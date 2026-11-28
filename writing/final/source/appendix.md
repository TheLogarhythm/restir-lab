---
marp: true
math: katex
theme: restir-final
size: 16:9
paginate: true
title: "ReSTIR Spatial Reuse: Evidence Appendix"
author: "Luoyi Zhang and Zelin Gao"
description: "COMP5411 Group 7 | 4:30 rehearsal target | 16 November 2026"
---

## A1 | Full six-view quality results

<p class="lead">SMAPE (%) | Lower is better | Mean ± SD of four seed means</p>
<table style="font-size:24px;width:100%;border-collapse:collapse"><tr><th>View</th><th>Ordinary</th><th>PDF Similarity</th><th>CGNS</th></tr><tr><td>Bistro Interior</td><td>28.044 ± 0.023</td><td>28.042 ± 0.023</td><td>25.302 ± 0.021</td></tr><tr><td>Bistro Exterior</td><td>16.667 ± 0.004</td><td>16.319 ± 0.007</td><td>15.118 ± 0.011</td></tr><tr><td>Classroom</td><td>17.332 ± 0.023</td><td>17.195 ± 0.015</td><td>16.027 ± 0.026</td></tr><tr><td>Emerald Square</td><td>25.550 ± 0.038</td><td>26.988 ± 0.040</td><td>19.738 ± 0.022</td></tr><tr><td>Veach Ajar</td><td>16.751 ± 0.042</td><td>16.778 ± 0.044</td><td>15.894 ± 0.027</td></tr><tr><td>Zero Day Measure Seven</td><td>19.089 ± 0.020</td><td>18.738 ± 0.021</td><td>18.339 ± 0.024</td></tr></table>
<p class="takeaway">Each seed contributes 16 individual frame scores after 40 warmup frames.</p>

$$
\operatorname{SMAPE}=\frac{100}{N}\sum_{i=1}^{N}\frac{\left|Y_i-Y_i^{\mathrm{ref}}\right|}{\left|Y_i\right|+\left|Y_i^{\mathrm{ref}}\right|+10^{-4}},\qquad Y=0.2126R+0.7152G+0.0722B
$$

<p class="small">Per-image score over N pixels. No factor of two. Linear HDR; finite 16384-spp reference.</p>
<p class="foot">Frozen archive: runs/pt-6-views-spatial-compare. Summary: results/summaries/falcor-pt-spatial-reuse/summary.csv.<br>“Ordinary” is the main deck’s Bitterli et al. [2020] baseline label, implemented in Falcor ReSTIR PT [Lin et al. 2022].</p>

---

## A2 | Where the GPU time goes

<img class="chart" style="height:435px" src="../assets/figures/stage-overview.png" alt="Initial sampling, temporal reuse, spatial reuse and other GPU frame time in five eligible views">
<p class="takeaway">Initial sampling: <strong>32.8–57.0%</strong> of baseline frame time.<br>CGNS spatial-stage increase: <strong>0.903–3.072 ms</strong>.</p>
<p class="foot">Cache / selection and retrace / merge are nested details, not extra terms to add to spatial time.<br>Retrace includes shift / reconnection and is not isolated visibility time. GPU frames 41–104, seed 0, no export; Emerald excluded; Veach recheck used.</p>

---

## A3 | Correlation is not a single quality score

<img class="chart" style="height:420px" src="../assets/figures/covariance-summary.png" alt="Temporal and spatial relative covariance across six views">
<p class="small">Signed relative covariance across four seed realizations; not Pearson correlation, not bias.<br>Temporal lag 3: 13 frame pairs. Spatial radius 8 disk, including center. Few seeds make pixelwise estimates noisy.</p>
<p class="foot">CGNS lowers temporal covariance in 6/6 views but increases spatial covariance in 6/6 views.<br>Do not rank differently scaled scenes by absolute covariance magnitude; no reference-covariance estimate is available.</p>

---

## A4 | Temporal reuse makes the largest difference

<img class="chart" style="height:430px" src="../assets/figures/temporal-ablation.png" alt="Ordinary reuse temporal on versus off SMAPE in all six views">
<p class="takeaway">Ordinary reuse: <strong>56.6–82.6% lower SMAPE</strong> with temporal on.</p>
<p class="foot">Same fixed cameras and transport; retained ordinary temporal-off results. This captured window is not an asymptotic convergence test.<br>The three-method comparison uses temporal on. Direction-history PDF with temporal off falls back to ordinary weighting.</p>

