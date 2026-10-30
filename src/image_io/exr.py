"""Linear RGB OpenEXR decoding without smoke-test or reference policy."""


def read_exr(path, *, require_float32=False):
    import OpenEXR
    import numpy as np

    with OpenEXR.File(str(path), separate_channels=True) as image:
        channels = image.channels()
        if not all(name in channels for name in ("R", "G", "B")):
            raise ValueError("Missing RGB channels")
        pixels = [channels[name].pixels for name in ("R", "G", "B")]
        if any(p.dtype.kind != "f" for p in pixels):
            raise ValueError("Expected floating-point RGB EXR")
        if require_float32 and any(p.dtype != np.float32 for p in pixels):
            raise ValueError("Expected FLOAT32 EXR")
        rgb = np.stack(pixels, axis=-1)
    if (
        rgb.ndim != 3
        or rgb.shape[-1] != 3
        or not rgb.size
        or not np.isfinite(rgb).all()
    ):
        raise ValueError("Malformed or nonfinite HDR")
    return rgb
