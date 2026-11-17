---
marp: true
math: katex
theme: restir-final
size: 16:9
paginate: true
title: "ReSTIR Spatial Reuse: Final Presentation"
author: "Luoyi Zhang and Zelin Gao"
description: "COMP5411 Group 7 | 4:30 rehearsal target | 16 November 2026"
---

<!-- _class: cover -->
<!-- _paginate: false -->

<div class="cover-grid"><div>
<h1>ReSTIR<br>Spatial Reuse</h1>
<p class="subtitle">From ReSTIR DI to ReSTIR PT</p>
<p>Implementation and evaluation<br><strong style="color:#a4e1d6">Final presentation</strong></p>
<p class="names">Group 7<br>Luoyi Zhang, Zelin Gao</p>
</div><figure><img src="../assets/figures/scene-montage.png" alt="Six evaluated fixed views: Bistro Interior, Bistro Exterior, Classroom, Emerald Square, Veach Ajar, Zero Day Measure Seven"><figcaption class="cover-caption">Our rendered reference images of 6 scenes</figcaption></figure></div>
<p class="foot">COMP5411 | 16 November 2026</p>

<!--
0:00 to 0:08 | 8 seconds | rehearsal target

We're Group Seven. We compare spatial reuse strategies for cleaner ReSTIR path tracing at a practical GPU cost.

Cue: Keep title, group and names visible. The images are our finite-sample references, used only to introduce the scenes.
-->

---
<!-- _class: pipeline -->

## Three spatial reuse methods in ReSTIR PT

<p class="lead">Direct lighting (RTXDI) → Path tracing (Falcor)</p>
<div class="pt-flow" role="img" aria-label="Initial sampling, temporal reuse, spatial reuse, resolve. Three alternatives are compared at the spatial reuse stage.">
<div class="pt-stages"><div class="pt-stage"><h3>Initial sampling</h3><p>Generate paths</p></div><span class="pt-arrow">→</span><div class="pt-stage"><h3>Temporal reuse</h3><p>Reuse across frames</p></div><span class="pt-arrow">→</span><div class="pt-stage pt-focus"><h3>Spatial reuse</h3><p>Compare three methods</p></div><span class="pt-arrow">→</span><div class="pt-stage"><h3>Resolve</h3><p>Produce the image</p></div></div>
<div class="pt-methods"><span class="pt-method-label">Spatial reuse variants</span><span>Ordinary reuse</span><span class="pt-pdf">PDF Similarity</span><span class="pt-cgns">CGNS</span></div>
</div>
<div class="overview-columns"><div><h3>Technical challenges</h3><ul><li>Adapt PDF Similarity from DI to ReSTIR PT.</li><li>Adapt CGNS to ReSTIR PT.</li><li>Convert scene formats unsupported by Falcor.</li><li>Keep multi-bounce path-reuse weights consistent.</li></ul></div><div><h3>Implemented</h3><ul><li>PDF Similarity adaptation for ReSTIR PT</li><li>CGNS adaptation</li><li>A reproducible experiment harness</li><li>ReSTIR research roadmap<br><a class="roadmap-url" href="https://thelogarhythm.github.io/restir-lab/" target="_blank" rel="noopener">https://thelogarhythm.github.io/restir-lab/</a></li></ul></div></div>
<p class="foot overview-resources"><strong>Resources used:</strong> <a href="https://github.com/NVIDIA-RTX/RTXDI">RTXDI</a>, <a href="https://github.com/NVIDIAGameWorks/Falcor">Falcor</a>, <a href="https://github.com/orion-junkins/ReSTIR-CGNS">official CGNS implementation</a>; scene assets from NVIDIA ORCA, Blender, Bitterli and Beeple.<br><strong>Papers:</strong> <a href="https://benedikt-bitterli.me/restir/">Bitterli et al. [2020]</a> · <a href="https://graphics.cs.utah.edu/research/projects/gris/">Lin et al. [2022]</a> · <a href="https://doi.org/10.1145/3585501">Tokuyoshi [2023]</a> · <a href="https://research.nvidia.com/labs/rtr/publication/junkins2026compatibility/">Junkins et al. [2026]</a></p>

