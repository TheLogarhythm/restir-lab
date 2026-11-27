# Falcor ReSTIR PT methods

Falcor 9.0 supplies path generation, shift mappings, visibility and reservoir merging. The two spatial-reuse extensions are project adaptations. The live demo switches methods in one window. The fixed-view benchmark uses separate, verified runtimes with matched rendering settings. [Falcor integration](../../renderers/falcor/README.md) · [Setup](../setup.md#falcor-and-live-demo) · [Six-view benchmark](pt-6-views-spatial-compare.md)

## PDF Similarity

Every valid initial RIS candidate contributes its positive scalar RIS weight and its first outgoing direction, including candidates that lose reservoir selection. A primary next-event connection contributes its light direction. A deeper contribution uses the first BSDF scatter. Weighted direction moments fit a von Mises–Fisher lobe for each pixel. The first-hop summary discards multiple peaks and later path segments.

Validated reprojection carries these moments with decay `0.95` and effective evidence capped at `20`. For receiving and donor evidence `e_i` and `e_j`, confidence is `c = clamp((min(e_i, e_j) - 1) / 19, 0, 1)`. With lobe similarity `S`, use `M_eff = ((1 - c) + c * S) * M_neighbor`. The merge, forward and reverse MIS, and output reservoir count all use the same effective count. A neighbor with insufficient evidence receives ordinary weighting. Continuous camera motion can retain valid reprojected history. A full reset requires fresh lighting reservoirs as well as cleared directional history. [History shader](../../scripts/falcor/pdf_pt_history.slang) · [MIS integration](../../scripts/falcor/pdf_pt_mis.py) · [Tokuyoshi 2023](https://doi.org/10.1145/3585501)

## CGNS

For two surface positions separated by distance `r`, shading normals `n_i` and `n_j`, and receiving camera distance `d`, compatibility is `exp(-r / (d * sqrt(0.05 / pi))) * max(dot(n_i, n_j), 0)^8`. The benchmark considers up to 32 disk proposals within 30 pixels. A-Chao retains one valid donor, with early stopping after the first score reaches `0.5`. The selected donor still passes Falcor's geometry and path-shift checks. CGNS adds geometry work while keeping one downstream path neighbor.

The cached selector stores one ID per pixel and spatial round for workload generation, retracing and merging. Two RGBA32F textures and one R32Uint texture add 36 bytes per pixel, about 71.2 MiB at 1080p. These allocations describe the cache itself. The benchmark's point reservoirs differ from the area-reservoir and splatting settings in the authors' Fast configuration. [Selector](../../scripts/falcor/cgns_single_selector.slang) · [Cache dispatch](../../scripts/falcor/cgns_cached_dispatch.inl) · [Junkins et al. 2026](https://doi.org/10.1145/3820024)

## Qualified settings

The fixed-view comparison uses 1 spp, point reservoirs, one unpaired neighbor, one spatial round, radius 30 and compact retracing. PDF uses directional history with temporal reuse enabled. Use the normal PDF profile with NRD because diagnostic profiles repurpose its channels. Historical GPU controls checked that forced PDF multipliers of one and zero recover ordinary and center-only behavior, and compared cached CGNS donor IDs against the uncached selector. The checks establish implementation behavior under those controls. [Fixed-view config](../../experiments/configs/falcor-pt-spatial-comparison/restir-pt-spatial-comparison.json) · [Regression tests](../../tests/README.md)
