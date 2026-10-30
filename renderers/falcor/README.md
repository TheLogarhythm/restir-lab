# Falcor 9.0 integration

Official [Falcor 9.0](https://github.com/NVIDIAGameWorks/Falcor/releases/tag/9.0), pinned to `759aad033ff610fb0d82c74f7e0a508d0096d5f2` in the `upstream/` Git submodule. The integration adds Python/PowerShell adapters; upstream C++ and Slang sources remain unmodified.

## Build

From the repository root, with Git, host Python 3.11, VS2022 C++ tools, Windows SDK 10.0.22621.0 and at least 15 GiB free. The checkout path must have **no spaces** because the pinned upstream bootstrap scripts contain unquoted internal paths; preflight rejects such paths before initialization or downloads. Run output paths may contain spaces.


```powershell
./scripts/falcor/setup.ps1 -Jobs 4
./scripts/falcor/setup.ps1 -CheckOnly
```

The adapter initializes an absent/empty source checkout only; an existing checkout must already match the pin. It initializes the pinned upstream dependencies (shallow where possible), runs upstream `setup.bat`, and builds `Mogwai` and the required `falcor-copy-files` deployment target in Release. Git uses certificate-verified OpenSSL for this machine's TLS compatibility. A conflicting revision, modified tracked source or conflicting user preset causes an error and is preserved.

The ignored `CMakeUserPresets.json` inherits `windows-vs2022`, selects host=x64 and installed SDK 10.0.22621.0 instead of upstream's 10.0.19041.0. `FALCOR_USE_SYSTEM_PYTHON=OFF`. Packman pins Python 3.10.11+nv1, CMake 3.24.1+nv3 and Slang 2025.13.2. No global Python/SDK/driver changes are required. GitHub archive connectivity failed locally, so DLSS v310.1.0 (`01e4efdc`) and NVAPI (`3d34a4fa`) are fetched from their official Git repositories at the same upstream revisions into `build/falcor/deps/`. Standard `FETCHCONTENT_SOURCE_DIR_*` arguments select these independent copies; revision/cleanliness checks apply to them too.

| Location | Content |
| --- | --- |
| `renderers/falcor/integration.json` | Upstream pin and build choices |
| `renderers/falcor/upstream/` | Full upstream layout, licenses and nested submodules |
| `renderers/falcor/upstream/build/lab-vs2022/` | Independent CMake build |
| `build/falcor/packman-cache/` | Local Packman cache |
| `build/falcor/build.json` | Source/dependency/binary/shader fingerprints |
| `build/falcor/*-*.log` | Dependency, configure and compile logs |
| `scripts/falcor/` | Build, graph and bounded run adapters |
| `runs/falcor/<new-name>/` | Per-run captures and provenance |

Build outputs, dependencies and run artifacts are ignored. The first bootstrap downloads sizable upstream dependency bundles; preserve failed logs and rerun after addressing the error. New DLSS/NVAPI downloads use temporary checkouts and are published only after revision checks, so an interrupted download can be retried. Existing nonempty checkouts remain untouched on a pin mismatch. Build verification also rejects uninitialized or mismatched nested submodules.

## Bounded validation

Create the separate host-side EXR verifier once:

```powershell
python -m venv build/falcor/verify-env
./build/falcor/verify-env/Scripts/python.exe -m pip install -r scripts/falcor/requirements.txt
./build/falcor/verify-env/Scripts/python.exe -B -m unittest discover -s tests -t . -p "test_falcor*.py" -v
./build/falcor/verify-env/Scripts/python.exe -B scripts/falcor/run.py --mode path-tracer --output runs/falcor/pt-smoke
./build/falcor/verify-env/Scripts/python.exe -B scripts/falcor/run.py --mode restir-pt --output runs/falcor/restir-pt-smoke
```

Use a **new output name** for every run. Add `--interactive` for a visible, still finite Mogwai check. It holds the last presented frame for 30 seconds after rendering, then exits automatically; UI startup/display is inspected separately and this pause does not verify interactive controls. Build and run preflight refuse to proceed while another FullSample or Mogwai process is active.


Build and run adapters also share an OS-owned `build/falcor/.operation.lock`, acquired before preflight and held through completion. Concurrent adapter operations in this checkout fail immediately, including a second launch before the first Mogwai process exists. The lock releases when its owner exits; the empty lock file stays in place and does not need deleting. The process probe also catches a surviving renderer after its launcher was killed. Renderers started outside these adapters are covered by a point-in-time process check, not by the checkout lock.

The default profile is 320 × 180, one sample per pixel per frame, 16 frames, captures at frames 1/16, and a 600-second process timeout. The two modes use native PathTracer with `useReSTIRPT` false/true in separate processes. VBufferRT uses pixel centers; the path tracer advances its native per-frame RNG instead of fixing a constant seed. Raw graphs have no accumulation, denoiser, upscaler or tone mapper.

The Cornell Box wrapper reads the existing RTXDI asset and hashes its referenced resources. Camera: position (0,5,-15), target (0,5,0), up (0,1,0), vertical FOV 60°, pinhole. Requested config, generated script, resolved graph/camera, command, GPU/driver, logs and hashes survive each run. New runs preserve a byte-for-byte `build.json` snapshot and execute their own `graphs.py` snapshot, retaining build provenance after a later rebuild. Timeout cleanup targets only the owned process tree, uses bounded waits, and preserves the original failure. If Windows tree termination fails, it attempts to stop the owned process directly and records `cleanup_error`; in that case descendant cleanup is not guaranteed.

Raw EXR must decode to finite, nonblack FLOAT32 RGB at the requested size. Separate PNG previews use EV0, Reinhard and sRGB; this display transform does not alter HDR. Reported wall time includes startup, shader compilation and export; GPU time is not measured.

## Scope and isolation

This establishes the official research environment, not a paper reproduction or a quantitative comparison. Falcor's material/light interpretation is not assumed equal to RTXDI's. No reference generation or parameter sweep is included.

The existing RTXDI binaries, runners, scenes and experiment state are independent. Falcor scripts live outside the frozen campaign's source globs; scene config is `.pyscene`, with the run profile under `experiments/configs/`. Falcor's own bundled RTXDI 1.3.0 dependency is separate from the lab's RTXDI 3.1.0.

See [the design](../../docs/superpowers/specs/2026-10-28-falcor-integration-design.md).

## Verification on 2026-10-28

**Completed:** VS2022 x64 Release build, complete runtime deployment, native D3D12 PathTracer and ReSTIR PT smoke captures, and visible Mogwai startup. Device: RTX 4060 Laptop, driver 560.94, D3D12 SM6.8. Upstream tracked sources remain clean. `setup.ps1 -CheckOnly`, 18 CPU adapter tests and the scaffold check pass.

| Run directory under `runs/falcor/` | Result | Wall seconds |
| --- | --- | --- |
| `20261028-path-tracer-final` | 16 frames; FLOAT32 RGB EXR at frames 1/16 | 21.110 |
| `20261028-restir-pt-final` | 16 frames; FLOAT32 RGB EXR at frames 1/16 | 62.906 |
| `20261028-mogwai-ui` | Visible window/menu/FPS observed; 16 frames and automatic exit | 45.078 |

All six EXRs decode as 320 × 180 finite, nonblack FLOAT32 RGB. Previews were inspected. UI-run HDR hashes match the corresponding headless PathTracer captures. The visible check includes a 30-second final-frame display hold; Windows may label the sleeping window unresponsive. Interactive controls were not tested. These wall times include startup/shader compilation/export and are not a performance comparison. Falcor's default internal `colorFormat=LogLuvHDR` remains in the resolved graph; FLOAT32 describes the exported channels, not every intermediate calculation.

RTXDI isolation: all 490 baseline frozen-source/binary fingerprints remain unchanged, and no new file entered the frozen source set. The existing static batch was already failed before integration; it was not restarted or repaired.

The user explicitly approved enabling Windows Developer Mode for this installation. Only `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\AppModelUnlock\AllowDevelopmentWithoutDevLicense=1` was set. Device Portal/discovery and the driver were not changed. Microsoft documents the [experimental D3D12 feature requirement](https://learn.microsoft.com/en-us/windows/win32/api/d3d12/nf-d3d12-d3d12enableexperimentalfeatures) and [Developer Mode settings](https://learn.microsoft.com/en-us/windows/advanced-settings/developer-mode).

Integration fixes retain upstream sources: build `falcor-copy-files` because `Mogwai` alone omits Agility/DXC/NVAPI deployment; export the graph with `g.print()` because upstream `m.saveConfig()` dereferences a missing window in headless mode; serialize native vectors via x/y/z. The stale top-level `usePairedNeighbors` example option is omitted; the resolved nested ReSTIR options retain the native default. Upstream Slang inheritance warnings remain, with successful rendering verified.

Local evidence: `build/falcor/build.json`, `build/falcor/verification.json`, `build/falcor/progress.md`, `build/falcor/developer-mode-change.json`, and `build/falcor/mogwai-ui-startup.jpg`. Latest build logs start with `20261028T114453Z`. Failed startup attempts remain in their own run directories. Generated records are ignored by Git.

## Correctness review on 2026-10-30

Fixed bounded process cleanup, interrupted dependency downloads, nested-submodule verification, relative executable paths, and retention of per-run build/graph snapshots. CPU CI now installs the EXR verifier dependencies, and the license link works without fetching the upstream submodule. Shared process cleanup replaces duplicated logic; the adapters and tests use consistent Python formatting.

Historical full-workspace validation (including then-uncommitted experiment work): all 597 tests passed, including 23 Falcor tests; incremental Release build and `-CheckOnly` passed. Both original 320 × 180, 16-frame smoke profiles completed in `runs/falcor/20261030-review-path-tracer/` and `runs/falcor/20261030-review-restir-pt/`. All four HDR hashes match the corresponding 2026-10-28 captures. The 490 RTXDI baseline fingerprints remain unchanged. This review did not repeat the interactive UI check or execute remote GitHub Actions.

Review evidence, the previous build manifest, and pre-edit file backups are under `build/falcor/review-20261030/`. Build logs start with `20261030T025300Z`; the current build manifest reflects the reviewed adapters. Earlier run records and captures remain intact.

### Follow-up concurrency review on 2026-10-30

Fixed two related correctness issues: overlapping launchers could both pass the process check before either spawned Mogwai, and a build could modify runtime files while a manually started or surviving Mogwai was active. Build/run entry points now share a lock across preflight and execution, and use one renderer-idle check. No upstream rendering code or graph parameters changed.

Four new regressions cover concurrent launch refusal, build refusal during launch preflight, lock release after forced launcher exit, and rejection of a surviving renderer before build mutations. The cross-process fixtures use CPU stand-ins; the surviving-renderer unit test supplies the Windows process-query result.

Historical full-workspace validation (including then-uncommitted experiment work): 584 portable tests passed, including all 27 Falcor tests. The incremental Release build, `-CheckOnly`, formatting and scaffold checks passed. New 320 × 180, 16-frame runs are `runs/falcor/20261030-concurrency-path-tracer/` and `runs/falcor/20261030-concurrency-restir-pt/`; all four HDR hashes match the preceding review's captures. All 494 RTXDI files fingerprinted at the start of this review remain unchanged. Evidence is under `build/falcor/review-concurrency-20261030/`; final build logs start with `20261030T031927Z`.

Validation was local on Windows. The POSIX lock path and remote CI were not executed, and the interactive UI check was not repeated. An attempted live-renderer contention probe arrived after the bounded run had exited; concurrency verification therefore relies on the separate-process regressions, not that probe. The initial broad test attempt used a host Python without OpenEXR; the passing run used the existing isolated verifier environment.

## Shared offline analysis

Saved smoke outputs can now be read through the common `records`/`analysis` interface and `scripts/analyze_run.py`; see [shared analysis](../../docs/shared-analysis.md). The native smoke validation still requires nonblack FLOAT32 EXR. The shared decoder permits valid black HDR for general analysis. Historical smoke repeats lack independent RNG/history metadata and remain ineligible for independent-repeat covariance.
