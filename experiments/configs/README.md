# Experiment configurations

| Workflow | Configuration |
| --- | --- |
| RTXDI DI baseline | [di-reuse.json](di-reuse.json) |
| RTXDI static comparison | [DI example](di-comparison-static.json) · [DI/GI/PT with CGNS](cgns-di-gi-pt-static.json) |
| RTXDI controlled PDF Similarity | [pdf-controlled.json](pdf-controlled.json) |
| Falcor smoke run | [falcor-sanity-check.json](falcor-sanity-check.json) |
| Falcor six-view PT benchmark | [Suite and schedule](pt-6-views-spatial-compare.json) · [Shared method settings](falcor-pt-spatial-comparison/restir-pt-spatial-comparison.json) |

The Falcor suite selects separate camera presets, scene profiles and resource inventories. Its active scene lock binds these inputs to the reference catalog. Use the preparation guide for the exact asset and runtime requirements. [Cameras](../views/falcor-pt-spatial-comparison/) · [Profiles and inventories](../scenes/falcor-pt-spatial-comparison/) · [Scene lock](falcor-pt-spatial-comparison/scene-inputs-v2.json) · [Preparation](falcor-pt-spatial-comparison/PREPARATION.md) · [Reference catalog](../references/README.md)

See [experiment suites](../suites/README.md) for commands and comparison settings.
