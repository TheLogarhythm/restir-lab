# Shared metrics and offline saved-result analysis

The shared Python library lives in `src`. Metrics and image I/O have one canonical implementation; historical `experiment.*` imports are compatibility exports. Existing renderer commands retain source-checkout bootstraps, so moving the numerical code does not require changing those commands.

## Layout and scope

- `metrics/`: SMAPE/TRMAE, spatial/temporal covariance, neighborhoods and pixel regions, sequence aggregation.
- `image_io/`: lossless PFM/PFM.gz and EXR loading, with preview conversion separate from metric input.
- `records/`: typed run/capture records, path/hash validation and source fingerprints.
- `backends/rtxdi/records.py`: schema-3 direct-lighting baseline reader with the full control/RNG schedule and native target/lighting provenance.
- `backends/falcor/records.py`: schema-1 smoke reader, including historical records lacking retained build/graph snapshots.
- `analysis/`: saved-image summaries, explicit-reference SMAPE and conservative independent-repeat analysis.

The shared execution layer, Falcor trial/RNG controls, GPU timing, reference generation and cross-backend transport validation remain future work. Existing campaign-specific runners and policies remain in place. No rendering is needed for the commands below.

## Install and inspect saved runs

Use a project-local Python 3.11+ environment. Replace `runs/example-run` with a completed saved run:

```powershell
python -m venv build/analysis/venv
./build/analysis/venv/Scripts/python.exe -m pip install -e ".[exr]"
./build/analysis/venv/Scripts/python.exe -B scripts/analyze_run.py --run runs/example-run --output runs/analysis/inspection
```

The same command accepts a completed RTXDI baseline run directory. Always choose a new output directory outside the input run. `analysis.json` retains input and package hashes, image statistics, backend identity and evidence limitations. The reader validates recorded HDR images, retained preview hashes and metadata; it never launches a renderer, imports saved graph scripts, queries a GPU or compares historical source hashes with today's checkout.

Add `--reference-image path/to/reference.exr` (or `.pfm`/`.pfm.gz`) to compute per-capture SMAPE. This is an explicitly supplied image: matching dimensions and valid HDR do not certify matching transport, material interpretation or reference convergence. The report labels this distinction. PNG previews are not metric input.

For Python usage after installation:

```python
from records import read_run, load_frame
from metrics.error_metrics import smape
from analysis.saved_runs import describe_run, analyze_repeats

run = read_run("runs/example-run")
rgb = load_frame(run, 1)
summary = describe_run(run)
```

`read_run` returns `RunRecord` and `CapturedFrame` views. Missing seed/reset/sampling metadata remains `None`; it is not synthesized. Each subsequent `load_frame` rechecks saved metadata, image digest and dimensions. File references must remain inside the run directory. Reading does not rewrite native manifests or images.

`analyze_repeats(runs, frames, lag=3, radius=8)` uses the same sequence metric implementation with verified image loads. It requires multiple eligible runs of one method: unique seeds, nonoverlapping recorded RNG streams with one-step progression and matching constant offsets, matching full controls (including unmeasured frames), settings, targets and lighting/build provenance. Its result includes the measured input image hashes, run/config hashes, package-source hashes and per-frame reference paths/hashes. `references=` accepts one HDR path or a frame-to-path mapping; the same uncertified-reference label applies, and each read plus analysis completion rechecks the reference digest. The existing array API also remains available for callers with independently validated data and custom loaders. Caller-provided region masks remain the caller's provenance responsibility.

## Historical limits

Falcor setup runs are unaccumulated native frame outputs; frame 16 does not mean a 16-spp averaged image. Their default RNG reruns are deterministic, not independent trials, and they have no recorded per-frame reset/sampling schedule. The adapter therefore rejects these records for independent-repeat covariance. Recorded GPU time is absent; startup/export wall time is not substituted for it.

Older Falcor runs may lack copied build/graph files. Their retained image hashes can still be checked; the missing evidence is reported. Resolved camera/graph files were not hash-bound by the old launcher, so this phase does not certify automatic reference compatibility for them. Source and asset hash lists are historical provenance, not instructions to access the current checkout.

The RTXDI baseline reader deliberately supports the existing frozen direct-lighting format. It requires a valid SHA-256 executable fingerprint and a nonempty shader inventory with nonblank names and valid SHA-256 values. Missing or malformed estimator-build evidence is rejected before the record can be used for repeat analysis. Reference checkpoints, compacted campaign archives, and arbitrary native renderer outputs retain their own readers. Shared HDR decoding permits finite black and negative values; the Falcor startup smoke check separately requires nonblack output.

## Migration and reproducibility

New run/batch source inventories include Python files in the five shared packages under `src/` and `pyproject.toml`, as well as the existing sources. Shared-library edits cannot bypass frozen-source checks. Existing run records, frozen plans, target keys and convergence policies are unchanged.

A source snapshot from before this refactor is retained locally at `build/shared-core-refactor-20261030/before/`, with digests in `baseline.json`. This is a source recovery snapshot, not a standalone backup of assets, native dependencies or the environment. A historical frozen batch must use the source version matching its receipt; the refactored checkout intentionally rejects a mismatch. Do not refresh an old receipt's hashes to make the new code appear identical. For recovery, restore the listed pre-refactor sources into a separate suitable checkout/environment and verify the original receipt before resuming.

The refactor is validated through existing numerical oracles and byte-preservation checks, legacy import compatibility, real tiny PFM/EXR reader fixtures, full-control/RNG guards, input preservation and CLI checks. Reusable fixture data is centralized under `tests/fixtures/`. Tests are grouped by responsibility and use qualified `tests.*` IDs; the structure migration retains an old/new mapping and checks every historical test and dependency group.

## Flattened layout

The shared library now exposes `metrics`, `image_io`, `records`, `analysis` and `backends` directly under `src/`. The distribution is still named `restir-lab`; `restir_lab` is no longer an import namespace. Reinstall an existing editable environment after this layout change: `python -m pip install -e ".[exr]"`. `image_io` avoids Python's standard-library `io` name. Historical `experiment.*` script APIs remain compatibility exports.

Tests live in `tests/core`, `tests/backends`, `tests/workflows` and `tests/assets`, with common fixtures in `tests/fixtures`. Use `python -B scripts/check_tests.py --suite all` or `python -B -m unittest discover -s tests -t . -v`. The explicit top-level directory keeps test modules under `tests.*`, so test folders cannot shadow production packages. The structure-migration snapshot and test ID mapping are retained locally under `build/structure-flattening-20261030/`; historical run records and frozen receipts are not rewritten.
