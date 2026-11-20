---
marp: true
math: katex
theme: restir-final
size: 16:9
paginate: true
title: "ReSTIR Spatial Reuse: Final Presentation"
author: "Luoyi Zhang and Zelin Gao"
description: "COMP5411 Group 7 | 4:40 rehearsal target | 16 November 2026"
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

Hi everyone. We’re Group Seven, and we’re comparing three ways to reuse light paths in ReSTIR.

Cue — Advance at 0:08.
-->

---
<!-- _class: motivation -->

## <span class="motivation-prefix">Motivation</span> Nearby pixels can see different light

<div class="motivation-layout">
  <figure><img src="../assets/figures/bistro-shadow-boundary.png" alt="Bistro Exterior pavement. Marker A lies in shadow, and marker B nearby lies in direct sunlight."></figure>
  <div class="motivation-details">
    <p><strong class="marker-a">A</strong> In shadow</p>
    <p><strong class="marker-b">B</strong> In direct sun</p>
    <div class="motivation-question">Which neighboring pixel(s) to reuse?</div>
  </div>
</div>

<!--
0:08 to 0:25 | 17 seconds | rehearsal target

At one sample per pixel, path tracing is noisy. Spatial reuse reduces that noise by borrowing paths already sampled at nearby pixels. But look at A and B. They’re right next to each other, on opposite sides of a shadow edge. That’s why the choice of neighbor matters.

Cue — Point to A and B when you mention the shadow edge. Advance at 0:25.
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
0:25 to 0:38 | 13 seconds | rehearsal target

Since the checkpoint, we’ve moved from direct lighting in RTXDI to multi-bounce path tracing in Falcor. We compare ordinary reuse with our adaptations of PDF Similarity and CGNS.

Cue — Point to the highlighted spatial reuse stage. The slide lists the implementation challenges. Advance at 0:38.
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
0:38 to 0:55 | 17 seconds | rehearsal target

To adapt PDF Similarity to multi-bounce paths, we summarize the directions in which paths leave the first surface. We compare those distributions at neighboring pixels to decide how much the proposed neighbor should contribute.

Cue — Follow the first segments in the diagram. Advance at 0:55.
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
0:55 to 1:12 | 17 seconds | rehearsal target

Ordinary reuse uses pass-or-fail checks. CGNS gives each candidate a compatibility score based on position and surface normal. Nearby surfaces with similar normals are more likely to support reuse of the same light path.

Cue — Point to the candidate ranking and the selected neighbor. Advance at 1:12.
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
1:12 to 1:28 | 16 seconds | rehearsal target

With the same sampling settings, CGNS reduced mean image error in all six fixed views, by about four to twenty-three percent. PDF Similarity gave smaller gains and increased error in some views.

Cue — Point to the zero line, then the range of CGNS bars. Advance at 1:28.
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
1:28 to 1:44 | 16 seconds | rehearsal target

Emerald Square shows the biggest difference. Compared with ordinary reuse, CGNS reduced error by about twenty-three percent, while PDF Similarity increased it by about six percent. In this crop, CGNS looks closest to the reference.

Cue — Point to the blue and red regions. Advance at 1:44.
-->

---
<!-- _class: local-result -->

## Whole-scene improvement can hide local regressions

<div class="local-layout"><img class="local-comparison" src="../assets/figures/classroom-local-results.png" alt="Classroom reference locations A and B, with tightly spaced matched crops for ordinary reuse, PDF and CGNS">
<div class="local-explanation"><h3>Classroom overall</h3><p>CGNS lowers SMAPE by <strong>7.53%</strong>.</p>
<h3>Region A improves</h3><p>40.834% → 29.204%<br>SMAPE</p>
<h3>Blackboard B regresses</h3><p>10.932% → 11.340%<br>SMAPE</p></div></div>

<!--
1:44 to 1:58 | 14 seconds | rehearsal target

Classroom shows why we also look at individual regions. CGNS improves the view overall, and region A improves substantially. The blackboard strip marked B has a small increase in error.

Cue — Point to the two marked strips. Advance at 1:58.
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
1:58 to 2:11 | 13 seconds | rehearsal target

Covariance tells us how strongly noise varies together. In all six fixed views, CGNS lowered covariance at the same pixel across frames and raised it between nearby pixels.

Cue — Point to the opposing sides of the zero line. Advance at 2:11.
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
2:11 to 2:28 | 17 seconds | rehearsal target