<!--
0:08 to 0:20 | 12 seconds | rehearsal target

Since the checkpoint, we adapted PDF Similarity and CGNS to Falcor ReSTIR PT, with scene conversion, consistent reuse weights and a reproducible experiment harness.

Cue: Point to the spatial stage, then summarize the challenges and delivered work. The roadmap name links to the public ReSTIR Explorer. Resources and foundational papers are linked along the bottom. Pipeline is a project-authored schematic.
-->

---
<!-- _class: pdf -->

## PDF Similarity: adapting single-bounce reuse to multi-bounce paths

<p class="lead" style="font-size:23px;margin:4px 0 8px">Tokuyoshi [2023] targets single-bounce connections. <strong>We adapt the idea to multi-bounce ReSTIR PT.</strong></p>
<img class="diagram" style="height:245px" src="../assets/diagrams/first-hop.svg" alt="Eye symbols observe two surface points. Multi-bounce contributions retain their first-hop directions; directional distributions are approximated and compared.">
<div class="pt-adaptation"><div><h3>1. Estimate a first-hop<br>direction distribution</h3><p>Record the first direction leaving the visible surface, weighted by each initial path contribution. Accumulate valid history across frames and fit a <strong>vMF lobe</strong>.</p></div><div><h3>2. Compare neighboring<br>distributions</h3><p>Compare lobe <strong>directions and concentration</strong> to estimate PDF similarity: do nearby pixels receive useful light from similar directions?</p></div><div><h3>3. Adjust the neighbor’s<br>effective sample count</h3><p>Scale the proposed neighbor’s <strong>effective sample count</strong>. Dissimilar distributions reduce its influence; insufficient history falls back to ordinary reuse.</p></div></div>

$$
M_{\mathrm{eff}}=\big[(1-c)+cS\big]M_{\mathrm{neighbor}}
$$

<p style="font-size:18px;text-align:center;margin:0;color:#69584b">S: distribution similarity · c: history confidence</p>

<!--
0:20 to 0:40 | 20 seconds | rehearsal target

The original PDF method targets single-bounce connections. Our PT adaptation summarizes contribution-weighted first-hop directions with a vMF lobe. Comparing neighboring lobes scales the proposed neighbor's effective sample count. With insufficient history, ordinary reuse is restored.

Cue: Follow the first orange segments, then compare the lobes. Later contributions retain their first direction leaving the visible surface. Similarity changes the influence of the already-proposed neighbor; native path shifting remains. S is similarity, c is joint history confidence. A vMF lobe is a smooth directional approximation.
-->

---
<!-- _class: cgns -->

## CGNS: choose neighbors likely to support path reuse

<div class="cgns-top"><figure><img src="../assets/figures/cgns-figure2.png" alt="Junkins et al. Figure 2. Left: original and reconnected paths. Right: camera-distance-scaled world-space neighborhood."><figcaption>CGNS Fig. 2 [Junkins et al. 2026]: path reconnection and position scale.</figcaption></figure><div><h3>Why position and normals?</h3><p>Nearby primary hits with similar normals are more likely to preserve BSDF, geometry and visibility after shifting.</p><p>A continuous score ranks candidates; binary thresholds can reject every borderline neighbor.</p></div></div>

<div class="cgns-formula-label">Ordinary acceptance | Bitterli et al. [2020]</div>

$$
\mathbf n\cdot\mathbf n_i\geq 0.5,\qquad \frac{|d_i-d|}{d}<0.1
$$

<div class="cgns-formula-label">CGNS | continuous geometric compatibility</div>

$$
h(\mathbf x_1,\mathbf y_1)=h_p(\mathbf x_1,\mathbf y_1)\,h_n(\mathbf x_1,\mathbf y_1)
$$

