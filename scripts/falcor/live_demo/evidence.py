"""Check the renderer state and pixels captured by automated demo runs."""

import hashlib
import json

from .graph import METHODS, MODES, SOURCES


def read_rendered_sequence(output, rows, pid, *, require_native_display=False, exact_resolution=None):
    result = json.loads((output / "renderer-complete.json").read_text(encoding="utf8"))
    hwnd = result["hwnd"]
    if result["pid"] != pid or not hwnd or len(result["captures"]) != len(rows):
        raise ValueError("Renderer identity or capture count mismatch")
    for rec, row in zip(result["captures"], rows):
        mode = row["Display"]
        expected = {key: row[key] for key in ("Scene", "Method", "Display", "label")}
        expected.update(pid=pid, hwnd=hwnd, visible=True,
                        method_id=METHODS[row["Method"]], display_input=SOURCES[mode],
                        tone_mapper_raw_input=mode == "Raw", accumulation_bypassed=mode != "Accumulation")
        if exact_resolution is not None:
            expected["resolution"] = exact_resolution
        if require_native_display or "tone_mapper_display_mode" in rec:
            expected.update(tone_mapper_display_mode=MODES.index(mode), nrd_passes_enabled=mode == "NRD")
        for key, wanted in expected.items():
            if rec.get(key) != wanted:
                raise ValueError(f"{row['label']}: expected {key}={wanted!r}, got {rec.get(key)!r}")
        if rec["settled_frames"] < row["frames"]:
            raise ValueError(f"Insufficient settled frames for {row['label']}")
    return result


def check_capture_image(path, resolution, *, hash_pixels=False):
    from PIL import Image

    with Image.open(path) as image:
        rgb = image.convert("RGB")
        extrema = rgb.getextrema()
        if image.size != tuple(resolution) or all(high - low < 2 for low, high in extrema):
            raise ValueError(f"Unexpected or constant rendered image: {path.name}")
        evidence = {"rgb_range": extrema}
        if hash_pixels:
            evidence["rgb_sha256"] = hashlib.sha256(rgb.tobytes()).hexdigest()
        return evidence
