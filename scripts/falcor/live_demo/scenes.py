"""Resolve the Falcor demo's seven scene presets and prepare San Miguel's sky."""

import argparse
from dataclasses import dataclass
import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SKY = "assets/generated/san-miguel/live-default-sky.exr"


@dataclass(frozen=True)
class _ScenePreset:
    name: str
    exposure: float | None
    source: str | None = None
    rtxdi_camera: bool = False
    dont_optimize_materials: bool = False
    requires_sky: bool = False


# The order here is the order shown in the scene selector.
# Exposures for the five fixed views come from their display recipes.
_PRESETS = {
    "bistro-exterior": _ScenePreset("Bistro Exterior", 0.0),
    "bistro-interior": _ScenePreset(
        "Bistro Interior", 7.0, "scenes/configs/falcor/bistro-interior.pyscene",
        dont_optimize_materials=True,
    ),
    "classroom": _ScenePreset("Classroom", 0.0),
    # +8 EV makes the walls and foliage in the shaded courtyard visible.
    "san-miguel": _ScenePreset(
        "San Miguel", 8.0, "scenes/configs/falcor/san-miguel.pyscene",
        rtxdi_camera=True, requires_sky=True,
    ),
    "sun-temple": _ScenePreset(
        "Sun Temple", None, "assets/prepared/sun-temple/SunTemple_v4/SunTemple/SunTemple.pyscene",
        rtxdi_camera=True,
    ),
    "veach-ajar": _ScenePreset("Veach Ajar", 0.0),
    "zero-day-measure-seven": _ScenePreset("Zero Day Measure Seven", 6.0),
}
SCENE_IDS = {key: spec.name for key, spec in _PRESETS.items()}
SCENE_NAMES = tuple(SCENE_IDS.values())
FIXED_EXPOSURE = {key: spec.exposure for key, spec in _PRESETS.items() if not spec.rtxdi_camera}


def _read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _resolve_preset(scene_name, root):
    root = ROOT if root is None else Path(root).resolve(strict=True)
    key = scene_name.lower().replace(" ", "-")
    spec = _PRESETS.get(key)
    if spec is None:
        raise ValueError("Unknown live scene: " + str(scene_name))

    source, exposure = spec.source, spec.exposure
    if spec.rtxdi_camera:
        view = _read(root / "scenes/configs/rtxdi" / f"{key}.json")
        if exposure is None:
            exposure = view["preview"]["exposure_ev"]
    else:
        view = _read(root / "experiments/views/falcor-pt-spatial-comparison" / f"{key}.json")
        if source is None:
            source = _read(root / view["scene_profile"])["scene_source"]

    if spec.requires_sky and not (root / SKY).is_file():
        raise FileNotFoundError(
            "Prepare the San Miguel sky with python -m scripts.falcor.live_demo.scenes --prepare"
        )
    path = root / source
    if not path.is_file():
        raise FileNotFoundError(path)
    return spec, path, view["camera"], float(exposure)


def preset(scene_name, root=None):
    """Resolve the registered camera and an existing scene without importing Falcor."""
    _, source, camera, exposure = _resolve_preset(scene_name, root)
    return source, camera, exposure


def load_scene(m, scene_name, root=None):
    """Apply one preset in place and return the EV for the graph's tone mapper."""
    from falcor import SceneBuilderFlags, float3

    spec, source, view, exposure = _resolve_preset(scene_name, root)
    m.clock.pause()
    m.clock.time = 0
    if spec.dont_optimize_materials:
        m.loadScene(str(source), SceneBuilderFlags.DontOptimizeMaterials)
    else:
        m.loadScene(str(source))
    if m.scene is None:
        raise RuntimeError("Mogwai could not load " + scene_name)
    m.scene.animated = False
    camera = m.scene.camera
    camera.animated = False
    camera.position = float3(*view["position"])
    camera.target = float3(*(a + b for a, b in zip(view["position"], view["direction"])))
    camera.up = float3(*view["up"])
    camera.frameHeight = 24.0
    camera.focalLength = 12.0 / math.tan(math.radians(view["vertical_fov"]) / 2)
    camera.apertureRadius = 0.0
    if "near_plane" in view:
        camera.nearPlane = float(view["near_plane"])
    return exposure


def prepare_sky(root=ROOT):
    """Bake FullSample's default directional sun and procedural environment on the CPU."""
    target = Path(root) / SKY
    if target.is_file():
        return target

    import os
    import tempfile
    from ..donut_procedural_sky import generate_image

    target.parent.mkdir(parents=True, exist_ok=True)
    # FullSample SceneRenderer.cpp creates this sun when the imported glTF has none.
    rgb = generate_image(2048, 1024, (-0.15, 1.0, -0.3),
                         sun_irradiance=1.0, sun_angular_size_degrees=1.0)
    with tempfile.TemporaryDirectory(dir=target.parent) as folder:
        staged = Path(folder) / target.name
        try:
            import OpenEXR
        except ImportError:
            os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
            import cv2
            if not cv2.imwrite(str(staged), rgb[:, :, ::-1], [cv2.IMWRITE_EXR_TYPE, cv2.IMWRITE_EXR_TYPE_HALF]):
                raise RuntimeError("Failed to write San Miguel's EXR sky map")
        else:
            OpenEXR.File({}, {"RGB": rgb.astype("float16")}).write(str(staged))
        staged.replace(target)
    return target


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", action="store_true", help="Prepare the San Miguel sky")
    args = parser.parse_args(argv)
    if args.prepare:
        print(prepare_sky())
        return
    for name in SCENE_NAMES:
        source, _, ev = preset(name)
        print(f"{name}: {source.relative_to(ROOT)} (EV {ev:g})")


if __name__ == "__main__":
    main()
