# Renderer checks

Add meaningful numerical and small-scene checks as rendering code is integrated: controlled reservoir selection statistics, estimator/reference agreement, invalid values, reprojection/history resets, and repeatable captures.

Run `python -m unittest discover -s tests -v` for asset-conversion and launcher regressions (requires the asset Pillow dependency; no Blender/GPU needed). Numerical renderer tests remain future work. `python scripts/check_scaffold.py` checks repository structure, not rendering correctness.
