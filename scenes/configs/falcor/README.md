# Falcor scene wrapper

`cornell-box.pyscene` imports the existing `renderers/rtxdi/Assets/Media/CornellBox/CornellBox.gltf` without copying or editing it. The bounded runner sets the active camera explicitly and saves its resolved values.

The run profile is `experiments/configs/falcor-sanity-check.json`; no JSON is added under this directory because the existing RTXDI campaign freezes that source glob. Asset and external buffer/texture hashes are recorded per run. Shared geometry does not imply identical transport, BSDF or light interpretation across Falcor and RTXDI.

## Spatial-comparison scenes

The current six-view Falcor comparison uses `classroom-reference.pyscene`,
`emerald-square-converted-reference.pyscene`, `veach-ajar-reference.pyscene`,
and `zero-day-measure-seven-reference.pyscene`. The Emerald script was renamed
from `emerald-square-converted-scout.pyscene` without changing its content; the
different ORCA `emerald-square-reference.pyscene` is not used by this comparison.
Historical Emerald script and configuration snapshots are preserved under
`runs/falcor-pt-spatial-comparison/provenance/relocations/`. Classroom also
uses `gallery-lights.py`. The active scene input inventory is `experiments/configs/falcor-pt-spatial-comparison/scene-inputs-v2.json`; it does not require historical runs. Bistro indoor uses the portable adapted glTF scene at
`scenes/configs/falcor/bistro-gltf/`, with the original frozen scene retained
under `runs/` for provenance. Bistro outdoor uses the original prepared ORCA
exterior scene.

The earlier Bistro FBX composition and material-diagnostic scene wrappers have
been retired. Their historical manifests retain the original paths but those
old scene routes cannot be replayed without restoring the removed files. The
present comparison's scenes and assets were not removed.

Reusable scene definitions/inventories live under `experiments/scenes/` and
the six independent cameras under `experiments/views/`. See the
[preparation guide](../../../experiments/configs/falcor-pt-spatial-comparison/PREPARATION.md).
