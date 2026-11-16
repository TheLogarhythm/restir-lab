"""Offline normalization of frozen, fixed-view PT quality captures.

Native collector scripts are parsed as evidence, never imported or executed.
Historical runtime, asset and source paths are retained as provenance only.
"""
import ast
import math
import re

from records.models import CapturedFrame, RunRecord
from records.provenance import sha256
from records.validation import (artifact_path, capture_rows, checked_image,
                                integer, read_json, require_digest)

KINDS = frozenset(f"{prefix}_pt_{mode}_single_frame"
                  for prefix in ("cgns", "pdf_similarity")
                  for mode in ("temporal", "paper_setting"))


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _seed_policy(temporal, offset):
    if temporal:
        return ("path fixedSeed=frame-1; ReSTIR reuse seed=max(0,frame-2); first temporal pass skipped"
                if not offset else
                f"path fixedSeed={offset}+frame-1; ReSTIR reuse seed=0 on first frame, otherwise {offset}+frame-2; first temporal pass skipped")
    return ("fixedSeed=frame-1; temporal reuse disabled" if not offset else
            f"fixedSeed={offset}+frame-1; temporal reuse disabled")


def _call(node, name):
    return isinstance(node, ast.Call) and ast.unparse(node.func) == name


def _seed_expression(node, frame):
    if isinstance(node, ast.Constant) and type(node.value) is int:
        return node.value
    if isinstance(node, ast.Name) and node.id == "frame":
        return frame
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub)):
        a, b = _seed_expression(node.left, frame), _seed_expression(node.right, frame)
        return a + b if isinstance(node.op, ast.Add) else a - b
    raise ValueError("Unsupported collector seed expression")


def _subset(actual, expected):
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(k in actual and _subset(actual[k], v)
                                                for k, v in expected.items())
    if type(expected) is float:
        return type(actual) in (int, float) and math.isclose(actual, expected, rel_tol=1e-6, abs_tol=1e-7)
    return type(actual) is type(expected) and actual == expected