---

## A5 | An average gain can hide a local regression

<div class="two" style="grid-template-columns:1.35fr 1fr;gap:25px"><img style="width:100%;height:475px;object-fit:contain" src="../assets/figures/classroom-temporal-strips.png" alt="Classroom matched temporal strips with reference structure and three methods"><div><h3>Classroom | CGNS</h3><p>Whole scene:<br><strong>7.53% lower error</strong></p><p>Blackboard strip B:<br>10.932% →11.340% SMAPE<br><span class="red">+0.408 pp worse</span></p><p class="small">Strip A was selected for maximum observed CGNS gain. Strip B was chosen from reference structure / material contrast.</p><p class="small">These RGB strips are illustrative. Static geometry also creates vertical streaks; this is not a covariance heatmap.</p></div></div>
<p class="foot">Metric: all four seeds. Illustration: seed 0, frames 41–56. Frozen revised strip coordinates and source metrics are retained in the analysis directory.</p>

---

## A6 | What we validated—and what remains open

<div class="two"><div><h3>Implementation checks</h3><ul><li>Shared CPU / shader math and hand-computed two-reservoir MIS cases.</li><li>Forced <math><mi>h</mi><mo>=</mo><mn>1</mn></math> / <math><mi>h</mi><mo>=</mo><mn>0</mn></math> GPU controls and finite-output diagnostics.</li><li>Standard and Bistro glTF runtimes; continuous-motion history and reset checks.</li><li>Matched captures, configuration / runtime hashes, export-free timing replay.</li></ul></div><div><h3>Limits of this evidence</h3><ul><li>First-hop vMF loses multi-lobe / later-path structure; history can lag changes.</li><li>CGNS geometric affinity does not guarantee lighting compatibility.</li><li>Four seeds, finite references, one timing run; no equal-time claim.</li><li>Motion clips are qualitative. They have no reference video or motion-error ranking.</li></ul></div></div>
<p class="foot">Validation records: docs/reproductions/falcor-pdf-pt.md and falcor-cgns-pt.md.<br>These are documented project checks, not a new renderer validation run performed while preparing slides.</p>

---

## A7 | Resources and attribution

<div class="two"><div><h3>Algorithm foundations</h3><p style="font-size:23px"><a href="https://benedikt-bitterli.me/restir/">Bitterli et al. [2020]</a><br>Spatiotemporal Reservoir Resampling for Real-time Ray Tracing with Dynamic Direct Lighting</p><p style="font-size:23px"><a href="https://graphics.cs.utah.edu/research/projects/gris/">Lin et al. [2022]</a><br>Generalized Resampled Importance Sampling: Foundations of ReSTIR</p><p style="font-size:23px"><a href="https://doi.org/10.1145/3585501">Tokuyoshi [2023]</a><br>Efficient Spatial Resampling Using the PDF Similarity</p><p style="font-size:23px"><a href="https://research.nvidia.com/labs/rtr/publication/junkins2026compatibility/">Junkins et al. [2026]</a><br>Compatibility-Guided Neighbor Selection for ReSTIR</p></div><div><h3>Software and assets</h3><p style="font-size:23px"><a href="https://github.com/NVIDIAGameWorks/Falcor">NVIDIA Falcor</a>, <a href="https://github.com/NVIDIA-RTX/RTXDI">RTXDI</a>, <a href="https://github.com/orion-junkins/ReSTIR-CGNS">CGNS author code</a><br>Marp, FFmpeg, Python / NumPy / Matplotlib / OpenEXR</p><p style="font-size:23px">Bistro: Amazon Lumberyard / NVIDIA ORCA<br>Classroom: Christophe Seux / Blender<br>Emerald Square: NVIDIA / ORCA<br>Hull, Anderson and Benty<br>Veach Ajar: Benedikt Bitterli scene collection<br>Zero Day Measure Seven: Beeple</p><p class="small">Project-authored explanatory diagrams and renders. Scene license details: THIRD_PARTY.md and scenes/manifest.yaml.<br>Frozen results, processing hashes and media metadata are indexed under writing/final/data/.</p></div></div>
<p class="foot">These references distinguish source algorithms, author code and our adaptations. No paper results are presented as project measurements.</p>
