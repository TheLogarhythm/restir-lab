"""Editable catalog -> generated manifest. No renderer/GPU launch in this module."""
import copy
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re

ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
VIEW_FIELDS = {"id", "title", "camera", "exposure_ev", "render_overrides", "lighting_overrides", "indirect_mode"}
SETTING_FIELDS = {"frames", "averaged_tail_frames", "seed", "direct", "indirect", "pt_preset",
                  "max_bounces", "initial_paths_per_pixel_per_frame", "native_denoiser", "native_aa", "pdf_similarity"}


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save(path, value):
    """Atomic manifest updates prevent interruption from truncating prior state."""
    path = Path(path)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def utc():
    return datetime.now(timezone.utc).isoformat()


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode("utf-8")).hexdigest()


def identifier(value, name):
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise ValueError(f"{name} must use lowercase letters, digits and hyphens")


def checked_path(root, relative):
    path = (Path(root) / relative).resolve()
    if not path.is_relative_to(Path(root).resolve()):
        raise ValueError(f"Path escapes gallery: {relative}")
    return path


def dimensions(value):
    if not isinstance(value, list) or len(value) != 2 or any(type(x) is not int or not 1 <= x <= 16384 for x in value):
        raise ValueError("resolution must contain two integers in 1..16384")


def validate_settings(settings):
    unknown = set(settings) - SETTING_FIELDS
    if unknown:
        raise ValueError(f"Unknown render setting(s): {sorted(unknown)}")
    frames, count = settings["frames"], settings["averaged_tail_frames"]
    if type(frames) is not int or frames < 128 or type(count) is not int or not 1 <= count <= frames:
        raise ValueError("Use frames >= 128 and 1 <= averaged_tail_frames <= frames")
    fixed = {"direct": "ReSTIR DI", "native_denoiser": "OFF", "native_aa": "OFF", "pdf_similarity": False}
    for key, expected in fixed.items():
        if key in settings and settings[key] != expected:
            raise ValueError(f"{key} is fixed at {expected!r} for paired gallery previews")
    if settings.get("indirect", "ReSTIR PT") not in ("ReSTIR PT", "BRDF"):
        raise ValueError("indirect must be ReSTIR PT or BRDF")
    if settings.get("pt_preset", "ULTRA") not in ("ULTRA",):
        raise ValueError("The supported PT preset is ULTRA; other presets require renderer integration validation")


def validate_camera(camera):
    for field in ("position", "direction", "up"):
        v = camera[field]
        if not isinstance(v, list) or len(v) != 3 or any(type(x) not in (int, float) or not math.isfinite(x) for x in v):
            raise ValueError(f"camera.{field} must have three finite coordinates")
    d, u = camera["direction"], camera["up"]
    cross = [d[1]*u[2]-d[2]*u[1], d[2]*u[0]-d[0]*u[2], d[0]*u[1]-d[1]*u[0]]
    if math.hypot(*cross) < 1e-12:
        raise ValueError("camera.direction and up must be nonzero and not parallel")
    fov = camera["vertical_fov"]
    if type(fov) not in (int, float) or not math.isfinite(fov) or not 0 < fov < 180:
        raise ValueError("camera.vertical_fov must be between 0 and 180 degrees")


def select_views(plan, keys=None):
    available = {v["scene_id"] + "/" + v["id"]: v for v in plan["views"]}
    if keys is None:
        return list(available.values())
    unknown = set(keys) - available.keys()
    if unknown:
        raise ValueError(f"Unknown view(s): {', '.join(sorted(unknown))}; available: {', '.join(available)}")
    return [v for key, v in available.items() if key in keys]


def legacy_matches(root, view, native, settings):
    """Adopt an old completed pair only if its saved native config still matches."""
    try:
        record = read(checked_path(root, view["record"]))
        saved = read(checked_path(root, view["record"]).parent / "config.json")
        for config in (saved, native):
            config.pop("repository_root", None)
            config.pop("output", None)
        library = Path(settings["oidn_library"])
        return (saved == native and view.get("exposure_ev") == record["display"]["exposure_ev"]
                and library.is_file() and file_hash(library) == record["postprocessing"]["library_sha256"])
    except (OSError, ValueError, KeyError, TypeError):
        return False


