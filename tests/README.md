# Renderer checks

Add meaningful numerical and small-scene checks as rendering code is integrated: controlled reservoir selection statistics, estimator/reference agreement, invalid values, reprojection/history resets, and repeatable captures.

Run `python -m unittest discover -s tests -v` for asset-conversion, launcher, multi-scene experiment and offline analysis regressions (install scripts/run/requirements.txt; no Blender/GPU needed). Numerical renderer tests remain future work. `python scripts/check_scaffold.py` checks repository structure, not rendering correctness.

Run the object-material, emitter-visibility and authored-light conversion fixture with Blender: `blender --background --factory-startup --disable-autoexec --python-exit-code 1 --python tests/blender_classroom.py`.
For camera sensor-fit and pixel-aspect checks, use the same command with `tests/blender_camera.py`.

Use ignored `tmp/` for disposable fixtures and logs; it can be removed at any time.
Set `TEMP` and `TMP` to its absolute path when running these checks to keep temporary files there.
