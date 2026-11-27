"""Interactive ReSTIR PT demo for the private Falcor runtime.

The launcher runs in the host Python interpreter. Mogwai imports the controller
to drive its native window, scene presets and render graph. Acceptance and shader
precompilation share the checks for captured render state and pixels in evidence.
The native subpackage generates Falcor source overlays. Build and deploy them
with scripts.falcor.live_runtime.
"""
