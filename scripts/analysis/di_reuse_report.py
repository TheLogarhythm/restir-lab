"""Compact scientific presentation of validated DI measurements."""
from collections import defaultdict
import csv
import json
import math
import os
import numpy as np
from experiment.images import preview_rgb

MODES = ("initial", "temporal", "spatial", "combined")
COLORS = dict(zip(MODES, ("#666666", "#0072B2", "#E69F00", "#009E73")))


def mean_gpu_time(rows):
    """Weight phase means by frames, then give each independent seed equal weight."""
    by_seed = defaultdict(list)
    for row in rows:
        by_seed[row["seed"]].append(row)
    means = [sum(r["gpu_ms"] * r["frames"] for r in group) / sum(r["frames"] for r in group)
             for group in by_seed.values()]
    return float(np.mean(means)) if means else None


def error_concentration(image, reference):
    """Fraction of squared RGB error in the worst 1% of pixels (rounded up)."""
    squared = np.mean((image - reference) ** 2, axis=2).ravel()
    total = float(squared.sum())
    count = max(1, math.ceil(squared.size * .01))
    return float(np.partition(squared, squared.size-count)[-count:].sum() / total) if total else 0.


def selected_endpoints(captures, summaries):
    """Use the static endpoint when available; otherwise the selected scenario."""
    result = []
    for scene in sorted({c["config"]["scene_id"] for c in captures}):
        scenarios = {c["config"]["scenario"] for c in captures if c["config"]["scene_id"] == scene}
        scenario = "static" if "static" in scenarios else sorted(scenarios)[0]
        rows = [r for r in summaries if r["scene"] == scene and r["scenario"] == scenario and r["region"] == "full"]
        last = max(r["frame"] for r in rows)
        result.extend(sorted((r for r in rows if r["frame"] == last), key=lambda r: MODES.index(r["mode"])))
    return result


def plot_trajectories(plt, output, captures, summaries, scenes, scenarios):
    fig, axes = plt.subplots(len(scenes), len(scenarios), squeeze=False, sharey="row",
                             figsize=(4 * len(scenarios), 2.65 * len(scenes)), layout="constrained")
    handles = {}
    for i, scene in enumerate(scenes):
        maximum = max(r["rmae_mean"] + (r["rmae_std"] or 0) for r in summaries
                      if r["scene"] == scene and r["region"] == "full")
        for j, scenario in enumerate(scenarios):
            ax = axes[i, j]
            group = [c for c in captures if (c["config"]["scene_id"], c["config"]["scenario"]) == (scene, scenario)]
            if not group:
                ax.set_axis_off()
                continue
            for mode in MODES:
                points = sorted((r for r in summaries if (r["scene"], r["scenario"], r["mode"], r["region"]) ==
                                 (scene, scenario, mode, "full")), key=lambda r: r["frame"])
                if points:
                    yerr = [p["rmae_std"] or 0 for p in points] if any(p["seeds"] > 1 for p in points) else None
                    handle = ax.errorbar([p["frame"] for p in points], [p["rmae_mean"] for p in points],
                                         yerr=yerr, color=COLORS[mode], marker="o", markersize=3,
                                         linewidth=1.2, capsize=2, label=mode.capitalize())
                    handles[mode] = handle
            definition = group[0]["config"]["definition"]
            if scenario == "motion":
                ax.axvspan(definition["motion"]["start_frame"]+1, definition["motion"]["end_frame"], color="gray", alpha=.1)
            elif scenario == "reset":
                ax.axvline(definition["reset_frame"], color="gray", linestyle="--", linewidth=1)
            ax.set(title=f"{scene} / {scenario}", xlabel="Logical frame", ylim=(0, max(maximum * 1.08, 1e-6)))
            if j == 0:
                ax.set_ylabel("Linear RGB RMAE")
    fig.legend([handles[m] for m in MODES if m in handles],
               [m.capitalize() for m in MODES if m in handles], loc="outside upper center", ncols=4, frameon=False)
    fig.savefig(output / "error-trajectories.png", dpi=160)
    plt.close(fig)


def plot_images(plt, output, captures, references, reference_root, endpoints, scenes, load_image):
    fig, axes = plt.subplots(len(scenes), 5, squeeze=False, figsize=(12, 2.15 * len(scenes)), layout="constrained")
    tails = []
    for i, scene in enumerate(scenes):
        row = next(r for r in endpoints if r["scene"] == scene)
        selected = [c for c in captures if (c["config"]["scene_id"], c["config"]["scenario"], c["frame"]["frame"]) ==
                    (scene, row["scenario"], row["frame"])]
        seed = min(c["config"]["seed"] for c in selected)
        selected = [c for c in selected if c["config"]["seed"] == seed]
        if len({c["key"] for c in selected}) != 1:
            raise ValueError("Representative images have different reference targets")
        reference = load_image(reference_root / references[selected[0]["key"]]["image"])
        exposure = selected[0]["config"]["preview"]["exposure_ev"]
        for ax in axes[i]:
            ax.set_axis_off()
        axes[i, 0].imshow(preview_rgb(reference, exposure))
        axes[i, 0].set_title(f"{scene}\nReference / f{row['frame']} / seed {seed}", fontsize=8)
        for c in selected:
            mode = c["config"]["mode"]
            image = load_image(c["image"])
            ax = axes[i, MODES.index(mode)+1]
            ax.imshow(preview_rgb(image, exposure))
            ax.set_title(mode.capitalize(), fontsize=8)
            tails.append({"scene": scene, "scenario": row["scenario"], "mode": mode, "frame": row["frame"],
                          "seed": seed, "top_1pct_squared_error_share": error_concentration(image, reference)})
    fig.savefig(output / "representative-images.png", dpi=160)
    plt.close(fig)
    return tails


