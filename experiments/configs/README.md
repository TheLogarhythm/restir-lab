# Configurations

These are the configurations used by the retained experiment workflows:

- [di-reuse.json](di-reuse.json) defines the RTXDI DI reuse baseline.
- [di-comparison-static.json](di-comparison-static.json) and [cgns-di-gi-pt-static.json](cgns-di-gi-pt-static.json) define the comparison workflows.
- [pdf-controlled.json](pdf-controlled.json) is the declared matrix for the controlled PDF campaign, including view overrides, schedules, ROIs and execution order. The runner resolves scene defaults and freezes effective conditions in each suite. Changes remain subject to [experiment protocol](../protocol.md) approvals.
- [falcor-sanity-check.json](falcor-sanity-check.json) configures the Falcor integration smoke test.
- [Falcor ReSTIR PT spatial comparison](falcor-pt-spatial-comparison/README.md) defines the shared settings for ordinary spatial reuse and CGNS. Its six [camera presets](../views/falcor-pt-spatial-comparison/) select reusable [scene profiles and inventories](../scenes/falcor-pt-spatial-comparison/). See the [preparation guide](falcor-pt-spatial-comparison/PREPARATION.md) for the two Bistro variants and four other scenes.

Superseded Falcor scout and diagnostic configurations are preserved as historical records under `runs/falcor-pt-spatial-comparison/provenance/archived-configs/`. The old Bistro FBX composition and glass-bypass scene wrappers and their three dedicated launchers have been retired; the archived paths describe the historical runs and are not current runnable entry points.