That quality gain comes at a cost. CGNS added about four to six percent to GPU frame time, and PDF Similarity added more. In Bistro Interior, most of the extra work for CGNS was in spatial reuse.

Cue — Point to spatial reuse in the Bistro Interior breakdown. Advance at 2:28.
-->

---
<!-- _class: demo -->
<!-- _paginate: false -->

<video class="demo-video" muted playsinline controls preload="metadata" poster="../assets/videos/bistro-interior-fps.png" src="../assets/videos/bistro-interior-fps.mp4" aria-label="Bistro Interior"></video>
<img class="print-poster" src="../assets/videos/bistro-interior-fps.png" alt="Bistro Interior poster">

<!--
2:28 to 2:46 | 18 seconds | demo

Here’s Bistro Interior. The curves show GPU rendering rate along the same camera path.
- First hold, about 2:30 — Look at the chair legs.
- Second hold, about 2:37 — Now look at the chair back.

Cue — Advance at 2:46.
-->

---
<!-- _class: demo -->
<!-- _paginate: false -->

<video class="demo-video" muted playsinline controls preload="metadata" poster="../assets/videos/bistro-exterior-fps.png" src="../assets/videos/bistro-exterior-fps.mp4" aria-label="Bistro Exterior"></video>
<img class="print-poster" src="../assets/videos/bistro-exterior-fps.png" alt="Bistro Exterior poster">

<!--
2:46 to 3:04 | 18 seconds | demo

Now we’re outside the Bistro. Watch the magnified view along the bottom.
- First hold, about 2:52 — Compare the edges of the sign.
- Second hold, about 2:58 — Look at the thin chair legs and the pavement beneath them.

Cue — Advance at 3:04.
-->

---
<!-- _class: demo -->
<!-- _paginate: false -->

<video class="demo-video" muted playsinline controls preload="metadata" poster="../assets/videos/zero-day-fps.png" src="../assets/videos/zero-day-fps.mp4" aria-label="Zero Day Measure Seven"></video>
<img class="print-poster" src="../assets/videos/zero-day-fps.png" alt="Zero Day Measure Seven poster">

<!--
3:04 to 3:19 | 15 seconds | demo

Here’s Zero Day Measure Seven.

Cue — Let the clip play through. Advance at 3:19.
-->

---
<!-- _class: demo -->
<!-- _paginate: false -->

<video class="demo-video" muted playsinline controls preload="metadata" poster="../assets/videos/classroom-fps.png" src="../assets/videos/classroom-fps.mp4" aria-label="Classroom"></video>
<img class="print-poster" src="../assets/videos/classroom-fps.png" alt="Classroom poster">

<!--
3:19 to 3:34 | 15 seconds | demo

And this is Classroom. Keep an eye on the blackboard as the camera moves.

Cue — Let the clip play through. Advance at 3:34.
-->

---
<!-- _class: demo -->
<!-- _paginate: false -->

<video class="demo-video" muted playsinline controls preload="metadata" poster="../assets/videos/cgns-nrd-results.png" src="../assets/videos/cgns-nrd-results.mp4" aria-label="Final renders with CGNS and NRD"></video>
<img class="print-poster" src="../assets/videos/cgns-nrd-results.png" alt="Final renders with CGNS and NRD poster">

<!--
3:34 to 4:17 | 43 seconds | demo

- 3:34 · Bistro Interior — For these one-sample-per-pixel renders, we added NRD, NVIDIA’s real-time denoiser. A few bright speckles still flicker indoors.
- 3:44 · Bistro Exterior — The outdoor shot looks cleaner overall, especially on the pavement around the chairs.
- 3:54 · Zero Day — Some noise is still visible around the bright panels.
- 4:04 · Classroom — In Classroom, the blackboard looks fairly clean as the camera moves past it.

Cue — Let the montage finish at 4:14. Advance at 4:17.
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
4:17 to 4:37 | 20 seconds | rehearsal target

Of the three methods we tested, CGNS gave the best balance of image quality and GPU cost. It improved all six fixed views with a modest increase in frame time. The walkthroughs also show where there’s room to improve, especially around visibility boundaries and during camera motion.

Cue — Advance to the thank-you slide at 4:37.
-->

---
<!-- _class: thanks -->
<!-- _paginate: false -->

# Thanks for listening

<!--
4:37 to 4:40 | 3 seconds | rehearsal target

Thank you for listening.

Cue — Finish at 4:40.
-->
