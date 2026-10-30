# Renderer checks

Add meaningful numerical and small-scene checks as rendering code is integrated: controlled reservoir selection statistics, estimator/reference agreement, invalid values, reprojection/history resets, and repeatable captures.

Run `python -B -m unittest discover -s tests -t . -v` for asset-conversion, launcher, multi-scene experiment and offline analysis regressions (install with `python -m pip install -e ".[exr]" -r scripts/run/requirements.txt`; no Blender/GPU needed). With MSVC, PDF tests execute shared direction-reservoir math and the adapted RTXDI spatial loops on deterministic inputs. GPU validation is recorded in the [implementation note](../docs/reproductions/pdf-similarity.md). `python scripts/check_scaffold.py` checks repository structure, not rendering correctness.

Run the object-material, emitter-visibility and authored-light conversion fixture with Blender: `blender --background --factory-startup --disable-autoexec --python-exit-code 1 --python tests/blender_classroom.py`.
For camera sensor-fit and pixel-aspect checks, use the same command with `tests/blender_camera.py`.
For real FBX frame baking, source visibility and camera alignment, use
`tests/blender_static_frame.py`; it also checks that default FBX exports retain animation.

Use ignored `tmp/` for disposable fixtures and logs; it can be removed at any time.
Set `TEMP` and `TMP` to its absolute path when running these checks to keep temporary files there.

## Test groups

The ordinary `python -B -m unittest discover -s tests -t . -v` command still discovers every unittest.
For a dependency-specific run, use:

```powershell
python -B scripts/check_tests.py --suite cpu
python -B scripts/check_tests.py --suite native
python -B scripts/check_tests.py --suite media
python -B scripts/check_tests.py --suite windows
```

The CPU group runs on every push and pull request; it needs the Python packages in
[scripts/run/requirements.txt](../scripts/run/requirements.txt) and the `exr` extra in
[pyproject.toml](../pyproject.toml), plus Git for isolated dependency fixtures, without downloaded scenes,
Blender, MSVC, FFmpeg or a GPU. Native checks compile production shader functions with MSVC
and need the pinned RTXDI/Donut sources. Media checks encode, probe and decode an actual
video with FFmpeg/ffprobe. Windows checks run the PowerShell supervisor with CPU stand-ins
and need an idle renderer/worker. An explicitly selected integration group fails when its
required checks are skipped. Discovery/import errors fail every group before filtering,
including `--list`. `--list` prints its test IDs; `--suite all` runs all groups.

The manually dispatched [integration workflow](../.github/workflows/integration.yml) keeps
native, Windows, media and Blender dependencies separate from the portable job.
The three Blender commands above remain the local integration entry points.

Shared fixtures live in `tests/fixtures/`: isolated worker imports, controlled capture records,
equal-time data and the MSVC/shader extraction harness. Assertions stay in their respective
test modules. Gallery tests are part of normal discovery in `workflows/test_gallery_catalog.py`.
The C++ fixture sources are retained; each checks a different mathematical or runtime contract.

## Test packages and fixture ownership

The test packages group checks by responsibility:

- `core/`: numerical contracts and image storage.
- `backends/`: renderer adapters and build/runtime contracts.
- `workflows/`: experiment scheduling, references, reporting and test tooling.
- `assets/`: scene conversion, installation and authored scene properties.
- `fixtures/`: reusable input builders and native compilation helpers.

Reusable fixture inputs belong in `fixtures/`: `provenance.py` owns lighting build
records, `legacy_artifacts.py` owns capture/planar-geometry setup for existing
analysis tests, and `cgns.py` supplies one-frame runtime records for CGNS and
geometry checks. Tests must not import other test modules for fixtures. Scenario
configs, expected values, numerical oracles, assertions and deliberate corruption
remain in their tests; hash refreshes stay explicit.

Use `-t .` with unittest discovery so modules have names such as
`tests.backends.test_rtxdi_runner`. A focused module can run with
`python -B -m unittest tests.core.test_covariance_metrics -v`; a group can run with
`python -B -m unittest discover -s tests/core -t . -v`.

Integration groups retain exact module/class prefixes under the `tests.`
namespace. New grouping or file moves must compare
`scripts/check_tests.py --suite all --list` and every integration-group inventory.
Similar numerical checks at pure-function, saved-file and launcher boundaries
protect different contracts and are retained. The Blender scripts and C++ fixture
sources stay at the top of `tests/` so their manual entry points remain stable.

## Shared library checks

The canonical implementations are under `src/{metrics,image_io,records,analysis,backends}`;
numerical tests import them directly. `core/test_shared_core.py` retains explicit
historical import compatibility and image-format boundaries.
`backends/test_saved_run_readers.py` tests backend records with tiny real PFM/EXR
files. `workflows/test_shared_analysis.py` covers offline CLI behavior and
independent-trial guards. These are portable CPU tests, with OpenEXR installed
through the `exr` extra above.

`fixtures/saved_runs.py` writes independent native-format fixtures for the shared
readers. Keep expected values, assertions, deliberate corruption and hash refreshes
explicit in the consuming tests.