$$
h_p=\exp\!\left(-\frac{\|\mathbf x_1-\mathbf y_1\|}{s}\right),\qquad
h_n=\max(\mathbf n_{\mathbf x_1}\cdot\mathbf n_{\mathbf y_1},0)^\beta
$$

<div class="cgns-bottom"><p class="cgns-selection"><strong>Weighted selection</strong><br>Sample neighbors in proportion to compatibility.</p><div class="cgns-definitions"><p><math><mi mathvariant="bold">n</mi><mo>,</mo><msub><mi mathvariant="bold">n</mi><mi>i</mi></msub></math>: primary-hit normals; <math><mi>d</mi><mo>,</mo><msub><mi>d</mi><mi>i</mi></msub></math>: camera distances.</p><p>Position scale: <math><mi>s</mi><mo>=</mo><mi>d</mi><msqrt><mfrac><mi>Ω</mi><mi>π</mi></mfrac></msqrt></math>. Defaults: <math><mi>Ω</mi><mo>=</mo><mn>0.05</mn></math>, <math><mi>β</mi><mo>=</mo><mn>8</mn></math>.</p></div></div>

<!--
0:40 to 0:55 | 15 seconds | rehearsal target

CGNS samples a neighbor using continuous position-and-normal compatibility. Our adaptation caches geometry and the selected neighbor so all reuse stages share one choice.

Cue: Figure 2 and formulas describe the CGNS paper; the acceptance thresholds are the original 2020 criteria, not a claim of identical Falcor checks. Contrast choice of neighbor with PDF's weighting of the ordinary proposed neighbor. Compatibility is a probabilistic guide, not guaranteed visibility or lighting compatibility. Cache adds about 71.2 MiB at 1080p; not a free optimization. Figure 2 is an attributed author figure. Material compatibility motivated the analysis but was omitted from the final heuristic after no measurable benefit in the authors’ tested scenes; this is not a guarantee about all materials.
-->

---
<!-- _class: quality -->

## CGNS lowers mean error in all six fixed views

<p class="lead">SMAPE reduction relative to ordinary spatial reuse | Higher is better</p>
<div class="quality-layout"><div><img class="chart" src="../assets/figures/quality-improvement.png" alt="Six-view relative SMAPE reductions: CGNS 3.93 to22.75%; PDF Similarity minus5.63 to plus2.09%."></div><div class="quality-definitions"><div>
<h3>Relative SMAPE reduction</h3>

$$
100\left(1-\frac{\bar E_{\mathrm{method}}}{\bar E_{\mathrm{ordinary}}}\right)\%
$$



$\bar E$: mean SMAPE across frames.


</div><div>
<h3>SMAPE (lower is better)</h3>

$$
E=100\,\underset{p}{\mathrm{mean}}\;\frac{|Y_p-Y_p^{\mathrm{ref}}|}{|Y_p|+|Y_p^{\mathrm{ref}}|+10^{-4}}
$$



$Y$: rendered luminance; $Y^{\mathrm{ref}}$: reference luminance.


</div><div class="quality-conclusion"><p class="takeaway"><strong>CGNS: 3.9–22.7% lower error.</strong> <span class="purple">PDF: small gains, a near-zero change, and regressions.</span></p></div></div></div>



<!--
0:55 to 1:10 | 15 seconds | rehearsal target

CGNS lowers mean SMAPE in all six views, by about four to twenty-three percent. PDF gives smaller gains and some regressions. These are matching-settings results over four seeds, not equal-time comparisons.

Cue: Indicate the zero line and negative PDF bar. Near-zero Bistro Interior change is only 0.006%; don't sell it as a meaningful win. Four seed means are independent units; the 64 frames are correlated within seeds.
-->

---
<!-- _class: failure -->

## Emerald Square exposes the strongest PDF regression

