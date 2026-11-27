"""Compatibility entry point for the Falcor live scene presets."""

from .live_demo.scenes import FIXED_EXPOSURE, ROOT, SCENE_IDS, SCENE_NAMES, SKY, load_scene, main, prepare_sky, preset

__all__ = ["FIXED_EXPOSURE", "ROOT", "SCENE_IDS", "SCENE_NAMES", "SKY", "load_scene", "main", "prepare_sky", "preset"]

if __name__ == "__main__":
    main()