def load_plan(root, build_config, scene_loader):
    root = Path(root)
    settings = read(root / "gallery.json")
    if settings["schema_version"] != 1:
        raise ValueError("Unsupported gallery.json schema_version")
    unknown = set(settings) - {"schema_version", "scene_order", "resolution", "oidn_library", "oidn_api_source",
                               "render_settings", "definition_snapshot", "scout"}
    if unknown:
        raise ValueError(f"Unknown gallery setting(s): {sorted(unknown)}")
    dimensions(settings["resolution"])
    validate_settings(settings["render_settings"])
    if "scout" in settings:
        dimensions(settings["scout"]["resolution"])
        validate_settings({k: v for k, v in settings["scout"].items() if k != "resolution"})
    previous = read(root / "manifest.json") if (root / "manifest.json").exists() else {}
    old_views = {(v["scene_id"], v["id"]): v for v in previous.get("views", [])}
    plan = copy.deepcopy(previous)
    plan.update({k: copy.deepcopy(v) for k, v in settings.items() if k != "scene_order"})
    plan.update(schema_version=2, scenes={}, views=[])
    files = {p.stem: p for p in sorted((root / "scenes").glob("*.json"))}
    order = settings.get("scene_order", [])
    if len(order) != len(set(order)) or any(sid not in files for sid in order):
        raise ValueError("scene_order must have unique IDs with existing scene config files")
    source_paths = [root / "gallery.json"]
    for sid in [*order, *(sid for sid in files if sid not in order)]:
        doc = read(files[sid])
        identifier(sid, "scene_id")
        if doc["schema_version"] != 1 or doc["scene_id"] != sid:
            raise ValueError(f"Scene ID/version mismatch: {files[sid]}")
        if set(doc) - {"schema_version", "scene_id", "title", "credit", "views"}:
            raise ValueError(f"Unknown scene config field(s): {files[sid]}")
        if (not isinstance(doc.get("title"), str) or not doc["title"].strip()
                or not isinstance(doc.get("credit"), str) or not doc["credit"].strip() or not doc.get("views")):
            raise ValueError(f"Scene needs a title, credit and at least one view: {sid}")
        scene = scene_loader(sid)
        entry = copy.deepcopy(previous.get("scenes", {}).get(sid, {}))
        entry.update(title=doc["title"], credit=doc["credit"], source_profile=scene["source"],
                     source_camera=scene["camera"], source_lighting=scene["lighting"], source_registry=scene["registry"])
        # Camera separation was an initial selection note, not a live config validator.
        entry.pop("camera_separation", None)
        plan["scenes"][sid] = entry
        source_paths.append(files[sid])
        seen, positions = set(), []
        for requested in doc["views"]:
            if set(requested) - VIEW_FIELDS:
                raise ValueError(f"Unknown view field(s) for {sid}: {sorted(set(requested) - VIEW_FIELDS)}")
            if "title" in requested and (not isinstance(requested["title"], str) or not requested["title"].strip()):
                raise ValueError(f"View title must be a nonempty string: {sid}")
            overrides = requested.get("lighting_overrides", {})
            if set(overrides) - scene["lighting"].keys():
                raise ValueError(f"Unknown lighting override for {sid}: {sorted(set(overrides) - scene['lighting'].keys())}")
            vid = requested["id"]
            identifier(vid, "view.id")
            if vid in seen:
                raise ValueError(f"Duplicate view ID: {sid}/{vid}")
            seen.add(vid)
            validate_settings({**settings["render_settings"], **requested.get("render_overrides", {})})
            camera = requested.get("camera")
            if camera is not None:
                validate_camera(camera)
                if any(math.dist(camera["position"], p) < 1e-6 for p in positions):
                    raise ValueError(f"Distinct view position required: {sid}/{vid}")
                positions.append(camera["position"])
            exposure = requested.get("exposure_ev")
            if exposure is not None and (type(exposure) not in (float, int) or not math.isfinite(exposure) or not -32 <= exposure <= 32):
                raise ValueError(f"exposure_ev must be null or finite in -32..32: {sid}/{vid}")
            if requested.get("indirect_mode", "RESTIRPT") not in ("RESTIRPT", "BRDF"):
                raise ValueError(f"Unsupported indirect_mode: {sid}/{vid}")
            old = old_views.get((sid, vid), {})
            view = {k: copy.deepcopy(v) for k, v in old.items() if k not in VIEW_FIELDS}
            view.update(copy.deepcopy(requested), scene_id=sid)
            view.setdefault("title", vid)
            if camera is None:
                view["status"] = "needs-camera"
                view.pop("requested_input_sha256", None)
            else:
                native = build_config(plan, view)
                key = fingerprint({"native": native, "exposure_ev": exposure,
                                   "postprocess": {"pipeline": "OIDN RT HDR HIGH color-only + ACES fitted sRGB v1",
                                                   "oidn_library": settings["oidn_library"]}})
                view["requested_input_sha256"] = key
                if not view.get("render_input_sha256") and old.get("status") == "completed":
                    if legacy_matches(root, view, copy.deepcopy(native), settings):
                        view["render_input_sha256"] = key
                view["status"] = ("completed" if view.get("render_input_sha256") == key and view.get("outputs")
                                  else "stale" if view.get("outputs") else "pending")
            plan["views"].append(view)
    if not plan["scenes"]:
        raise ValueError("No scene configs found in scenes/*.json")
    plan["configuration_sources"] = {p.relative_to(root).as_posix(): file_hash(p) for p in source_paths}
    summarize(plan)
    return plan


def summarize(plan):
    completed = [v for v in plan["views"] if v.get("status") == "completed"]
    plan["status"] = "completed" if len(completed) == len(plan["views"]) else "incomplete"
    plan["output_summary"] = {"scenes": len(plan["scenes"]), "views": len(plan["views"]),
                              "completed_views": len(completed), "pngs": len(completed)*2,
                              "resolution": plan["resolution"], "linear_hdr_pfm_retained": False}
    if plan["status"] != "completed":
        plan.pop("completed_utc", None)


def add_scene(root, sid, scene_loader):
    identifier(sid, "scene_id")
    path = Path(root) / "scenes" / (sid + ".json")
    if path.exists():
        raise ValueError(f"Scene already configured: {sid}; edit {path}")
    scene = scene_loader(sid)
    registry = scene["registry"]
    doc = {"schema_version": 1, "scene_id": sid, "title": sid.replace("-", " ").title(),
           "credit": registry.get("license", "Review THIRD_PARTY.md") + " | " + registry.get("source_url", ""),
           "views": [{"id": "view-a", "title": "Registered camera", "camera": scene["camera"], "exposure_ev": None},
                     {"id": "view-b", "title": "Choose a distinct camera", "camera": None, "exposure_ev": None}]}
    path.parent.mkdir(parents=True, exist_ok=True)
    save(path, doc)
    return path