<div class="failure-layout"><div class="failure-images">
<img class="failure-map" src="../assets/figures/emerald-change-pp.png" alt="PDF and CGNS error-change maps: blue lower error, red higher error; same ±20 percentage-point scale">
<img class="failure-crops" src="../assets/figures/emerald-frame48-crops.png" alt="Matched illustrative crop: ordinary reuse, PDF Similarity, CGNS, reference">
</div><div class="failure-explanation">
<h3 class="purple">PDF Similarity</h3><p><strong class="purple">5.63% more error</strong><br>SMAPE<br>25.55% → 26.99%</p>
<h3>CGNS</h3><p><strong>22.75% less error</strong><br>SMAPE<br>25.55% → 19.74%</p>
<p class="cgns-reason">Emerald Square contains many fine structures, and nearby pixels can belong to very different surfaces. Geometry-guided heuristics increase the chance of selecting a useful path reservoir.</p>


</div></div>

<!--
1:10 to 1:30 | 20 seconds | rehearsal target

Blue means lower error; red means higher error. Emerald shows the largest CGNS gain and PDF regression. A single directional lobe may lose useful structure, but these images cannot establish the cause.

Cue: Use the color legend. Map units are percentage points; headline values are relative percentages. Emerald timing is excluded, so do not make a speed claim for this scene.
-->

---
<!-- _class: local-result -->

## Whole-scene improvement can hide local regressions

<div class="local-layout"><img class="local-comparison" src="../assets/figures/classroom-local-results.png" alt="Classroom reference locations A and B, with tightly spaced matched crops for ordinary reuse, PDF and CGNS">
<div class="local-explanation"><h3>Classroom overall</h3><p>CGNS lowers SMAPE by <strong>7.53%</strong>.</p>
<h3>Region A improves</h3><p>40.834% → 29.204%<br>SMAPE</p>
<h3>Blackboard B regresses</h3><p>10.932% → 11.340%<br>SMAPE</p></div></div>

<!--
1:30 to 1:45 | 15 seconds | rehearsal target

CGNS improves Classroom overall, but not every region. The selected region A improves strongly, while the blackboard strip gets slightly worse. These local examples show why a whole-scene average cannot tell the complete story.

Cue: Identify the marked strips. Numerical values average four seeds and sixteen frames; RGB crops show one frame only. A is gain-selected, B reference-selected. Avoid claiming a causal explanation.
-->

---
<!-- _class: covariance-result -->

## CGNS changes the structure of noise

<img class="chart" style="height:310px" src="../assets/figures/covariance-change.png" alt="Relative covariance changes: CGNS lowers temporal covariance but increases spatial covariance in all six views">
<div class="two covariance-definitions"><div><h3>Temporal covariance ↓8.8–40.4%</h3>
<p>How strongly noise varies together<br>at the same pixel across frames.</p>

$$
C_T=\operatorname{Cov}_s\!\left[r_s(p,t),r_s(p,t+3)\right]
$$

</div><div><h3>Spatial covariance ↑1.7–24.9%</h3>
<p>How strongly noise varies together<br>across nearby pixels in one frame.</p>

$$
C_S=\underset{q\in D_8(p)}{\mathrm{mean}}\operatorname{Cov}_s\!\left[r_s(p,t),r_s(q,t)\right]
$$

</div></div>

<div class="covariance-residual">

$r_s=\frac{Y_s-\bar Y}{\bar Y+10^{-4}}$: normalized luminance deviation; $s$: seed; $D_8(p)$: radius-8 pixel disk.

</div>
<p class="takeaway"><strong>Lower average error does not mean every noise characteristic improves.</strong></p>

<!--
1:45 to 2:00 | 15 seconds | rehearsal target

Covariance measures how strongly noise varies together across frames or nearby pixels. CGNS lowers temporal covariance but raises spatial covariance in all six views. This is a tradeoff in noise structure, not a uniform reduction in correlation.

Cue: Point to the zero lines. These are relative changes within scenes; do not rank absolute covariance across scenes or equate it with visible flicker. Four seeds limit precision.
-->

---
<!-- _class: cost expanded-cost -->

## Quality gains come with additional GPU cost