def _collector(script, resolved, options, offset, last):
    """Check the supported fresh-graph/static-clock collector and actual seed loop."""
    try:
        tree = ast.parse(script)
        graph_tree = ast.parse(resolved)
    except SyntaxError as exc:
        raise ValueError("Invalid saved collector/graph syntax") from exc
    loops = [n for n in tree.body if isinstance(n, ast.For) and isinstance(n.target, ast.Name)
             and n.target.id == "frame"]
    _require(len(loops) == 1, "Missing full collector frame loop")
    loop = loops[0]
    _require(ast.dump(loop.iter) == ast.dump(ast.parse(f"range(1, {last + 1})", mode="eval").body),
             "Collector frame budget differs")
    before = tree.body[:tree.body.index(loop)]
    assignments = {ast.unparse(t): n.value for n in before if isinstance(n, ast.Assign) for t in n.targets}
    for target, value in {"tracer.useFixedSeed": True, "m.scene.animated": False,
                          "camera.animated": False, "m.clock.framerate": 0, "m.clock.time": 0}.items():
        _require(target in assignments and ast.literal_eval(assignments[target]) == value,
                 "Missing static history/RNG control: " + target)
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
    for name in ("RenderGraph", "m.addGraph", "m.loadScene", "m.clock.pause"):
        _require(sum(_call(n, name) for n in calls) == 1
                 and any(_call(n, name) for stmt in before for n in ast.walk(stmt)),
                 "Collector must initialize one fresh graph/static scene: " + name)
    # Supported native collectors set both clocks before their only render.
    # Additional history/device mutations are unsupported, even with valid hashes.
    _require(len(loop.body) >= 3
             and isinstance(loop.body[0], ast.Assign)
             and [ast.unparse(t) for t in loop.body[0].targets] == ["tracer.fixedSeed"]
             and isinstance(loop.body[1], ast.Assign)
             and [ast.unparse(t) for t in loop.body[1].targets] == ["m.clock.frame"]
             and isinstance(loop.body[2], ast.Expr) and _call(loop.body[2].value, "m.renderFrame")
             and not loop.orelse and all(isinstance(n, ast.If) for n in loop.body[3:]),
             "Unsupported collector control order/history mutations")
    for node in ast.walk(loop):
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                name = ast.unparse(target)
                controlled = any(name == prefix or name.startswith(prefix + ".")
                                 or name.startswith(prefix + "[") for prefix in ("m", "tracer", "g", "camera"))
                _require(not controlled or node in loop.body[:2], "Collector mutates history/clock controls")
        if isinstance(node, ast.Call):
            name = ast.unparse(node.func)
            output_write = (isinstance(node.func, ast.Attribute) and node.func.attr == "write_text"
                            and _call(node.func.value, "Path") and len(node.func.value.args) == 1
                            and isinstance(node.func.value.args[0], ast.Constant)
                            and node.func.value.args[0].value == "scene-state.json")
            _require(name in {"m.renderFrame", "m.frameCapture.capture", "abs", "RuntimeError",
                              "camera_state", "json.dumps", "Path", "range"} or output_write,
                     "Unsupported call inside collector history loop: " + name)
    camera_functions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "camera_state"]
    _require(all(len(n.body) == 1 and isinstance(n.body[0], ast.Return)
                 and not any(isinstance(v, ast.Call) for v in ast.walk(n)) for n in camera_functions),
             "Unsupported camera-state callback")
    body_assignments = [(ast.unparse(t), n.value) for n in loop.body
                        if isinstance(n, ast.Assign) for t in n.targets]
    seed_nodes = [v for t, v in body_assignments if t == "tracer.fixedSeed"]
    all_seeds = [n for n in ast.walk(tree) if isinstance(n, ast.Assign)
                 and any(ast.unparse(t) == "tracer.fixedSeed" for t in n.targets)]
    _require(len(seed_nodes) == len(all_seeds) == 1, "Ambiguous collector seed assignment")
    _require(all(_seed_expression(seed_nodes[0], f) == offset + f - 1 for f in range(1, last + 1)),
             "Collector seed schedule differs")
    _require(any(t == "m.clock.frame" and isinstance(v, ast.Name) and v.id == "frame"
                 for t, v in body_assignments), "Missing per-frame clock control")
    render = [n for n in calls if _call(n, "m.renderFrame")]
    _require(len(render) == 1 and any(isinstance(n, ast.Expr) and n.value is render[0] for n in loop.body),
             "Collector must render once per frame")
    requested = [n for n in calls if _call(n, "createPass") and len(n.args) >= 2
                 and isinstance(n.args[0], ast.Constant) and n.args[0].value == "PathTracer"]
    _require(len(requested) == 1 and ast.literal_eval(requested[0].args[1]) == options,
             "Collector graph differs from capture settings")
    actual = [n for n in ast.walk(graph_tree) if isinstance(n, ast.Call)
              and isinstance(n.func, ast.Attribute) and n.func.attr == "create_pass"
              and len(n.args) == 3 and isinstance(n.args[0], ast.Constant)
              and n.args[0].value == "PathTracer"]
    _require(len(actual) == 1, "Missing resolved PathTracer graph")
    graph = ast.literal_eval(actual[0].args[2])
    _require(_subset(graph, options) and graph.get("fixedSeed") == offset + last - 1,
             "Resolved graph or final seed differs")
    return {k: v for k, v in graph.items() if k != "fixedSeed"}


