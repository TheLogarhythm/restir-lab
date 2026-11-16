"""Analyze saved Falcor PDF PT scout captures; never launch or modify a renderer.

Use the Python environment in build/falcor/verify-env (numpy and OpenEXR).
Input layout is ROOT/cases/*/manifest.json with the EXRs beside each manifest,
as produced by spatial_capture.launch. Directory names are not interpreted.
Use --plan scouts for pdf_pt_scouts.cases(): seed-zero diagnostics, four paired
Classroom brightness seeds, and the three-frame Bistro running check. A JSON
plan can instead contain {"cases": [{"scene_id": ..., "view_id": ..., "profile": ...,
"seed_offset": ..., "capture_frames": [...]}]}; capture_frames, resolution and
temporal_reuse are optional constraints. Without a plan, require the full matrix.
Only completed attempts are eligible; the latest completed attempt for the same
scene/view/scenario/mode/resolution/profile/seed wins. Superseded failures remain
listed. A missing frame, profile, FLOAT32 RGBA channel or provenance record is
reported explicitly, never interpreted as a successful equality check.

Exit codes: 0 = requested checks passed, 1 = numerical/provenance failure,
2 = incomplete evidence. Finite-seed brightness differences are descriptive;
they do not establish bias or reference error. Frames are averaged inside each
seed before estimating variation across independent seed offsets.
The optional --aov-atol allowance applies only to color comparisons between a
diagnostic capture and a color-only capture. It does not change the one/native
or zero/center comparisons, diagnostic-channel checks, or reported raw deltas.
"""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re

import numpy as np

PROFILES = ("baseline", "normal", "one", "zero", "center", "observe", "native")
PAIRS = (("one", "baseline"), ("one", "native"), ("native", "baseline"),
         ("zero", "center"), ("normal", "observe"))
AOV_COLOR_ONLY_PAIRS = (("one", "baseline"), ("native", "baseline"), ("normal", "observe"))
AOVS = {"emission": "nrdEmission", "moment": "nrdDiffuseRadianceHitDist",
        "pair": "nrdSpecularRadianceHitDist", "initial": "nrdResidualRadianceHitDist"}
LUMA = np.array([.2126, .7152, .0722], dtype=np.float64)
SEED_UNIT = "seed_offset; captured frames within each seed are averaged first"


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _status(statuses):
    values = set(statuses)
    return "failed" if "failed" in values else "incomplete" if values & {"missing", "incomplete"} else "passed"


def _identity(manifest):
    method = manifest.get("requested_method")
    profile = "baseline" if method == "baseline" else manifest.get("pdf_profile", "normal")
    if method not in ("baseline", "pdf-similarity") or profile not in PROFILES:
        raise ValueError("Not a baseline/PDF PT validation capture")
    resolution = manifest.get("resolution")
    frames = manifest.get("capture_frames")
    seed = manifest.get("seed_offset", 0)
    if (not isinstance(resolution, list) or len(resolution) != 2
            or any(type(x) is not int or x <= 0 for x in resolution)):
        raise ValueError("Missing/invalid resolution")
    if (not isinstance(frames, list) or not frames or frames != sorted(set(frames))
            or any(type(x) is not int or x < 1 for x in frames)):
        raise ValueError("Missing/invalid capture_frames")
    if type(seed) is not int or seed < 0:
        raise ValueError("Invalid seed_offset")
    if not isinstance(manifest.get("scene_id"), str) or not manifest["scene_id"]:
        raise ValueError("Missing scene_id")
    if not isinstance(manifest.get("view_id"), str) or not manifest["view_id"]:
        raise ValueError("Missing view_id")
    if type(manifest.get("temporal_reuse")) is not bool:
        raise ValueError("Missing/invalid temporal_reuse")
    context = (manifest["scene_id"], manifest["view_id"],
               str(manifest.get("validation_scenario", manifest.get("scenario", "static"))),
               manifest["temporal_reuse"], tuple(resolution))
    return context, seed, profile


def _context(context):
    return dict(zip(("scene_id", "view_id", "scenario", "temporal_reuse", "resolution"),
                    (*context[:4], list(context[4]))))