<div class="cost-layout"><div class="cost-images">
<img class="cost-overhead" src="../assets/figures/timing-overhead.png" alt="GPU frame-time overhead across five eligible views: PDF8.16–26.93%, CGNS3.95–5.92%">
<img class="cost-stages" src="../assets/figures/bistro-interior-stage-cost.png" alt="Bistro Interior GPU frame time split into initial sampling, temporal reuse, spatial reuse and other time">
</div><div class="cost-explanation"><h3>Additional frame time</h3><p><strong>CGNS: +4.0–5.9%</strong><br><span class="purple">PDF: +8.2–26.9%</span></p>
<h3>Quality / cost tradeoff</h3><p>Ordinary reuse is fastest.<br>CGNS offers the strongest observed tradeoff here.</p>
<h3>Bistro Interior</h3><p>Initial sampling is the largest baseline stage. CGNS adds work mainly to spatial reuse.</p>
<p class="cost-note">Measured on an RTX 4060 Laptop GPU.</p></div></div>

<!--
2:00 to 2:15 | 15 seconds | rehearsal target

CGNS costs around four to six percent extra GPU time; PDF costs more. Bistro Interior illustrates where time goes: initial sampling, temporal and spatial reuse. Ordinary reuse is cheapest; CGNS offers the strongest observed quality-cost tradeoff here.

Cue: All stage segments reconcile to full frame time. Initial sampling is the largest measured baseline high-level stage across five eligible views. Nested events must not be added twice. No equal-time superiority claim.
-->

---
<!-- _class: demo -->
<!-- _paginate: false -->

<video class="demo-video" muted playsinline controls loop preload="metadata" poster="../assets/videos/bistro-interior-course-v2.png" src="../assets/videos/bistro-interior-course-v2.mp4" aria-label="Bistro Interior synchronized three-method trajectory comparison"></video>
<img class="print-poster" src="../assets/videos/bistro-interior-course-v2.png" alt="Bistro Interior demo poster">

<!--
2:15 to 2:45 | 30 seconds | demo1

First, Bistro Interior uses our separate glTF runtime. Its fixed-view PDF result was almost unchanged. Watch the moving view without assuming it must show a large improvement, especially near newly visible surfaces where history confidence falls.

Cue: Three complete 10-second loops. Do not claim a measured moving-view error ranking; no trajectory reference was rendered. The implementation preserves valid history through continuous camera motion and rejects invalid reprojections.
-->

---
<!-- _class: demo -->
<!-- _paginate: false -->

<video class="demo-video" muted playsinline controls loop preload="metadata" poster="../assets/videos/bistro-exterior-course-v2.png" src="../assets/videos/bistro-exterior-course-v2.mp4" aria-label="Bistro Exterior synchronized three-method trajectory comparison"></video>
<img class="print-poster" src="../assets/videos/bistro-exterior-course-v2.png" alt="Bistro Exterior demo poster">

<!--
2:45 to 3:15 | 30 seconds | demo2

Bistro Exterior is where both extensions improved fixed-view error, with a larger gain for CGNS. Watch how detail and noise change as the camera passes geometry. The crops use the same coordinates and display transform for all methods.

Cue: Three 10-second loops at 1×. Pausing may help live discussion; for the 4:30 recording keep the 30-second slot. MP4 compression can hide fine noise; linear HDR metrics remain the quantitative evidence.
-->

---
<!-- _class: demo -->
<!-- _paginate: false -->

<video class="demo-video" muted playsinline controls loop preload="metadata" poster="../assets/videos/zero-day-course-v2.png" src="../assets/videos/zero-day-course-v2.mp4" aria-label="Zero Day Measure Seven synchronized three-method trajectory comparison"></video>
<img class="print-poster" src="../assets/videos/zero-day-course-v2.png" alt="Zero Day Measure Seven demo poster">

<!--
3:15 to 3:45 | 30 seconds | demo3

