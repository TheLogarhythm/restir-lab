# Falcor 9.0 Integration Design

Status: the user approved the phase-one scope and selected official Falcor 9.0 on 2026-10-28. The layout and implementation details below are recommendations for that scope. This document does not claim installation or validation has happened.

## Goal and boundary

Add a separately buildable and runnable Falcor research backend to restir-lab. Phase one finishes when Mogwai, the conventional PathTracer and the upstream ReSTIR PT implementation can render a small scene and export inspectable linear HDR with provenance.

The existing RTXDI DI/PDF/CGNS work remains its own experiment line. Phase one does not port the team's algorithms to Falcor, change the existing RTXDI campaign's execution state, run a quality campaign, claim cross-renderer equivalence, or establish a converged reference.

## Approaches

1. Official Falcor 9.0, pinned to a commit: chosen by the user for future extensions. It includes ReSTIR PT Enhanced and Area ReSTIR support and example graphs.
2. A paper-specific author fork, such as CGNS on Falcor 8.0: useful for a later reproduction, but separately pinned and built. It is not a plugin assumed compatible with 9.0.

## Versions and build environment

- Upstream: https://github.com/NVIDIAGameWorks/Falcor.git
- Tag: `9.0`.
- Commit: `759aad033ff610fb0d82c74f7e0a508d0096d5f2`, resolved through GitHub's tag-ref API.
- Windows x64, Visual Studio 2022, D3D12 runtime, Release.
- Use upstream Packman and its versioned dependency manifest: CMake `3.24.1+nv3`, Python `3.10.11+nv1`, Slang `2025.13.2`. Record resolved dependencies and hashes.
- The official Windows preset requests SDK `10.0.19041.0`; this machine has `10.0.22621.0` and `10.0.26100.0`. Propose a generated, Git-ignored CMakeUserPresets.json overriding the SDK to `10.0.22621.0` and using the x64 compiler host. Build validation must confirm compatibility.
- Leave `FALCOR_USE_SYSTEM_PYTHON=OFF`. The repository's Python 3.11 launcher starts Mogwai as a subprocess; Falcor executes graph scripts in its own embedded interpreter.
- Do not replace Falcor's packaged RTXDI/NRD/DLSS with files from the existing RTXDI checkout. CUDA/OptiX integration is optional upstream and not an installation goal.
- Initial build parallelism is 4. Record installed driver and hardware; existing advertised prerequisites do not prove successful compilation or rendering.

## Proposed files

| Path | Role |
| --- | --- |
| `renderers/falcor/README.md` | Local entry point: version, build/run instructions, verified status |
| `renderers/falcor/integration.json` | Small tracked pin and local build choices |
| `renderers/falcor/upstream/` | Official source as a pinned Git submodule; preserve its native layout |
| `renderers/falcor/upstream/build/lab-vs2022/` | Ignored build; binaries under bin/Release |
| `scripts/falcor/setup.ps1` | Bootstrap dependencies, generate local preset, configure/build, record logs |
| `scripts/falcor/run.py` | Host-side launcher, provenance, bounded execution, output verification |
| `scripts/falcor/graphs.py` | Embedded-Python graph construction and output selection |
| `scripts/falcor/requirements.txt` | Isolated HDR-verification dependencies; record resolved package versions |
| `scenes/configs/falcor/cornell-box.pyscene` | Falcor-native import/camera setup for the existing Cornell asset |
| `experiments/configs/falcor-sanity-check.json` | Bounded setup check, not a research comparison |
| `tests/backends/test_falcor_runner.py` | CPU-only launcher/provenance failure checks |
| `build/falcor/` | Ignored setup logs, build manifest and optional verifier environment |
| `runs/falcor/<run-id>/` | Ignored config, command, log, captures, hashes and run manifest |

Update `.gitmodules`, renderer/setup documentation and `THIRD_PARTY.md` during implementation. Preserve the existing Falcor README by putting the official source in the `upstream/` child directory. Do not create a second installation system for paper forks in phase one.

## Minimal adapter

Use the upstream `PathTracer` render pass with `useReSTIRPT` false/true for two modes, based on the shipped example graphs. Add only graph and process integration in Python/PowerShell. No new C++ render pass or Slang algorithm is planned.

Import the existing RTXDI Assets CornellBox glTF with a Falcor-native scene wrapper and explicit camera. Hash the entry asset and referenced buffers/textures. Treat this as an import/setup check; using the same glTF does not establish identical BSDFs, lighting or transport across backends.