def load_plan(value):
    """Resolve the bounded scout plan or explicit JSON cases without running it."""
    if value is None:
        return None
    if value == "scouts":
        from scripts.falcor.pdf_pt_scouts import VIEWS, cases
        value = []
        configs = {}
        for label, profile, seed in cases():
            path = VIEWS / (label + ".json")
            if label not in configs:
                configs[label] = json.loads(path.read_text(encoding="utf-8-sig"))
            config = configs[label]
            value.append({"scene_id": config["scene_id"], "view_id": config["view_id"],
                          "case_label": label, "view_config": path.relative_to(Path(__file__).resolve().parents[2]).as_posix(),
                          "view_config_sha256": sha256(path), "profile": profile, "seed_offset": seed,
                          "capture_frames": list(range(1, 4 if label == "bistro-interior" else 13)),
                          "resolution": [96, 64], "temporal_reuse": True})
    elif isinstance(value, (str, Path)):
        value = json.loads(Path(value).read_text(encoding="utf-8-sig"))
    if isinstance(value, dict):
        value = value.get("cases")
    if not isinstance(value, list) or not value:
        raise ValueError("A validation plan needs a nonempty cases list")
    result, keys = [], set()
    for entry in value:
        if (not isinstance(entry, dict) or not isinstance(entry.get("scene_id"), str)
                or not isinstance(entry.get("view_id"), str) or not entry["view_id"]
                or entry.get("profile") not in PROFILES or type(entry.get("seed_offset", 0)) is not int
                or entry.get("seed_offset", 0) < 0):
            raise ValueError("Invalid planned case")
        entry = dict(entry, seed_offset=entry.get("seed_offset", 0))
        key = (entry["scene_id"], entry["view_id"], entry["profile"], entry["seed_offset"])
        if key in keys:
            raise ValueError("Duplicate planned scene/view/profile/seed")
        keys.add(key)
        for field in ("capture_frames", "resolution"):
            if field in entry and (not isinstance(entry[field], list) or not entry[field]
                                   or any(type(x) is not int or x < 1 for x in entry[field])):
                raise ValueError("Invalid planned " + field)
        if "capture_frames" in entry and entry["capture_frames"] != sorted(set(entry["capture_frames"])):
            raise ValueError("Invalid planned capture_frames")
        if "resolution" in entry and len(entry["resolution"]) != 2:
            raise ValueError("Invalid planned resolution")
        if "temporal_reuse" in entry and type(entry["temporal_reuse"]) is not bool:
            raise ValueError("Invalid planned temporal_reuse")
        result.append(entry)
    return result


def _read_exr(path, channels):
    import OpenEXR
    with OpenEXR.File(str(path), separate_channels=True) as image:
        data = image.channels()
        missing = [name for name in channels if name not in data]
        if missing:
            raise ValueError("Missing " + ",".join(missing) + " channel in " + path.name)
        pixels = [np.array(data[name].pixels, copy=True) for name in channels]
    if any(value.dtype != np.float32 for value in pixels):
        raise ValueError("Expected FLOAT32 " + channels + " EXR: " + path.name)
    result = np.stack(pixels, axis=-1)
    if result.ndim != 3 or not result.size:
        raise ValueError("Malformed EXR: " + path.name)
    return result


def difference_stats(left, right, *, channels="RGB", atol=0., rtol=0., top=8):
    """Report actual differing pixels, including their zero-based image positions."""
    a, b = np.asarray(left), np.asarray(right)
    if a.shape != b.shape or a.ndim != 3 or a.shape[-1] != len(channels):
        raise ValueError("Image dimensions/channel counts differ")
    if a.dtype != np.float32 or b.dtype != np.float32 or not np.isfinite(a).all() or not np.isfinite(b).all():
        raise ValueError("Comparison needs finite FLOAT32 images")
    bits = a.view(np.uint32) != b.view(np.uint32)
    delta = a.astype(np.float64) - b
    absolute = np.abs(delta)
    mismatched = np.any(bits, axis=-1)
    close = np.abs(delta) <= atol + rtol * np.abs(b)
    passed = not np.any(bits) if atol == 0 and rtol == 0 else bool(np.all(close))
    location = list(np.unravel_index(np.argmax(absolute), absolute.shape))
    if absolute[tuple(location)] == 0 and np.any(bits):
        location = list(np.argwhere(bits)[0])
    order = np.argsort(np.max(absolute, axis=-1).ravel(), kind="stable")[::-1]
    worst = []
    for flat in order:
        y, x = np.unravel_index(flat, mismatched.shape)
        if not mismatched[y, x]:
            continue
        worst.append({"x": int(x), "y": int(y), "max_abs": float(np.max(absolute[y, x])),
                      "left": [float(v) for v in a[y, x]], "right": [float(v) for v in b[y, x]]})
        if len(worst) == top:
            break
    result = {"status": "passed" if passed else "failed", "bitwise_equal": not bool(np.any(bits)),
              "pixels": int(mismatched.size), "mismatch_pixels": int(mismatched.sum()),
              "mismatch_channels": int(bits.sum()), "max_abs": float(absolute.max()),
              "mean_abs": float(absolute.mean()),
              "max_abs_location": {"x": int(location[1]), "y": int(location[0]), "channel": channels[location[2]]},
              "worst_pixels": worst}
    if channels == "RGB":
        signed = delta @ LUMA
        result.update(mean_signed_luminance_difference=float(signed.mean()),
                      mean_absolute_luminance_difference=float(np.abs(signed).mean()))
    return result