Zero Day. CGNS gave its smallest fixed-view improvement here, about four percent. This is a useful modest-benefit case. The displayed GPU FPS comes from a separate replay of the same camera sequence, with image export disabled.

Cue: Three 10-second loops. GPU FPS uses a trailing 15-frame mean and excludes CPU/export/encoding. Do not equate smooth 30 FPS playback with the application's rendering rate. The 120-second demo budget includes all four repeated clips.
-->

---
<!-- _class: demo -->
<!-- _paginate: false -->

<video class="demo-video" muted playsinline controls loop preload="metadata" poster="../assets/videos/classroom-course-v2.png" src="../assets/videos/classroom-course-v2.mp4" aria-label="Classroom synchronized three-method trajectory comparison"></video>
<img class="print-poster" src="../assets/videos/classroom-course-v2.png" alt="Classroom demo poster: three matched method views and equal-location magnified crops">

<!--
3:45 to 4:15 | 30 seconds | demo4

Finally, Classroom. The top row shows the matched camera motion; the lower row magnifies identical regions. Compare the noise on surfaces rather than the apparent playback speed. All three play at thirty FPS; the watermark reports GPU rendering performance.

Cue: Play the complete 10-second trajectory three times, at 1× speed. First and last seconds are still; middle 8 seconds move. Note that moving-view footage is qualitative, not the fixed-view statistical test. Forty warmup frames are outside the clip. Allow time to watch rather than filling all 30 seconds with narration.
-->

---
<!-- _class: closing -->

## Conclusion: Prefer CGNS

<ul>
<li><strong>CGNS offers the best quality–cost tradeoff.</strong><span>Lower SMAPE in all six views, with 3.9–22.7% reductions and 4.0–5.9% extra GPU time.</span></li>
<li><strong>PDF Similarity’s PT adaptation brings limited gains.</strong><span>Small, scene-dependent improvements, with regressions and higher GPU cost than CGNS.</span></li>
<li><strong>Spatial reuse still faces correlation and visibility challenges.</strong><span>Noise patterns may briefly appear stretched during camera motion. Shadow boundaries and disocclusions remain challenging.</span></li>
</ul>
<div class="closing-credits"><div><h3>Resources used</h3><p><a href="https://github.com/NVIDIA-RTX/RTXDI">NVIDIA RTXDI</a> / <a href="https://github.com/NVIDIAGameWorks/Falcor">Falcor</a><br><a href="https://github.com/orion-junkins/ReSTIR-CGNS">CGNS official implementation</a></p><p class="asset-credit">Scene assets: NVIDIA ORCA, Blender,<br>Benedikt Bitterli and Beeple</p></div><div><h3>References</h3><div class="closing-paper-grid"><a href="https://benedikt-bitterli.me/restir/">Bitterli et al. [2020]<span>ReSTIR</span></a><a href="https://graphics.cs.utah.edu/research/projects/gris/">Lin et al. [2022]<span>GRIS / ReSTIR PT</span></a><a href="https://doi.org/10.1145/3585501">Tokuyoshi [2023]<span>PDF Similarity</span></a><a href="https://research.nvidia.com/labs/rtr/publication/junkins2026compatibility/">Junkins et al. [2026]<span>CGNS</span></a></div></div></div>

<!--
4:15 to 4:27 | 12 seconds | rehearsal target

CGNS offers the best tradeoff. PDF’s gains are limited and costlier. Correlation and visibility challenges remain, including briefly stretched noise patterns during motion.

Cue: Move to the Thanks slide at 4:27. This is a recommendation for the tested implementations and settings, not a universal algorithm ranking. PDF SMAPE higher than CGNS in all 6;PDF frame time higher in all 5 eligible views. Open the separate appendix only for questions. Resources and scene credits are fully linked there.
-->

---
<!-- _class: thanks -->
<!-- _paginate: false -->

# Thanks for listening

<!--
4:27 to 4:30 | 3 seconds | rehearsal target

Thank you for listening.

Cue: Hold the final slide and finish at 4:30.
-->