The upstream examples enable AccumulatePass and mark only ToneMapper.dst. Our smoke adapter explicitly disables image accumulation for raw method captures, exposes PathTracer.color, and uses a separate fixed-exposure PNG preview. PathTracer.color is RGBA32Float at this pin. Inspect the exported EXR channel types and decoded values; the filename alone does not establish precision.

Proposed bounded check: 320 x 180, one sample/pixel/frame, 16 frames per mode, captures at frames 1 and 16, at most 600 seconds per process including shader compilation. Load a fresh process per mode; disable animation, denoising and upscaling. The cap is for installation validation, not authorization for later experiments. Export requested and resolved graph settings, bounce limits, camera, frame schedule and RNG policy. Do not use a constant fixedSeed as a substitute for an independent temporal sample stream.

Record wall-clock time with its scope. Do not label startup/export time as GPU rendering time. Detailed GPU pass timing, independent-trial scheduling, reference generation and covariance evaluation belong to a subsequent evaluation integration.

## Data and process contracts

Each run directory is new and never overwritten. Save requested config, generated Mogwai script/command, resolved settings, stdout/stderr and a manifest recording running/completed/failed status. Record upstream/submodule commits, relevant source/build/output hashes, asset identity, GPU/driver, software versions and float encoding. Failed runs retain evidence.

Mogwai's supported headless/script/device/resolution CLI is sufficient. Use its frame capture and explicit script-controlled frame loop; exit after the finite schedule. A timeout terminates only this launch's process tree, not unrelated renderers. CPU tests use a stand-in executable and do not import Falcor or require the GPU.

## Protect the existing frozen campaign

The existing static batch fingerprints all Python under `scripts/run/`, top-level Python under `scripts/analysis/`, and JSON under `scenes/configs/`. Adding files there would change its frozen input set.

Use `scripts/falcor/` and a `.pyscene` scene wrapper instead. Compare the frozen source set before/after integration; preserve existing method/reference binary and shader hashes. Do not edit the batch plan to conceal drift. Preserve the batch's current execution state and automation; do not stop or resume it as part of this integration.

Read-only recheck on 2026-10-28: the existing frozen source set still matches its plan, but the latest saved batch state reports `running` in reference generation rather than the earlier `paused` state. This planning inspection did not launch or control it. Reconcile worker/renderer ownership before any Falcor GPU smoke test; saved status alone is not proof of current GPU occupancy.

## Acceptance and deferred work

Acceptance: exact upstream pin, clean tracked upstream sources, successful Release build, Mogwai startup, both modes complete their bounded captures, finite nonblack linear HDR at the requested size, separately labelled previews, correct failure handling, and documented repeatable commands. Run scaffold checks and relevant CPU tests. An interactive Mogwai launch is checked separately from headless completion.

Next stages can add a run loader for the existing pure metric functions, explicit GPU timing, statistically valid independent trials and Falcor-specific references. Existing RTXDI-only provenance loaders are not assumed to accept Falcor outputs. Paper forks and custom algorithm ports remain separately scoped.

## Primary sources inspected

- [Falcor 9.0 release](https://github.com/NVIDIAGameWorks/Falcor/releases/tag/9.0)
- [Pinned dependencies](https://github.com/NVIDIAGameWorks/Falcor/blob/759aad033ff610fb0d82c74f7e0a508d0096d5f2/dependencies.xml)
- [Pinned CMake presets](https://github.com/NVIDIAGameWorks/Falcor/blob/759aad033ff610fb0d82c74f7e0a508d0096d5f2/CMakePresets.json)
- [ReSTIR PT example](https://github.com/NVIDIAGameWorks/Falcor/blob/759aad033ff610fb0d82c74f7e0a508d0096d5f2/scripts/PathTracerReSTIRPT.py)
- [Python interpreter guidance](https://github.com/NVIDIAGameWorks/Falcor/blob/759aad033ff610fb0d82c74f7e0a508d0096d5f2/docs/falcor-in-python.md)
- [Frame capture implementation](https://github.com/NVIDIAGameWorks/Falcor/blob/759aad033ff610fb0d82c74f7e0a508d0096d5f2/Source/Mogwai/Extensions/Capture/FrameCapture.cpp)
- [Image encoding implementation](https://github.com/NVIDIAGameWorks/Falcor/blob/759aad033ff610fb0d82c74f7e0a508d0096d5f2/Source/Falcor/Utils/Image/Bitmap.cpp)