def _diagnostic_inventory(directory, profile, frames, issue):
    """Check an optional capture-time RGBA checksum sidecar, including its set."""
    path = directory / "pdf-diagnostics.json"
    if not path.exists():
        return None, {"status": "absent", "checksum_policy": "legacy EXRs hashed during analysis"}
    summary = {"path": path.name, "sha256": sha256(path), "status": "passed"}
    records = {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (ValueError, OSError) as error:
        issue("failed", "Invalid diagnostic sidecar JSON: " + str(error))
        return records, summary
    if not isinstance(data, dict):
        issue("failed", "Invalid diagnostic sidecar object")
        return records, summary
    if data.get("profile") != profile:
        issue("failed", "Diagnostic sidecar profile differs from manifest")
    artifacts = data.get("artifacts")
    if not isinstance(artifacts, list):
        issue("failed", "Invalid diagnostic sidecar inventory")
        artifacts = []
    labels = ("emission", "moment") if profile == "native" else tuple(AOVS) if profile not in ("normal", "baseline") else ()
    expected = {(frame, label) for frame in frames for label in labels}
    outputs = {"PathTracer." + output: label for label, output in AOVS.items()}
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            issue("failed", "Invalid diagnostic sidecar artifact")
            continue
        frame, output, name, digest = (artifact.get(key) for key in ("frame", "output", "hdr", "sha256"))
        label = outputs.get(output) if isinstance(output, str) else None
        if (type(frame) is not int or label is None or not isinstance(name, str)
                or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", digest)):
            issue("failed", "Invalid diagnostic sidecar frame/output/path/SHA256")
            continue
        key = (frame, label)
        if key in records:
            issue("failed", "Duplicate diagnostic sidecar inventory entry", frame)
            continue
        filename = r"capture\." + re.escape(output) + r"\." + str(frame) + r"(?:\.(?:RGBA|RGB))?\.exr"
        if not re.fullmatch(filename, name) or (directory / name).resolve().parent != directory.resolve():
            issue("failed", "Diagnostic sidecar path differs from its frame/output", frame)
            continue
        if "channels" in artifact and artifact["channels"] not in ("RGBA", ["R", "G", "B", "A"]):
            issue("failed", "Diagnostic sidecar channels do not declare RGBA", frame)
            continue
        records[key] = artifact
    if set(records) != expected:
        issue("failed", "Diagnostic sidecar inventory differs from expected profile/frame outputs")
    present = {path.name for output in AOVS.values() for path in directory.glob("capture.PathTracer." + output + ".*.exr")}
    if present != {artifact["hdr"] for artifact in records.values()}:
        issue("failed", "Diagnostic sidecar inventory differs from diagnostic EXRs present")
    summary["record_count"] = len(records)
    return records, summary


def _load_case(root, path, manifest, context, seed, profile, issues):
    directory = path.parent
    row = {**_context(context), "seed_offset": seed, "profile": profile,
           "manifest": path.relative_to(root).as_posix(), "manifest_sha256": sha256(path),
           "capture_frames": manifest["capture_frames"], "artifacts": []}
    case = {"row": row, "manifest": manifest, "context": context, "seed": seed,
            "profile": profile, "color": {}, "aovs": defaultdict(dict), "issues": []}

    def issue(kind, detail, frame=None, source=None):
        value = {"status": kind, "manifest": row["manifest"], "detail": detail}
        if frame is not None:
            value["frame"] = frame
        if source is not None:
            value["source"] = source
        issues.append(value)
        case["issues"].append(value)

    sidecar, row["diagnostic_sidecar"] = _diagnostic_inventory(
        directory, profile, manifest["capture_frames"],
        lambda kind, detail, frame=None: issue(kind, detail, frame, source="pdf-diagnostics.json"))

    artifact_list = manifest.get("artifacts")
    if not isinstance(artifact_list, list):
        artifact_list = []
        issue("missing", "Missing manifest.artifacts checksum inventory")
    records = {}
    for artifact in artifact_list:
        if not isinstance(artifact, dict) or "hdr" not in artifact:
            continue
        frame = artifact.get("frame")
        if type(frame) is not int or frame < 1:
            issue("failed", "Invalid color artifact frame")
            continue
        if frame in records:
            issue("failed", "Duplicate color artifact record", frame)
        records[frame] = artifact

    def read(path, channels, frame, expected_sha=None, checksum_source="manifest"):
        def problem(kind, detail):
            issue(kind, detail, frame, source=checksum_source)
        if not path.is_file():
            problem("missing", "Missing EXR: " + path.name)
            return None
        actual = sha256(path)
        row["artifacts"].append({"frame": frame, "path": path.relative_to(directory).as_posix(),
                                 "sha256": actual, "checksum_source": checksum_source if expected_sha else "computed_during_analysis"})
        if expected_sha and actual != expected_sha.lower():
            problem("failed", "EXR SHA256 differs from " + checksum_source + ": " + path.name)
            return None
        try:
            image = _read_exr(path, channels)
        except (ImportError, ValueError, RuntimeError, OSError) as error:
            problem("missing", str(error))
            return None
        if image.shape[:2] != (context[4][1], context[4][0]):
            problem("failed", "EXR resolution differs from manifest: " + path.name)
            return None
        finite = np.all(np.isfinite(image), axis=-1)
        if not finite.all():
            y, x = np.argwhere(~finite)[0]
            problem("failed", f"Nonfinite EXR: {path.name}, first pixel x={x},y={y}, count={int((~finite).sum())}")
            return None
        return image

    for frame in manifest["capture_frames"]:
        artifact = records.get(frame)
        if artifact is None or not isinstance(artifact.get("hdr"), str) or not artifact.get("sha256"):
            issue("missing", "Missing color artifact path/SHA256 for captured frame", frame)
        else:
            name = artifact["hdr"]
            target = (directory / name).resolve()
            if not target.is_relative_to(directory.resolve()):
                issue("failed", "Color artifact escapes its case directory", frame)
            elif not re.fullmatch(r"capture\.PathTracer\.color\." + str(frame) + r"(?:\.(?:RGBA|RGB))?\.exr", target.name):
                issue("failed", "Color artifact filename differs from its declared frame", frame)
            else:
                value = read(target, "RGB", frame, artifact["sha256"])
                if value is not None:
                    case["color"][frame] = value
                    if not np.any(value > 0):
                        issue("failed", "Color EXR is entirely black/nonpositive", frame)
                expected_seed = seed + frame - 1
                if "seed" in artifact and artifact["seed"] != expected_seed:
                    issue("failed", "Artifact sample seed differs from seed_offset+frame-1", frame)
        required = (() if profile in ("baseline", "normal") else
                    ("emission", "moment") if profile == "native" and sidecar is not None else
                    ("emission",) if profile == "native" else tuple(AOVS))
        for label in required:
            pattern = re.compile(r"capture\.PathTracer\." + re.escape(AOVS[label]) + r"\." + str(frame) + r"(?:\.(?:RGBA|RGB))?\.exr$")
            matches = [item for item in directory.glob("capture.PathTracer." + AOVS[label] + ".*.exr") if pattern.fullmatch(item.name)]
            if len(matches) != 1:
                issue("missing", f"Expected exactly one {AOVS[label]} RGBA EXR; found {len(matches)}", frame,
                      source="pdf-diagnostics.json" if sidecar is not None else None)
                continue
            record = sidecar.get((frame, label)) if sidecar is not None else None
            if sidecar is not None and (record is None or record["hdr"] != matches[0].name):
                issue("failed", "Diagnostic EXR missing/mismatched in sidecar inventory: " + matches[0].name, frame, source="pdf-diagnostics.json")
                continue
            value = read(matches[0], "RGBA", frame, record["sha256"] if record else None,
                         checksum_source="pdf-diagnostics.json" if record else "computed_during_analysis")
            if value is not None:
                case["aovs"][label][frame] = value
    if sidecar is not None:
        row["diagnostic_sidecar"]["status"] = _status(value["status"] for value in case["issues"] if value.get("source") == "pdf-diagnostics.json")
    row["status"] = _status(value["status"] for value in case["issues"])
    return case


def _diagnostics(case, issues, *, atol=1e-5, rtol=1e-5):
    profile, aovs, row = case["profile"], case["aovs"], case["row"]
    if profile in ("baseline", "normal", "native"):
        return {"status": "not_applicable", "reason": "No complete PDF direction/pair diagnostic in this profile"}
    result = {"status": "passed", "invariants": {}, "natural_h": {"fractional_pixels": 0, "zero_pixels": 0, "one_pixels": 0},
              "history": {"accumulated_pixels": 0, "maximum_count": 0.},
              "initial_contributions": {key: {"positive_pixels": 0, "sum_weight": 0.} for key in ("primary_nee", "indirect_nee", "bsdf_hit")},
              "limitations": ["h=0 with B_neighbor=0 also includes native geometry/screen rejection; zero alone does not prove PDF rejection.",
                              "A positive history count proves accepted direction evidence; it does not establish temporal unbiasedness."]}
    params = case["manifest"].get("pdf_shader_parameters") or {}
    limit = float(params.get("history_limit", np.inf))
    common = sorted(set.intersection(*(set(aovs[name]) for name in AOVS)))
    if common != row["capture_frames"]:
        result["status"] = "incomplete"

    def invariant(name, mask, frame):
        mask = np.asarray(mask)
        count = int(np.count_nonzero(mask))
        record = result["invariants"].setdefault(name, {"violations": 0, "first_location": None})
        record["violations"] += count
        if count and record["first_location"] is None:
            y, x = np.argwhere(mask)[0]
            record["first_location"] = {"frame": frame, "x": int(x), "y": int(y)}

    for frame in common:
        emission, moment, pair, initial = (aovs[name][frame].astype(np.float64) for name in AOVS)
        m, weight, phat, count = np.moveaxis(emission, -1, 0)
        h, neighbor_m, confidence, central_m = np.moveaxis(pair, -1, 0)
        energy = moment[..., 3]
        surface = np.any(emission != 0, axis=-1)
        active = surface & (neighbor_m > 0)
        invariant("nonnegative_reservoir", np.any(emission < 0, axis=-1), frame)
        invariant("nonnegative_confidence", (neighbor_m < 0) | (confidence < 0) | (central_m < 0), frame)
        invariant("h_range", (h < 0) | (h > 1), frame)
        invariant("confidence_sum", surface & ~np.isclose(confidence, central_m + neighbor_m, atol=atol, rtol=rtol), frame)
        invariant("output_M", surface & ~np.isclose(m, confidence, atol=atol, rtol=rtol), frame)
        invariant("moment_energy", energy < 0, frame)
        invariant("moment_vector_bound", np.linalg.norm(moment[..., :3], axis=-1) > energy + atol + rtol * np.abs(energy), frame)
        invariant("history_limit", count > limit + atol, frame)
        if frame == 1 or not row["temporal_reuse"]:
            invariant("history_start_or_disabled", count > 1 + atol, frame)
        invariant("zero_energy_count", (energy == 0) & (count != 0), frame)
        invariant("initial_nonnegative", np.any(initial < 0, axis=-1), frame)
        invariant("initial_partition", ~np.isclose(initial[..., :3].sum(axis=-1), initial[..., 3], atol=atol, rtol=rtol), frame)
        invariant("current_energy_within_history", initial[..., 3] > energy + atol + rtol * np.abs(energy), frame)
        if frame == 1 or not row["temporal_reuse"]:
            invariant("initial_energy_without_history", ~np.isclose(initial[..., 3], energy, atol=atol, rtol=rtol), frame)
        if profile == "one":
            invariant("forced_one", active & (h != 1), frame)
        if profile in ("zero", "center"):
            invariant("forced_zero", surface & ((h != 0) | (neighbor_m != 0)), frame)
        if profile == "observe":
            invariant("cold_start_fallback", active & (count <= 1) & (h != 1), frame)
        natural = result["natural_h"]
        natural["fractional_pixels"] += int(np.count_nonzero(active & (h > 0) & (h < 1)))
        natural["zero_pixels"] += int(np.count_nonzero(surface & (h == 0)))
        natural["one_pixels"] += int(np.count_nonzero(active & (h == 1)))
        result["history"]["accumulated_pixels"] += int(np.count_nonzero(count > 1 + atol))
        result["history"]["maximum_count"] = max(result["history"]["maximum_count"], float(np.max(count)))
        for index, label in enumerate(result["initial_contributions"]):
            result["initial_contributions"][label]["positive_pixels"] += int(np.count_nonzero(initial[..., index] > 0))
            result["initial_contributions"][label]["sum_weight"] += float(initial[..., index].sum())
    for name, record in result["invariants"].items():
        if record["violations"]:
            result["status"] = "failed"
            issues.append({"status": "failed", "manifest": row["manifest"], "detail": f"Diagnostic invariant {name}: {record['violations']} pixel-frame violations",
                           "first_location": record["first_location"]})
    return result


def _compare(left, right, context, seed, *, atol, rtol, aov_atol):
    a, b = left["profile"] if left else None, right["profile"] if right else None
    # Names are assigned by the caller even if an entire side is missing.
    row = {**_context(context), "seed_offset": seed, "frames": []}
    if left is None or right is None:
        row.update(status="missing", detail="Missing paired profile")
        return row
    aov_applies = (a, b) in AOV_COLOR_ONLY_PAIRS or (b, a) in AOV_COLOR_ONLY_PAIRS
    color_atol = max(atol, aov_atol) if aov_applies else atol
    row["color_tolerance"] = {"atol": color_atol, "rtol": rtol, "aov_atol_applies": aov_applies}
    row.update(left_manifest=left["row"]["manifest"], right_manifest=right["row"]["manifest"])
    statuses = [left["row"]["status"], right["row"]["status"]]
    mismatched_metadata = [key for key in ("scene_config_sha256", "asset_sha256", "source_sha256",
                           "experiment_config_sha256", "requested_graph_options", "clock_policy")
                           if key in left["manifest"] and key in right["manifest"] and left["manifest"][key] != right["manifest"][key]]
    if mismatched_metadata:
        statuses.append("failed")
        row["metadata_mismatch"] = mismatched_metadata
    if left["row"]["capture_frames"] != right["row"]["capture_frames"]:
        statuses.append("missing")
        row["detail"] = "Capture schedules differ"
    frames = sorted(set(left["row"]["capture_frames"]) | set(right["row"]["capture_frames"]))
    for frame in frames:
        item = {"frame": frame}
        if frame not in left["color"] or frame not in right["color"]:
            item.update(status="missing", detail="Missing validated color EXR")
            statuses.append("missing")
        else:
            item["color"] = difference_stats(left["color"][frame], right["color"][frame], atol=color_atol, rtol=rtol)
            item["status"] = item["color"]["status"]
            statuses.append(item["status"])
        if {a, b} in ({"one", "native"}, {"zero", "center"}):
            if frame in left["aovs"]["emission"] and frame in right["aovs"]["emission"]:
                # Native alpha is zero by design. Only RGB is (M,weight,pHat).
                item["reservoir_M_weight_pHat"] = difference_stats(left["aovs"]["emission"][frame][..., :3], right["aovs"]["emission"][frame][..., :3],
                                                                       channels="MWP", atol=atol, rtol=rtol)
                statuses.append(item["reservoir_M_weight_pHat"]["status"])
            else:
                item["reservoir_M_weight_pHat"] = {"status": "missing"}
                statuses.append("missing")
        if {a, b} == {"zero", "center"}:
            for name, label in (("moment", "direction_history"), ("initial", "initial_direction_contributions")):
                if frame in left["aovs"][name] and frame in right["aovs"][name]:
                    item[label] = difference_stats(left["aovs"][name][frame], right["aovs"][name][frame],
                                                   channels="RGBA", atol=atol, rtol=rtol)
                else:
                    item[label] = {"status": "missing"}
                statuses.append(item[label]["status"])
        item["status"] = _status([item.get("status", "passed"),
                                  *(value["status"] for value in item.values() if isinstance(value, dict) and "status" in value)])
        statuses.append(item["status"])
        row["frames"].append(item)
    row["status"] = _status(statuses)
    return row


def _brightness(cases, issues, min_seeds, plan):
    grouped = defaultdict(list)
    for case in cases:
        if case["color"]:
            grouped[(case["context"], case["profile"])].append(case)
    results, means = [], {}
    for (context, profile), members in sorted(grouped.items()):
        samples, seed_images, frame_count = [], {}, 0
        schedules = {tuple(case["row"]["capture_frames"]) for case in members}
        expected_seeds = ({entry["seed_offset"] for entry in plan
                           if entry["scene_id"] == context[0] and entry["view_id"] == context[1] and entry["profile"] == profile}
                          if plan is not None else None)
        require_repeats = plan is None or profile in ("baseline", "normal") and len(expected_seeds) > 1
        for case in sorted(members, key=lambda value: value["seed"]):
            if sorted(case["color"]) != case["row"]["capture_frames"]:
                continue
            image = np.mean([value.astype(np.float64) for _, value in sorted(case["color"].items())], axis=0)
            luminance = float((image @ LUMA).mean())
            samples.append({"seed_offset": case["seed"], "mean_luminance": luminance,
                            "captured_frames": len(case["color"]),
                            "path_seed_range_including_warmup": [case["seed"], case["seed"] + max(case["row"]["capture_frames"]) - 1]})
            seed_images[case["seed"]] = image
            frame_count += len(case["color"])
        count = len(samples)
        values = np.array([value["mean_luminance"] for value in samples])
        ranges = sorted(value["path_seed_range_including_warmup"] for value in samples)
        disjoint = all(previous[1] < current[0] for previous, current in zip(ranges, ranges[1:]))
        expected_present = expected_seeds is None or expected_seeds == set(seed_images)
        record = {**_context(context), "profile": profile, "independent_seed_count": count,
                  "captured_frame_count": frame_count, "seed_samples": samples,
                  "seed_blocks_disjoint": disjoint,
                  "expected_seed_offsets": sorted(expected_seeds) if expected_seeds is not None else None,
                  "all_expected_seed_offsets_present": expected_present,
                  "mean_luminance": float(values.mean()) if count else None,
                  "sample_std_across_seeds": float(values.std(ddof=1)) if count > 1 and disjoint else None,
                  "standard_error_across_seeds": float(values.std(ddof=1) / np.sqrt(count)) if count > 1 and disjoint else None,
                  "status": "incomplete" if not expected_present or not disjoint or len(schedules) != 1 or require_repeats and count < min_seeds
                            else "passed" if require_repeats else "descriptive"}
        if require_repeats and count < min_seeds:
            issues.append({"status": "missing", **_context(context), "profile": profile,
                           "detail": f"Only {count} independent seeds; at least {min_seeds} requested"})
        if len(schedules) != 1:
            issues.append({"status": "missing", **_context(context), "profile": profile, "detail": "Different frame schedules across seed repeats"})
        if not disjoint:
            issues.append({"status": "missing", **_context(context), "profile": profile, "detail": "Overlapping path seed ranges cannot establish independent seed repeats"})
            record["independent_seed_count"] = None
        if not expected_present:
            issues.append({"status": "missing", **_context(context), "profile": profile, "detail": "Brightness seed set differs from the explicit plan"})
        results.append(record)
        if count:
            means[(context, profile)] = (seed_images, {row["seed_offset"]: row["mean_luminance"] for row in samples},
                                        {case["seed"]: tuple(case["row"]["capture_frames"]) for case in members}, disjoint)
    differences = []
    for (context, profile), (images, seeds, schedules, disjoint) in sorted(means.items()):
        if profile != "normal" or (context, "baseline") not in means:
            continue
        baseline_images, baseline_seeds, baseline_schedules, baseline_disjoint = means[(context, "baseline")]
        paired = sorted(set(seeds) & set(baseline_seeds))
        matched = set(seeds) == set(baseline_seeds) and all(schedules[seed] == baseline_schedules[seed] for seed in paired)
        values = np.array([seeds[seed] - baseline_seeds[seed] for seed in paired]) if matched else np.array([])
        if not matched:
            issues.append({"status": "missing", **_context(context), "detail": "normal_vs_baseline brightness requires identical seed sets and capture schedules"})
        image_difference = None
        if matched:
            image_difference = difference_stats(np.mean([images[seed] for seed in paired], axis=0).astype(np.float32),
                                                np.mean([baseline_images[seed] for seed in paired], axis=0).astype(np.float32))
            image_difference.pop("status")
            image_difference["equality_expected"] = False
        differences.append({**_context(context), "pair": "normal_vs_baseline", "interpretation": "Descriptive difference, not reference error or a bias test",
                            "status": "passed" if matched and disjoint and baseline_disjoint else "incomplete",
                            "normal_seed_offsets": sorted(seeds), "baseline_seed_offsets": sorted(baseline_seeds),
                            "paired_seed_count": len(paired), "paired_mean_luminance_difference": float(values.mean()) if len(values) else None,
                            "paired_difference_standard_error": float(values.std(ddof=1) / np.sqrt(len(values))) if len(values) > 1 and disjoint and baseline_disjoint else None,
                            "mean_image_difference": image_difference})
    return results, differences


def analyze(root, *, atol=0., rtol=0., aov_atol=0., min_seeds=2, plan=None):
    """Return a JSON-compatible report from one validation root's saved cases."""
    if (not all(np.isfinite(value) for value in (atol, rtol, aov_atol)) or min(atol, rtol, aov_atol) < 0
            or type(min_seeds) is not int or min_seeds < 1):
        raise ValueError("Invalid tolerance/minimum-seed settings")
    root = Path(root).resolve()
    plan = load_plan(plan)
    expected = {(entry["scene_id"], entry["view_id"], entry["profile"], entry["seed_offset"]): entry for entry in plan} if plan is not None else None
    issues, excluded, candidates = [], [], defaultdict(list)
    directory = root if root.name == "cases" else root / "cases"
    for path in sorted(directory.glob("*/manifest.json")):
        try:
            manifest = json.loads(path.read_text(encoding="utf-8-sig"))
            context, seed, profile = _identity(manifest)
        except (ValueError, TypeError, OSError) as error:
            issues.append({"status": "missing", "manifest": path.relative_to(root).as_posix(), "detail": "Invalid manifest: " + str(error)})
            continue
        if expected is not None and (context[0], context[1], profile, seed) not in expected:
            excluded.append({"manifest": path.relative_to(root).as_posix(), "status": manifest.get("status"), "reason": "outside_explicit_plan"})
            continue
        candidates[(context, seed, profile)].append((path, manifest))
    selected = []
    for (context, seed, profile), attempts in sorted(candidates.items()):
        completed = [item for item in attempts if item[1].get("status") == "completed"]
        if not completed:
            issues.append({"status": "missing", **_context(context), "seed_offset": seed, "profile": profile, "detail": "No completed attempt"})
            for path, manifest in attempts:
                excluded.append({"manifest": path.relative_to(root).as_posix(), "status": manifest.get("status"), "reason": "no_completed_attempt", "error": manifest.get("error")})
            continue
        chosen = max(completed, key=lambda item: (item[1].get("ended_utc", ""), item[0].stat().st_mtime_ns, str(item[0])))
        for path, manifest in attempts:
            if path != chosen[0]:
                excluded.append({"manifest": path.relative_to(root).as_posix(), "status": manifest.get("status"),
                                 "reason": "superseded_completed_attempt" if manifest.get("status") == "completed" else "superseded_failed_attempt"})
        case = _load_case(root, *chosen, context, seed, profile, issues)
        if expected is not None:
            entry = expected[(context[0], context[1], profile, seed)]
            for field in ("capture_frames", "resolution", "temporal_reuse", "view_id"):
                if field in entry and entry[field] != chosen[1].get(field):
                    issues.append({"status": "failed", "manifest": case["row"]["manifest"], "detail": "Captured " + field + " differs from explicit plan"})
                    case["row"]["status"] = "failed"
        selected.append(case)
    if expected is not None:
        present = {(case["context"][0], case["context"][1], case["profile"], case["seed"]) for case in selected}
        for key in sorted(set(expected) - present):
            issues.append({"status": "missing", "scene_id": key[0], "view_id": key[1], "profile": key[2], "seed_offset": key[3], "detail": "Missing completed planned case"})
    if not candidates:
        issues.append({"status": "missing", "detail": "No validation manifests under cases/*/manifest.json"})
    for case in selected:
        case["row"]["diagnostics"] = _diagnostics(case, issues)
        case["row"]["status"] = _status((case["row"]["status"], case["row"]["diagnostics"]["status"]))
    grouped = defaultdict(dict)
    for case in selected:
        grouped[(case["context"], case["seed"])][case["profile"]] = case
    comparisons = []
    for (context, seed), profiles in sorted(grouped.items()):
        for left, right in PAIRS:
            if expected is not None and not all((context[0], context[1], profile, seed) in expected for profile in (left, right)):
                continue
            comparison = _compare(profiles.get(left), profiles.get(right), context, seed, atol=atol, rtol=rtol, aov_atol=aov_atol)
            comparison["pair"] = left + "_vs_" + right
            comparisons.append(comparison)
            if comparison["status"] in ("missing", "incomplete", "failed"):
                issues.append({"status": comparison["status"], **_context(context), "seed_offset": seed, "detail": comparison["pair"] + ": " + comparison["status"]})
        observe = profiles.get("observe")
        if observe:
            diagnostic = observe["row"]["diagnostics"]
            params = observe["manifest"].get("pdf_shader_parameters") or {}
            can_have_history = context[3] and max(observe["row"]["capture_frames"]) > 1 and params.get("history_decay", 1) > 0
            if can_have_history:
                if not diagnostic["history"]["accumulated_pixels"]:
                    issues.append({"status": "missing", "manifest": observe["row"]["manifest"], "detail": "No accumulated direction history observed"})
                if not diagnostic["natural_h"]["fractional_pixels"]:
                    issues.append({"status": "missing", "manifest": observe["row"]["manifest"], "detail": "No active fractional natural h observed"})
            for label, record in diagnostic["initial_contributions"].items():
                if not record["positive_pixels"]:
                    issues.append({"status": "missing", "manifest": observe["row"]["manifest"], "detail": "No positive initial direction evidence observed for " + label})
    brightness, differences = _brightness(selected, issues, min_seeds, plan)
    return {"schema_version": 1, "kind": "saved_falcor_pdf_pt_gpu_validation", "root": str(root),
            "validator_sha256": sha256(__file__),
            "status": _status(value["status"] for value in issues), "comparison_tolerance": {"atol": atol, "rtol": rtol, "aov_atol": aov_atol},
            "aov_atol_scope": [left + "_vs_" + right for left, right in AOV_COLOR_ONLY_PAIRS],
            "seed_unit": SEED_UNIT, "minimum_independent_seeds": min_seeds,
            "plan": plan,
            "cases": [case["row"] for case in selected], "excluded_attempts": excluded,
            "comparisons": comparisons, "brightness": brightness, "descriptive_method_differences": differences,
            "issues": issues, "limitations": ["Only completed cases in this root are analyzed; failed/superseded attempts remain listed.",
                "Diagnostic EXRs are checked against pdf-diagnostics.json when present; legacy captures without sidecars are identified by checksum_source.",
                "No reference error, unbiasedness, equal-time quality, or performance conclusion follows from these scouts.",
                "Positive per-category direction weights demonstrate execution, not exhaustive transport coverage."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--output", type=Path, help="Write JSON here; otherwise emit JSON on stdout")
    parser.add_argument("--atol", type=float, default=0.)
    parser.add_argument("--rtol", type=float, default=0.)
    parser.add_argument("--aov-atol", type=float, default=0.,
                        help="Color-only allowance for one/baseline, native/baseline and normal/observe; default 0")
    parser.add_argument("--min-seeds", type=int, default=2)
    parser.add_argument("--plan", help="scouts, or a JSON file with a cases list; omit for the full matrix")
    args = parser.parse_args()
    result = analyze(args.root, atol=args.atol, rtol=args.rtol, aov_atol=args.aov_atol,
                     min_seeds=args.min_seeds, plan=args.plan)
    encoded = json.dumps(result, indent=2, allow_nan=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf8")
        print(result["status"] + ": " + str(args.output))
    else:
        print(encoded, end="")
    return {"passed": 0, "failed": 1, "incomplete": 2}[result["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
