"""Exercise the demo controls and verify the resulting frames and history resets."""

import json

from ..runtime_common import sha256_file
from .evidence import check_capture_image, read_rendered_sequence
from .graph import METHODS, MODES
from .scenes import SCENE_NAMES


def step(scene, method, mode, label, *, camera=None, frames=None):
    result = {"Scene": scene, "Method": method, "Display": mode, "label": label,
              "frames": frames or (8 if mode == "Raw" else 16)}
    if camera:
        result["camera"] = camera
    return result


def acceptance_steps(suite, *, scenes=SCENE_NAMES):
    methods = ("CGNS", "PDF Similarity", "Original")
    rows = []
    classroom = suite == "classroom" or "Classroom" in scenes
    if classroom:
        for method in methods:
            for mode in MODES:
                label = (method + "-" + mode).lower().replace(" ", "-")
                rows.append(step("Classroom", method, mode, label))
                if mode == "Accumulation" and method == "CGNS":
                    for camera, suffix in (("Nudge camera right", "moved"), ("Reset camera", "restored")):
                        rows.append(step("Classroom", method, mode, label + "-" + suffix, camera=camera))
        rows.append(step("Classroom", "CGNS", "Raw", "return-cgns-raw"))
    if suite == "all":
        if classroom:
            rows.extend([
                step("Classroom", "CGNS", "Accumulation", "before-accum-method-switch"),
                {**step("Classroom", "PDF Similarity", "Accumulation", "after-accum-method-switch"),
                 "probe": "method-reset"},
                step("Classroom", "PDF Similarity", "NRD", "before-nrd-camera-move"),
                step("Classroom", "PDF Similarity", "NRD", "before-nrd-method-switch", camera="Nudge camera right"),
                step("Classroom", "CGNS", "NRD", "after-nrd-method-switch"),
                step("Classroom", "CGNS", "NRD", "nrd-camera-restored", camera="Reset camera"),
            ])
        for scene in scenes:
            if scene == "Classroom":
                continue
            for method in methods:
                for mode in MODES:
                    label = (scene + "-" + method + "-" + mode).lower().replace(" ", "-")
                    rows.append(step(scene, method, mode, label))
        if "Bistro Interior" in scenes:
            rows.append(step("Bistro Interior", "CGNS", "Raw", "return-bistro-interior"))
        if classroom:
            rows.append(step("Classroom", "CGNS", "Raw", "return-classroom"))
    return rows


def validate_sequence(rows):
    if not isinstance(rows, list) or not rows:
        raise ValueError("A sequence must be a nonempty list")
    for item in rows:
        if (item["Scene"] not in SCENE_NAMES or item["Method"] not in METHODS or item["Display"] not in MODES
                or not isinstance(item["label"], str) or not item["label"]
                or not all(c.isalnum() or c in "-_" for c in item["label"])
                or item.get("camera") not in (None, "Nudge camera right", "Reset camera")
                or type(item["frames"]) is not int or item["frames"] < 1):
            raise ValueError(f"Invalid sequence step: {item!r}")


def verify(output, config, pid):
    result = read_rendered_sequence(output, config["sequence"], pid)
    records = result["captures"]
    previous_scene, x_offset = None, 0.0
    for rec, requested in zip(records, config["sequence"]):
        mode = requested["Display"]
        if requested["Scene"] == "Classroom" and mode != "NRD" and not rec["raw_file"]:
            raise ValueError(f"Same-frame raw capture is missing: {rec['file']}")
        path = output / rec["file"]
        rec.update(check_capture_image(path, rec["resolution"]))
        rec["sha256"] = sha256_file(path)
        if previous_scene != rec["Scene"] or requested.get("camera") == "Reset camera":
            x_offset = 0.0
        if requested.get("camera") == "Nudge camera right":
            x_offset = 0.25
        previous_scene = rec["Scene"]
        for key in ("target", "position", "up"):
            expected = list(rec["preset_camera"][key])
            if key != "up":
                expected[0] += x_offset
            if max(abs(a - b) for a, b in zip(rec["camera"][key], expected)) > 0.001:
                raise ValueError("Camera pose mismatch: " + rec["label"])
    expected_probes = [row for row in config["sequence"]
                       if row["Display"] == "Accumulation" and row["Scene"] == "Classroom"
                       and (row.get("camera") or row.get("probe") == "method-reset")]
    reset_probes = result.get("reset_probes", [])
    if len(reset_probes) != len(expected_probes):
        raise ValueError("Missing first-frame accumulation reset comparison")
    for rec, row in zip(reset_probes, expected_probes):
        action = row.get("camera") or "method-switch-" + row["Method"]
        label = "first-" + action.lower().replace(" ", "-")
        if (rec["label"] != label or rec["pid"] != pid or rec["hwnd"] != result["hwnd"]
                or any(rec[key] != row[key] for key in ("Scene", "Method", "Display"))):
            raise ValueError(f"Unexpected accumulation reset probe for {row['label']}")
        compare_raw(output, rec, after_reset=True)
    for rec in records:
        if rec.get("raw_file"):
            compare_raw(output, rec)
    result["status"] = "passed"
    result["suite"] = config["suite"]
    (output / "acceptance.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf8")
    print(f"Verified {len(records)} captures from PID {pid} in {output}", flush=True)


def compare_raw(output, rec, *, after_reset=False):
    from PIL import Image, ImageChops

    with Image.open(output / rec["file"]) as shown, Image.open(output / rec["raw_file"]) as raw:
        if shown.size != raw.size:
            raise ValueError("Same-frame raw comparison has a different resolution: " + rec["file"])
        difference = ImageChops.difference(shown.convert("RGB"), raw.convert("RGB"))
        rec["same_as_raw"] = difference.getbbox() is None
        rec["max_channel_difference"] = max(upper for lower, upper in difference.getextrema())
    if after_reset and (rec["settled_frames"] != 1 or not rec["same_as_raw"]):
        raise ValueError("First frame after reset did not match the same-frame raw sample: " + rec["file"])
    if rec["Display"] == "Raw" and not rec["same_as_raw"]:
        raise ValueError("Raw did not match the same-frame path-tracer sample: " + rec["file"])
    if rec["Display"] == "Accumulation" and not after_reset and rec["settled_frames"] >= 8 and rec["same_as_raw"]:
        raise ValueError("Stationary accumulated output unexpectedly equals the simultaneous raw sample: " + rec["file"])