def figures(output, captures, summaries, references, reference_root, endpoints, load_image):
    os.environ.setdefault("MPLCONFIGDIR", str(output / ".matplotlib"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    scenes = sorted({c["config"]["scene_id"] for c in captures})
    scenarios = [s for s in ("static", "motion", "reset") if any(c["config"]["scenario"] == s for c in captures)]
    style = {"font.family": "DejaVu Sans", "font.size": 9, "axes.spines.top": False,
             "axes.spines.right": False, "axes.grid": True, "grid.alpha": .18}
    with plt.rc_context(style):
        plot_trajectories(plt, output, captures, summaries, scenes, scenarios)
        tails = plot_images(plt, output, captures, references, reference_root, endpoints, scenes, load_image)
    return tails


def write_report(output, captures, summaries, timing_rows, references, reference_root, load_image):
    endpoints = selected_endpoints(captures, summaries)
    tails = figures(output, captures, summaries, references, reference_root, endpoints, load_image)
    with (output / "tail-diagnostics.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(tails[0]))
        writer.writeheader()
        writer.writerows(tails)
    ready = all(references[c["key"]]["converged"] for c in captures)
    seeds = sorted({c["config"]["seed"] for c in captures})
    configs = {c["directory"]: c["config"] for c in captures}
    settings = set()
    for c in configs.values():
        d = c["definition"]
        settings.add(f"{c['width']} x {c['height']}; local/environment/distant candidates "
                     f"{d['initial_local_candidates']}/{d['initial_environment_candidates']}/{d['initial_infinite_candidates']}; "
                     f"{d['spatial_neighbors']} spatial neighbors, {d['spatial_radius']} px radius; history limit {d['max_history_length']}")
    hardware = sorted({c["manifest"].get("gpu", "unrecorded GPU") for c in captures})
    lines = ["# ReSTIR DI baseline evaluation", "", "## Experimental design", "",
             f"Controlled ablation of initial sampling, temporal reuse, spatial reuse, and combined reuse: "
             f"{len(configs)} runs, baseline seed(s) {', '.join(map(str,seeds))}. "
             "Camera paths, candidate budgets, lighting and materials are matched across modes; denoising and AA are disabled.", "",
             "Settings: " + " / ".join(sorted(settings)) + ". GPU record: " + "; ".join(hardware) + ".", "",
             "Primary metric: RMAE = mean(|I-R|)/(mean(|R|)+1e-12), over linear RGB. "
             "NRMSE = sqrt(mean((I-R)^2)/(mean(R^2)+1e-12)) additionally exposes large errors. Lower is better.", "",
             "## Endpoint accuracy and cost", "",
             "Image error is measured at the final saved frame shown in the table, using static runs where available. "
             "GPU cost is the mean over static frames 33 onward "
             "(Steady GPU ms); for other scenarios it covers the full sequence. "
             "This is a fixed-parameter comparison, not an equal-time comparison.", "",
             "| Scene / sequence | Frame | Mode | RMAE | NRMSE | Steady GPU ms* |",
             "|---|---:|---|---:|---:|---:|"]
    costs = {}
    def number(row, metric):
        value = f"{row[metric+'_mean']:.4f}"
        return value if row[metric+'_std'] is None else value + f" ± {row[metric+'_std']:.4f}"
    for r in endpoints:
        times = [t for t in timing_rows if (t["scene"],t["scenario"],t["mode"]) == (r["scene"],r["scenario"],r["mode"])
                 and (r["scenario"] != "static" or t["phase"] == "steady")]
        cost = mean_gpu_time(times)
        costs[(r["scene"], r["mode"])] = cost
        cost_text = "—" if cost is None else f"{cost:.2f}"
        lines.append(f"| {r['scene']} / {r['scenario']} | {r['frame']} | {r['mode']} | {number(r,'rmae')} | {number(r,'nrmse')} | {cost_text} |")
    lines += ["", "*Non-static selections use full-sequence GPU means. Timing excludes export/present and does not measure real-time FPS.", ""]
    if not ready:
        lines += ["**Provisional:** at least one reference fails the precision recheck; endpoint rankings below are descriptive only.", ""]
    for scene in sorted({r["scene"] for r in endpoints}):
        rows = [r for r in endpoints if r["scene"] == scene]
        best = min(rows, key=lambda r:r["rmae_mean"])
        initial = next((r for r in rows if r["mode"] == "initial"), None)
        text = f"- **{scene}:** {best['mode']} has the lowest observed endpoint RMAE"
        if initial and initial["rmae_mean"] > 0 and best["mode"] != "initial":
            text += f", {100*(1-best['rmae_mean']/initial['rmae_mean']):.1f}% below initial-only"
            base_cost, best_cost = costs[(scene,"initial")], costs[(scene,best["mode"])]
            if base_cost and best_cost is not None:
                text += f" at {best_cost/base_cost:.2f}x its measured GPU cost"
        text += "."
        squared_best = min(rows, key=lambda r:r["nrmse_mean"])
        if squared_best["mode"] != best["mode"]:
            text += f" NRMSE instead favors {squared_best['mode']}; the ranking depends on the error metric."
            tail = next(t for t in tails if t["scene"] == scene and t["mode"] == best["mode"])
            text += (f" For {best['mode']}, the worst 1% of pixels contribute "
                     f"{100*tail['top_1pct_squared_error_share']:.2f}% of squared error in the illustrated seed.")
        lines.append(text)
    lines += ["", "## Temporal behavior", "", "![Full-image error across saved frames](error-trajectories.png)", "",
              "Markers are saved captures; connecting lines interpolate between measurements. Gray spans mark camera motion; "
              "dashed lines mark history reset. Axes share an error scale within each scene."]
    reset = [r for r in summaries if r["scenario"] == "reset" and r["region"] == "full"]
    reset_ratios = []
    recovered = []
    for scene in sorted({r["scene"] for r in reset}):
        config = next(c for c in configs.values() if c["scene_id"] == scene and c["scenario"] == "reset")
        at = config["definition"]["reset_frame"]
        points = {r["frame"]:r["rmae_mean"] for r in reset if r["scene"] == scene and r["mode"] == "temporal"}
        if at in points and at-1 in points and points[at-1]>0:
            reset_ratios.append(f"{scene} {points[at]/points[at-1]:.2f}x")
            if max(points) > at:
                recovered.append(points[max(points)] < points[at])
    if reset_ratios:
        lines += ["", "Temporal-only RMAE ratios at reset relative to the preceding captured frame: " + "; ".join(reset_ratios) + ". "
                  "Clearing reservoirs removes historical reuse; current-frame spatial sampling remains available. "
                  + ("Endpoint errors are below the reset-frame errors in these sequences."
                     if recovered and all(recovered) else "Subsequent captures show the evolution of the rebuilt history.")]
    if any(c["scenario"]=="motion" for c in configs.values()):
        lines += ["", "The motion test uses constant-velocity camera translation with fixed orientation. "
                  "Frames around motion start/stop are separate measurements. Error changes during motion combine "
                  "view-dependent sampling difficulty and reuse behavior; they do not isolate temporal artifacts."]
    lines += ["", "[Representative endpoint images](representative-images.png) use the recorded fixed exposure within each scene; "
              "the numerical metrics use untransformed HDR. [Tail diagnostics](tail-diagnostics.csv) record the squared-error share "
              "of the worst 1% of pixels for these images.", "", "## Reference acceptance and limits", ""]
    for scene in sorted({c["config"]["scene_id"] for c in captures}):
        keys={c["key"] for c in captures if c["config"]["scene_id"]==scene}
        checks=[json.loads((reference_root/references[k]["convergence"]).read_text(encoding="utf-8")) for k in sorted(keys)]
        ratios=sorted({c["reference_noise_ratio"] for c in checks})
        budgets=[c.get("samples_per_class_per_stream",c["checkpoints"][-1]["samples_per_class_per_stream"]) for c in checks]
        budget=str(min(budgets)) if min(budgets)==max(budgets) else f"{min(budgets)}–{max(budgets)}"
        lines.append(f"- {scene}: {len(keys)} reference view(s), {budget} samples/light class/stream; acceptance ratio "
                     + "/".join(f"{v:g}" for v in ratios) + ".")
    lines += ["", "References average two independent conventional sampling streams. Half-stream disagreement and checkpoint change "
              "must both remain below the recorded fraction of the best baseline RMAE for two successive checkpoints. "
              + ("All selected references pass the current recheck. " if ready else "Some selected references fail the current recheck. ")
              + "This empirical criterion does not detect shared bias; larger acceptance ratios permit more reference uncertainty.", "",
              ("Single baseline seed: these are observed outcomes, without repeat-to-repeat uncertainty estimates. " if len(seeds)==1 else
               "Error entries show the mean ± sample standard deviation across baseline seeds where available. ")
              + "The reference shares RTXDI materials and approximate glass composition. This evaluation establishes neither physical "
              "ground truth nor reproduction of the original paper's performance.", "",
              "[All capture metrics](metrics.csv) · [Seed summaries](summary.csv) · [Phase timings](timings.csv) · [Provenance](analysis.json)", ""]
    (output/"summary.md").write_text("\n".join(lines),encoding="utf-8")
    return {"plots":["error-trajectories.png","representative-images.png"],"reference_converged":ready}
