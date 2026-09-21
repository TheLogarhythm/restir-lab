# Pitch sources

## Illustrations

| File | Source and attribution | Use / changes |
| --- | --- | --- |
| `assets/bistro-exterior.png` | Amazon Lumberyard, *Bistro*, Open Research Content Archive (2017). [Source page](https://developer.nvidia.com/orca/amazon-lumberyard-bistro), [original image](https://d29g4g2dyqv443.cloudfront.net/sites/default/files/akamai/Bistro_Exterior_1.png). CC BY 4.0. | Slide 5 scene illustration; original image bytes, cropped by slide layout. Not a project render. |
| `assets/cgns-comparison.png` | Orion Junkins, Markus Kettunen, Daqi Lin, Ravi Ramamoorthi, and Chris Wyman. *Compatibility-Guided Neighbor Selection for ReSTIR* (2026), Fig. 1. [Paper](https://research.nvidia.com/labs/rtr/publication/junkins2026compatibility/junkins2026compatibility.pdf), [DOI](https://doi.org/10.1145/3820024). Copyright the authors, CC BY 4.0. | PDF page 1 rendered to PNG; margins and caption removed, all comparison labels and measurements retained. The label “Ours” denotes the authors' method. |
| `assets/cgns-temporal.png` | Same authors and paper, Fig. 5 (Veach Ajar). Copyright the authors, CC BY 4.0. | PDF page 11 rendered to PNG; margins and caption removed, all figure panels and measurements retained. Retained source asset; not used in the revised deck. |
| `assets/cornell-box.png` | Cornell Box from [RTXDI Assets](https://github.com/NVIDIA-RTX/RTXDI-Assets/tree/1da7b749ef0e3fb606ab46dde8e5bfbacd078a02/CornellBox), root MIT license, NVIDIA GameWorks. | Local official RTXDI scene preview for slide 5; capture settings below. |
| `assets/arcade.png` | Arcade from [RTXDI Assets](https://github.com/NVIDIA-RTX/RTXDI-Assets/tree/1da7b749ef0e3fb606ab46dde8e5bfbacd078a02/Arcade), root MIT license, NVIDIA GameWorks. | Local official RTXDI scene preview for slide 5; capture settings below. |

The Cornell Box and Arcade previews use unmodified RTXDI `v3.1.0` (`a6efab966b7c3b272da0461578eb56ac61c7cbff`), assets `1da7b749ef0e3fb606ab46dde8e5bfbacd078a02`, and each scene's default camera. Settings: 1280 × 720, DI `UNBIASED` preset with temporal/spatial reuse, indirect lighting off, denoising off, accumulation AA, animation off, capture frame 240, tone mapping and default bloom on. BMP captures were converted to PNG without changing pixels. Local exact commands and logs are in `build/slides/scene-previews/<scene>/`; the previews illustrate scene content, not algorithm quality or matched-time performance. Their colors/settings should not be compared with the external Bistro image.

The two previews retain the [RTXDI Assets MIT notice](assets/RTXDI-ASSETS-LICENSE.txt).

External-figure license: [Creative Commons Attribution 4.0](https://creativecommons.org/licenses/by/4.0/). Attribution does not imply endorsement. The CGNS paper identifies this license on its first page; the Bistro source page lists the same license. Retrieved 2026-09-19. Full downloaded papers and intermediate renders remain in ignored `build/pitch-sources/`.

## Research and project content

- Bitterli et al. (2020), [Spatiotemporal Reservoir Resampling for Real-time Ray Tracing with Dynamic Direct Lighting](https://doi.org/10.1145/3386569.3392481).
- Tokuyoshi (2023), [Efficient Spatial Resampling Using the PDF Similarity](https://doi.org/10.1145/3585501).
- Junkins et al. (2026), [Compatibility-Guided Neighbor Selection for ReSTIR](https://doi.org/10.1145/3820024).
- [RTXDI](https://github.com/NVIDIA-RTX/RTXDI), [CGNS author implementation](https://github.com/orion-junkins/ReSTIR-CGNS), and [RTXDI Assets](https://github.com/NVIDIA-RTX/RTXDI-Assets).
- Project [proposal](../proposal/main.tex), [scope](../../../docs/scope.md), [roadmap](../../../docs/roadmap.md), and [experiment protocol](../../../experiments/protocol.md).

The deck text, layout, notes, and build script were drafted with Codex assistance. Figures comprise attributed published illustrations and locally captured official-renderer scene previews. Per-slide source details are also in the speaker notes; no novel algorithm or measured project result is claimed.
