# ReSTIR literature review

**Updated: 2026-09-18.** An overview of ReSTIR foundations, research directions, and implementations to guide reading and experiments with RTXDI and Falcor.

The [reading matrix](reading-matrix.csv) lists full titles, venues, primary sources, and code links for 31 papers and two supporting resources. `source_checked` indicates that metadata and contributions were checked against primary sources.

## 1. Foundations: what is reused, and with which weights?

ReSTIR combines importance resampling with reuse across space and time. A reservoir compresses candidate samples, but its weights and normalization must account for how those candidates were generated and reused. Moving from lights to paths introduces domain mappings and their associated density changes. The [GRIS framework](https://research.nvidia.com/labs/rtr/publication/lin2022generalized/) is therefore essential for understanding correctness beyond the original direct-lighting algorithm.

| Work | Publication | Main contribution |
| --- | --- | --- |
| [RIS](https://diglib.eg.org/items/7b8d7c38-ee96-4415-acdd-3dd164fa8fad) | 2005, EGSR | Introduces importance resampling for light transport; the foundation for reservoir-based reuse. |
| [ReSTIR DI](https://research.nvidia.com/labs/rtr/publication/bitterli2020spatiotemporal/) | 2020, TOG / SIGGRAPH | Reuses light candidates across pixels and frames; visibility and reuse weights determine correctness. |
| [Production ReSTIR](https://research.nvidia.com/labs/rtr/publication/wyman2021rearchitecting/) | 2021, HPG | Reorganizes sampling and shading for practical GPU costs and production integration. |
| [ReSTIR GI](https://research.nvidia.com/publication/2021-06_restir-gi-path-resampling-real-time-path-tracing) | 2021, CGF / HPG | Extends reuse to multi-bounce indirect transport; distinguish its sampling domain from full path resampling. |
| [GRIS / ReSTIR PT](https://research.nvidia.com/labs/rtr/publication/lin2022generalized/) | 2022, TOG / SIGGRAPH | Formalizes generalized reuse and shift mappings; introduces the ReSTIR PT application. |
| [Conditional RIS / Suffix ReSTIR](https://research.nvidia.com/labs/rtr/publication/kettunen2023conditional/) | 2023, SIGGRAPH Asia Conference | Derives conditional resampling for reusing subpaths rather than always resampling complete paths. |

**Reading order:** RIS and DI, production ReSTIR and GI, then GRIS/PT and conditional RIS. The [SIGGRAPH 2023 course](https://intro-to-restir.cwyman.org/) is a useful companion. [ReGIR](https://research.nvidia.com/labs/rtr/publication/boksansky2021rendering/) is a related 2021 book chapter on world-space light proposals, useful when studying candidate generation.

## 2. Reuse quality: selection, correlation, and error distribution

These methods improve different parts of the estimator. Better neighbor selection finds useful candidates; weighting controls their contribution; mutations and stratification change statistical dependence and visible noise. Compare their effects under matched rendering settings and time budgets.

| Work | Publication | Main contribution |
| --- | --- | --- |
| [PDF similarity](https://doi.org/10.1145/3585501) | 2023, PACMCGIT / I3D | Uses distribution similarity to avoid ineffective spatial reuse. |
| [MCMC mutations](https://research.nvidia.com/labs/rtr/publication/sawhney2024decorrelating/) | 2024, TOG | Mutates reused samples to reduce correlation artifacts. |
| [Novel MIS weight](https://doi.org/10.1111/cgf.15049) | 2024, CGF / Eurographics | Changes weighting and visibility handling to address energy loss and noise in biased direct-lighting reuse. |
| [Histogram stratification](https://iribis.github.io/publication/2025_Stratified_Histogram_Resampling) | 2025, SIGGRAPH Conference | Preserves useful stratification through resampling; connects quasi-Monte Carlo, antithetic sampling, and noise shaping. |
| [Stochastic pairwise MIS](https://research.nvidia.com/labs/rtr/publication/hedstrom2026stochastic/) | 2026, CGF / Eurographics | Makes large spatial neighborhoods affordable while favoring contributing candidates. |
| [Compatibility-guided neighbors](https://research.nvidia.com/labs/rtr/publication/junkins2026compatibility/) | 2026, PACMCGIT / HPG | Uses weighted stochastic neighbor selection based on geometric compatibility. |
| [Blue-noise dithering](https://doi.org/10.1109/TVCG.2026.3708022) | 2026, IEEE TVCG (online July 1) | Shapes resampling error toward perceptually favorable high frequencies. |
| [PT Enhanced](https://research.nvidia.com/labs/rtr/publication/lin2026restirptenhanced/) | 2026, PACMCGIT / I3D | Combines improved reconnection, neighbor selection, and sample-duplication handling. |

**Synthesis:** low per-frame error does not guarantee stable animation or favorable noise structure. Evaluate temporal artifacts and sample diversity alongside image error and total runtime. Histogram stratification and blue-noise dithering are important additions to a survey focused only on variance reduction.

## 3. Camera integration and changing visibility

A reservoir history is only useful when samples can be transported to the current integration domain. Lens changes, motion, disocclusion, and changing geometry expose different failures of that transport.

| Work | Publication | Main contribution |
| --- | --- | --- |
| [Area ReSTIR](https://research.nvidia.com/labs/rtr/publication/zhang2024area/) | 2024, TOG / SIGGRAPH | Extends reuse across film and lens dimensions for antialiasing and depth of field. |
| [Reservoir splatting](https://research.nvidia.com/labs/rtr/publication/liu2025splatting/) | 2025, SIGGRAPH Conference | Projects samples forward through space and time, complementing backward temporal reuse. |
| [Multi-layer splatting](https://research.nvidia.com/labs/rtr/publication/hong2026multilayer/) | 2026, SIGGRAPH Conference | Retains occluded history in multiple layers for later disocclusion. |
| [ReSTIR LoD](https://research.nvidia.com/labs/rtr/publication/wang2026levelofdetail/) | 2026, SIGGRAPH Conference | Maps reusable surface points across geometry level changes. |

Multi-layer history recovers previously observed samples after disocclusion. Reservoir splatting transports reservoir samples across frames.

## 4. Difficult transport and candidate generation

Reuse cannot recover an important path that candidate generation almost never finds. Photon methods, bidirectional construction, manifold sampling, and guiding address this complementary problem.

| Work | Publication | Main contribution |
| --- | --- | --- |
| [Volumetric ReSTIR](https://research.nvidia.com/publication/2021-11_fast-volume-rendering-spatiotemporal-reservoir-resampling) | 2021, TOG / SIGGRAPH Asia | Adapts candidate generation and resampling to participating media. |
| [ReSTIR FG](https://doi.org/10.2312/sr.20241155) | 2024, EGSR Symposium Track | Combines photon final gathering and reservoir reuse to render caustic transport. |
| [ReSTIR SSS](https://cg.ivd.kit.edu/english/restir-sss.php) | 2024, PACMCGIT / HPG | Designs shift mappings for subsurface transport. |
| [ReSTIR BDPT](https://research.nvidia.com/labs/rtr/publication/hedstrom2025restir/) | 2025, TOG | Reuses bidirectional paths to reach caustic paths poorly sampled from the camera. |
| [Partitioned manifold sampling](https://research.nvidia.com/labs/rtr/publication/hong2025partition/) | 2025, SIGGRAPH Asia Conference | Combines specular manifold sampling with partitioning and temporal/spatial reuse. |
| [ReSTIR PG](https://research.nvidia.com/labs/rtr/publication/zeng2025restirpg/) | 2025, SIGGRAPH Asia Conference | Uses resampled paths to learn directional proposals for subsequent path generation. |
| [Guided ReSTIR FG+](https://doi.org/10.2312/sr.20261001) | 2026, EGSR Symposium Track | Guides photon emission toward camera-relevant regions and improves final-gather reuse. |

**Synthesis:** caustic quality depends on both discovering paths and successfully reusing them. Guided FG+ extends the FG line to large scenes and many lights, while ReSTIR PG improves future proposals using previously resampled paths. A comparison should separate proposal changes from reuse changes.

## 5. Alternative estimators and rendering targets

These works extend reservoir estimation to image gradients, parameter derivatives, shadow-map allocation, and transient transport.

| Work | Publication | Main contribution |
| --- | --- | --- |
| [Gradient-domain ReSTIR](https://research.nvidia.com/labs/rtr/publication/wang2026gradient/) | 2026, CGF / Eurographics | Estimates image gradients alongside pixel values, then reconstructs the image. |
| [ReSTCV](https://hercier.github.io/restcv/) | 2026, SIGGRAPH Conference | Uses correlated contributions as control variates to reduce residual rendering variance. |
| [Parameter-space ReSTIR](https://weschang.com/publications/restir-dr/) | 2023, SIGGRAPH Conference | Resamples for parameter derivatives, including signed integrands, during optimization. |
| [Inverse-rendering reuse](https://research.nvidia.com/labs/rtr/publication/wang2023amortizing/) | 2023, TOG / SIGGRAPH Asia | Reuses differential transport samples across inverse-rendering iterations. |
| [ReSTIR shadow maps](https://research.nvidia.com/labs/rtr/publication/zhang2025many-light/) | 2025, CGF / Eurographics | Uses resampling to allocate shadow-map effort among many lights. |
| [ToF ReSTIR](https://arxiv.org/abs/2605.11536) | 2026, TOG / SIGGRAPH | Introduces path-length-aware shifts for time-gated and transient light transport. |

Gradient-domain rendering estimates differences between image pixels; differentiable rendering estimates derivatives with respect to scene parameters. They are distinct tasks. ToF further constrains optical path length, so a spatially nearby path need not be a useful reusable sample.

## Implementation notes

- **Paper names:** ReSTIR PT is introduced in GRIS; Suffix ReSTIR belongs to conditional RIS.
- **Neighbor selection:** [compatibility-guided selection](https://research.nvidia.com/labs/rtr/publication/junkins2026compatibility/) is weighted stochastic selection, not deterministic selection of the best M neighbors.
- **Estimator guarantees:** the [original DI paper](https://research.nvidia.com/labs/rtr/publication/bitterli2020spatiotemporal/) includes biased and unbiased variants. GRIS guarantees require its assumptions; they do not imply every practical ReSTIR implementation is unbiased.
- **RTXDI versions:** RTXDI combines methods from multiple papers. Its [PT documentation](https://github.com/NVIDIA-RTX/RTXDI/blob/main/Doc/RestirPT.md) includes components from PT Enhanced and compatibility-guided selection. Pin a commit and identify the components enabled in each experiment.
- **Author releases:** the public [Area ReSTIR repository](https://github.com/guiqi134/Area-ReSTIR) covers direct lighting. Author implementations use different Falcor versions; check their dependencies and supported features before planning a port.

## Implications for this project

The current [course scope](../scope.md) focuses on ReSTIR DI, PDF Similarity, and compatibility-guided neighbor selection on one backend. GRIS/PT remains a later extension. Use the following questions to guide further reading.

Three reading questions:

| Reading question | Related work |
| --- | --- |
| How do motion and disocclusion affect neighbor selection? | PDF similarity, stochastic pairwise MIS, compatibility-guided selection |
| How does noise structure affect spatial and temporal quality? | MCMC mutations, histogram stratification, blue-noise dithering |
| How do candidate generation and reuse each affect caustic rendering? | FG/FG+, BDPT, manifold sampling, PG |

Keep detailed derivations and paper-specific limitations in [individual notes](notes/README.md), and update this overview only when they change the research map or project choices.
