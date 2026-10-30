# Falcor scene wrapper

`cornell-box.pyscene` imports the existing `renderers/rtxdi/Assets/Media/CornellBox/CornellBox.gltf` without copying or editing it. The bounded runner sets the active camera explicitly and saves its resolved values.

The run profile is `experiments/configs/falcor-sanity-check.json`; no JSON is added under this directory because the existing RTXDI campaign freezes that source glob. Asset and external buffer/texture hashes are recorded per run. Shared geometry does not imply identical transport, BSDF or light interpretation across Falcor and RTXDI.