def normalize(directory, manifest, manifest_digest):
    """Read a quality capture; timing-only and diagnostic outputs are unsupported."""
    m = manifest
    _require(m.get("kind") in KINDS and m.get("schema_version") == 1
             and m.get("status") == "completed" and m.get("backend") == "falcor",
             "Unsupported PT quality capture")
    width, height = (integer(v, "resolution", 1, 16384) for v in m["resolution"])
    warmup = integer(m["warmup_frames"], "warmup", 0, 512)
    schedule = m["capture_frames"]
    _require(isinstance(schedule, list) and bool(schedule), "Missing capture schedule")
    last = integer(schedule[-1], "last frame", 1, 16384)
    _require(all(type(f) is int for f in schedule) and schedule == list(range(warmup + 1, last + 1)),
             "Quality capture schedule differs")
    seed = integer(m.get("seed_offset", 0), "seed offset", 0, 2**32 - last)
    temporal = m["temporal_reuse"]
    _require(type(temporal) is bool and m["spp_per_frame"] == 1
             and m["image_accumulation"] is False, "Unsupported capture controls")
    _require(m["clock_policy"] == {"paused": True, "framerate": 0, "time": 0}, "Nonstatic capture clock")
    _require(m["seed_policy"] == _seed_policy(temporal, seed), "Unverified seed policy")
    method = m["requested_method"]
    _require(method in ("baseline", "cgns", "pdf-similarity"), "Unknown PT method")
    prefix = "pdf_similarity" if method == "pdf-similarity" else "cgns"
    _require(m["kind"] == f"{prefix}_pt_{'temporal' if temporal else 'paper_setting'}_single_frame",
             "Capture kind and reuse method differ")
    record_files = {"manifest.json": manifest_digest}
    script_path = artifact_path(directory, "render.py")
    script_digest = require_digest(m["render_script_sha256"])
    _require(sha256(script_path) == script_digest, "Saved collector hash changed")
    record_files["render.py"] = script_digest
    graph_path = artifact_path(directory, "resolved.py")
    record_files["resolved.py"] = sha256(graph_path)
    graph = _collector(script_path.read_text(encoding="utf-8-sig"),
                       graph_path.read_text(encoding="utf-8-sig"),
                       m["requested_graph_options"], seed, last)
    snapshots = {}
    for name in ("resolved-camera.json", "scene-state.json"):
        snapshots[name], record_files[name] = read_json(artifact_path(directory, name))
    camera = snapshots["resolved-camera.json"]
    _require(set(camera) == {"initial", "first_frame", "last_frame"}
             and camera["first_frame"].get("frame") == 1
             and camera["last_frame"].get("frame") == last, "Incomplete camera/history evidence")
    initial = camera["initial"]
    _require(initial.get("animated") is False and initial.get("apertureRadius") == 0
             and all({k: v for k, v in camera[n].items() if k != "frame"} == initial
                     for n in ("first_frame", "last_frame")), "Camera changed during static capture")
    scene = snapshots["scene-state.json"]
    lighting = {k: scene[k] for k in ("lights", "environment_present", "useAnalyticLights",
                                     "useEnvLight", "useEmissiveLights")}
    target = {"scene_id": m["scene_id"], "view_id": m["view_id"],
              "scene_config_sha256": require_digest(m["scene_config_sha256"]), "camera": initial}
    controls = tuple({"frame": f, "sampling_frame": seed + f - 1, "reset": f == 1,
                      "capture": f in schedule, "reuse_previous_frame": temporal and f > 1,
                      "clock_time": 0} for f in range(1, last + 1))
    rows = capture_rows(m["artifacts"], schedule)
    frames = []
    for index in schedule:
        row = rows[index]
        _require(type(row.get("seed")) is int and row["seed"] == seed + index - 1, "Path seed mismatch")
        if temporal:
            _require(type(row.get("reuse_seed")) is int
                     and row["reuse_seed"] == (0 if index == 1 else seed + index - 2), "Reuse seed mismatch")
        image = artifact_path(directory, row["hdr"])
        match = re.fullmatch(r"capture\.PathTracer\.color\.(\d+)(?:\.RGBA)?\.exr", image.name)
        _require(match is not None and int(match[1]) == index, "Capture filename/frame mismatch")
        digest = require_digest(row["sha256"])
        checked_image(image, digest, width, height, float32_exr=True)
        frames.append(CapturedFrame(index, image, digest, index == 1, seed + index - 1, target))
    identity = {k: m[k] for k in ("requested_method", "temporal_reuse", "build_commit",
                                  "runtime_verification", "runtime_spatial_shader_sha256",
                                  "asset_sha256", "source_sha256")}
    identity.update(graph=graph, camera=initial, warmup_frames=warmup, capture_frames=schedule,
                    resolution=[width, height], rng_schedule="fixedSeed=seed_offset+frame-1; prior path seed; first temporal pass skipped")
    return RunRecord("falcor", directory, manifest_digest, width, height, tuple(frames), seed,
                     controls, m, {"manifest": m, "record_files": record_files,
                     "transport": "native ReSTIR path tracing", "lighting_signature": lighting,
                     "comparison_identity": identity, "rng_schedule": identity["rng_schedule"]},
                     ("Seed ranges and fresh graph histories are checked; RNG statistical independence is an experiment assumption.",
                      "Reference transport equivalence and convergence are not certified by this reader."),
                     frozenset({"linear_rgb", "independent_trials"}))
