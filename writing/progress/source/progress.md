---
marp: true
theme: default
size: 16:9
paginate: true
title: "ReSTIR Spatial Reuse: Project Progress"
author: "Luoyi Zhang and Zelin Gao"
description: "COMP5411 Group 7. Progress report draft, 24 October 2026."
style: |
  section {background:#f5f7f5;color:#182e3a;font-family:'Segoe UI',Arial,sans-serif;font-size:27px;line-height:1.28;padding:43px 58px 94px;display:block;}
  section::before{content:'';position:absolute;left:0;top:0;width:8px;height:100%;background:#13847d;}
  section::after{color:#71868e;top:24px;right:32px;bottom:auto;font-size:16px;}
  h1{font-size:62px;line-height:1.06;letter-spacing:-1.6px;margin:0 0 22px;}
  h2{font-size:43px;line-height:1.12;letter-spacing:-.8px;margin:0 0 24px;}
  h3{font-size:25px;color:#08766e;margin:0 0 12px;}
  p{margin:0 0 18px;} strong{color:#08766e;}
  a{color:#08766e;} ul{padding-left:25px;margin:0;}li{padding-left:3px;margin-bottom:20px;}
  .lead{font-size:26px;color:#536a73;margin-bottom:24px;}
  .small{font-size:19px;color:#536a73;line-height:1.35;}
  .foot{position:absolute;left:58px;bottom:30px;max-width:920px;font-size:17px;line-height:1.3;color:#5c7178;}
  .two{display:grid;grid-template-columns:1fr 1fr;gap:32px;align-items:start;}
  .two.text-image{grid-template-columns:0.85fr 1.15fr;gap:40px;}
  figure{margin:0;}figure img{display:block;width:100%;object-fit:contain;background:#10212b;}figcaption{font-size:21px;margin-top:10px;}
  .two figure img{aspect-ratio:16/9;}
  .method-table{width:100%;border-collapse:collapse;display:table;font-size:26px;margin:5px 0 24px;}
  table th,table td{border:0;border-bottom:1px solid #c9d8d6;text-align:left;padding:19px 18px;background:transparent;}
  table tr{background:transparent !important;}table th{background:#e2ece9;font-size:21px;color:#4e666e;}
  .method-table td:first-child{width:230px;font-weight:600;}
  .method-table td:last-child{width:240px;font-size:22px;color:#08766e;}
  .metrics{width:100%;display:table;border-collapse:collapse;font-size:25px;margin-top:21px;}
  .metrics td,.metrics th{padding:10px 16px;}
  .metrics td{font-variant-numeric:tabular-nums;}
  .codework{display:grid;grid-template-columns:1fr 1fr;column-gap:50px;row-gap:25px;}
  .codework div{border-top:2px solid #a9c8c2;padding-top:13px;}
  .codework p{font-size:25px;}
  section.cover{background:#142d39;color:#f8fbfa;padding:52px 58px;}
  section.cover::before{display:none;}section.cover .cover-grid{display:grid;grid-template-columns:510px 1fr;gap:30px;align-items:center;height:500px;}
  section.cover h1{font-size:64px;color:#f8fbfa;}section.cover .subtitle{color:#a4e1d6;font-size:29px;}section.cover .names{font-size:23px;color:#d8e6e5;margin-top:42px;}
  section.cover figure img{height:460px;object-fit:cover;object-position:58% center;}section.cover .small{color:#bdd0d2;font-size:15px;}
  section.cover .foot{color:#c1d3d5;}
  section.new-scenes{padding:30px 52px 54px;}
  section.new-scenes h2{font-size:39px;margin:0 0 7px;}
  section.new-scenes .lead{font-size:22px;margin:0 0 17px;}
  .scene-grid{display:grid;grid-template-columns:repeat(3,1fr);column-gap:23px;row-gap:18px;}
  .scene-grid img{display:block;width:100%;height:auto;aspect-ratio:16/9;object-fit:contain;}
  .scene-grid figcaption{display:flex;justify-content:space-between;align-items:baseline;gap:8px;margin-top:7px;line-height:1.2;}
  .scene-grid .scene-name{font-size:22px;font-weight:600;white-space:nowrap;}
  .scene-grid .scene-desc{font-size:16px;color:#536a73;white-space:nowrap;}
  section.new-scenes .foot{left:52px;bottom:15px;max-width:1170px;font-size:15px;line-height:1.4;}
  .demo{width:816px;height:459px;position:relative;background:#0b111b;}
  .demo video{display:block;width:100%;height:100%;object-fit:contain;}
  .demo .print-poster{display:none;width:100%;height:100%;object-fit:contain;}
  .demo-caption{margin-top:11px;font-size:20px;color:#526b75;}
  section.pdf-method .lead{font-size:25px;margin-bottom:20px;}
  .pdf-figure{width:100%;height:328px;object-fit:contain;background:white;display:block;}
  .pdf-explanation{display:grid;grid-template-columns:1fr 1fr;gap:50px;margin-top:18px;}
  .pdf-explanation h3{font-size:24px;margin-bottom:7px;}
  .pdf-explanation p{font-size:23px;line-height:1.3;}
  .result-pair{display:grid;grid-template-columns:1fr 1fr;gap:26px;}
  .result-pair img{height:235px;object-fit:contain;}
  .sequence-pair img{height:auto;aspect-ratio:16/9;}
  .failure-pair{display:grid;grid-template-columns:1fr 1fr;gap:26px;}
  .failure-pair img{height:256px;object-fit:contain;}
  .failure-pair figcaption{font-size:22px;}
  .limits{margin-top:19px;max-width:1030px;font-size:23px;}
  section.closing{background:#142d39;color:#eff7f5;}section.closing h2{color:#eff7f5;}section.closing strong{color:#9dddd0;}
  section.closing li{font-size:31px;margin-bottom:30px;max-width:1040px;}section.closing .foot{color:#c1d3d5;}
  section.thank-you{display:grid;place-items:center;padding:0;}
  section.thank-you h1{color:#eff7f5;font-size:82px;letter-spacing:-1.5px;margin:0;}
  section.cover .cover-grid{grid-template-columns:340px 1fr;gap:24px;height:560px;}
  section.cover h1{font-size:56px;letter-spacing:-1.3px;}
  section.cover .subtitle{font-size:24px;}
  section.cover .names{font-size:22px;}
  .cover-gallery{display:grid;grid-template-columns:1fr 1fr;gap:14px 16px;align-items:start;}
  section.cover .cover-gallery img{height:auto;aspect-ratio:16/9;object-fit:contain;}
  section.cover .cover-gallery figcaption{font-size:18px;margin-top:5px;color:#e4eeec;}
  section.cover .cover-credit{font-size:13px;line-height:1.3;color:#bdd0d2;margin:9px 0 0;}
  section.static-results{padding:24px 44px 34px;}
  section.static-results h2{font-size:37px;margin-bottom:12px;}
  .comparison-grid{max-width:940px;margin:0 auto;display:grid;grid-template-columns:repeat(3,1fr);gap:18px;}
  .comparison-grid h3{text-align:center;font-size:20px;margin:0 0 6px;line-height:1.2;}
  .comparison-grid figure{position:relative;margin-bottom:7px;}
  .comparison-grid img{width:100%;height:auto;aspect-ratio:16/9;}
  .comparison-grid figcaption{position:absolute;left:7px;top:7px;margin:0;font-size:15px;line-height:1.15;padding:3px 6px;color:white;background:#10232ddd;}
  .metric-equation{display:flex;align-items:center;justify-content:center;gap:32px;margin:1px 0 4px;min-height:46px;}
  .metric-equation math{font-family:'Cambria Math',serif;font-size:22px;}
  .metric-equation .metric-key{font-size:15px;line-height:1.35;color:#536a73;}
  section.static-results .metrics{max-width:1000px;margin:3px auto 0;font-size:22px;line-height:1.15;}
  section.static-results .metrics th{font-size:18px;}
  section.static-results .metrics td,section.static-results .metrics th{padding:4px 13px;}
  section.static-results .metrics .cost-value{color:#85542c;font-weight:600;}
  section.static-results .foot{left:44px;bottom:9px;font-size:13px;max-width:1170px;}
  section.indoor-failure h2{font-size:40px;}
  section.indoor-failure .failure-pair img{height:auto;aspect-ratio:16/9;}
  section.indoor-failure .failure-pair figcaption{font-size:20px;}
  .failure-analysis{font-size:26px;line-height:1.4;margin-top:25px;max-width:1120px;}
  @media print{.demo video{display:none}.demo .print-poster{display:block}}
  section.demo-slide{padding:0;background:#101c28;}
  section.demo-slide::before{display:none;}
  section.demo-slide h2{position:absolute;z-index:2;top:14px;left:50%;transform:translateX(-50%);font-size:28px;white-space:nowrap;color:white;background:#10232dd9;padding:9px 15px;border-radius:3px;margin:0;pointer-events:none;}
  section.demo-slide .demo{position:absolute;inset:0;width:100%;height:100%;}
  section.demo-slide .demo-caption{position:absolute;z-index:2;right:24px;bottom:60px;max-width:490px;font-size:17px;color:white;background:#10232ddd;padding:9px 13px;border-radius:3px;margin:0;}
  section.demo-slide .demo-caption a{color:#9cf0db;}
  section.demo-slide .foot{z-index:2;left:32px;bottom:65px;max-width:600px;color:white;background:#10232ddd;padding:7px 10px;font-size:14px;}
---

<!-- _class: cover -->
<!-- _paginate: false -->

<div class="cover-grid"><div>
<h1>ReSTIR<br>Spatial Reuse</h1>
<p class="subtitle">Implementation and evaluation</p>
<p>Project progress</p>
<p class="names">Group 7<br>Luoyi Zhang · Zelin Gao</p>
</div><div><div class="cover-gallery"><figure><img src="../assets/results/cornell-static-reference-frame-0128.png" alt="Cornell Box reference"><figcaption>Cornell Box</figcaption></figure><figure><img src="../assets/results/arcade-static-reference-frame-0128.png" alt="Arcade reference"><figcaption>Arcade</figcaption></figure><figure><img src="../assets/results/bistro-interior-static-reference-frame-0128.png" alt="Bistro interior reference"><figcaption>Bistro interior</figcaption></figure><figure><img src="../assets/results/bistro-exterior-static-reference-frame-0128.png" alt="Bistro exterior reference"><figcaption>Bistro exterior</figcaption></figure></div><p class="cover-credit">Cornell / Arcade: NVIDIA RTXDI Assets<br>Bistro: Amazon Lumberyard / NVIDIA ORCA · CC BY 4.0</p></div></div>
<p class="foot">COMP5411 · 24 October 2026</p>


<!--
0:00 to 0:20 | rehearsal target

Hi, we're Group Seven. Our project studies Reservoir-based Spatiotemporal Importance Resampling, or ReSTIR for short. This is an evaluation study focused on spatial reuse: how choosing neighboring pixels affects image quality and GPU cost.

Cue: Aim for 3:30 overall. Say the full name of ReSTIR, then explain the focus on spatial reuse. Finish this slide by 0:20.
-->

---

## Spatial reuse across different surfaces

<div class="two text-image"><div>
<h3>Reuse a small light-sample reservoir</h3>
<p>Nearby pixels and earlier frames supply candidate samples.</p>
<h3 style="margin-top:28px">Compatibility can change</h3>
<p>Materials, surface directions and visibility affect whether a neighbor helps.</p>
</div><figure><img class="" src="../assets/results/cornell-static-reference-frame-0128.png" alt="Cornell · RTXDI Assets"><figcaption>Cornell · RTXDI Assets</figcaption></figure></div>
<p class="foot">The project studies direct lighting and the cost of more selective reuse.</p>


<!--
0:20 to 0:42 | rehearsal target

At each pixel, ReSTIR keeps a selected light sample and its weight. It reuses samples from nearby pixels and previous frames. This works well when their lighting needs are similar. Materials, surface orientations, and visibility all affect whether those samples are useful.

Cue: Use the Cornell image to explain which neighbors may help. Leave other reservoir state details for later.
-->

---

## Three methods in one renderer

<table class="method-table"><thead><tr><th>Method</th><th>Spatial reuse</th><th>Progress</th></tr></thead><tbody>
<tr><td>ReSTIR DI</td><td>Reuse neighboring reservoirs with geometric checks</td><td>Baseline evaluated</td></tr>
<tr><td>PDF Similarity</td><td>Reduce reuse when estimated target distributions differ</td><td>RTXDI adaptation evaluated</td></tr>
<tr><td>CGNS</td><td>Sample neighbors using geometric compatibility</td><td>Next implementation</td></tr>
</tbody></table>
<p class="lead">Evaluate each extension against the same direct-lighting baseline.</p>
<p class="foot">PDF Similarity is our RTXDI adaptation. It is not an exact reproduction of the original renderer.</p>


<!--
0:42 to 1:05 | rehearsal target

We use ReSTIR DI, the direct-lighting version, as our baseline. We've adapted PDF Similarity to RTXDI, the toolkit we're using. Next, we'll implement Compatibility-Guided Neighbor Selection, or CGNS. We compare methods using image error and GPU cost.

Cue: Distinguish the completed PDF Similarity adaptation from the next step, CGNS. Finish the first three recap slides by 1:05.
-->

---

<!-- _class: pdf-method -->

## PDF Similarity: compare lighting directions

<p class="lead">Reduce spatial reuse when the target distributions differ.</p>
<img class="pdf-figure" src="../assets/papers/pdf-similarity-figure-2.png" alt="Tokuyoshi Figure 2: lit and shadowed pixels have different directional target PDFs; smooth vMF lobes approximate these distributions.">
<div class="pdf-explanation"><div><h3>(a) Nearby pixels can need different samples</h3><p>Shadows change which light directions contribute.</p></div><div><h3>(b) Approximate each PDF with a smooth lobe</h3><p>Compare its direction and sharpness to guide reuse.</p></div></div>
<p class="foot">Figure 2 reproduced from Y. Tokuyoshi (2023), <a href="https://doi.org/10.1145/3585501">Efficient Spatial Resampling Using the PDF Similarity</a>.<br>vMF = von Mises–Fisher distribution. Our implementation adapts this idea to RTXDI.</p>

<!--
1:05 to 1:31 | rehearsal target

PDF Similarity compares lighting directions. Across a shadow boundary, nearby pixels can need different light samples. Geometry checks alone cannot fully capture this difference. The method approximates each target distribution with a smooth directional lobe, then compares the lobes' directions and widths to guide reuse.

Cue: Point to the lit and shadowed pixels, then the directional lobes in the paper figure. Geometry checks cannot fully capture visibility differences. Avoid implying that ReSTIR DI ignores visibility entirely.
-->

---

## Programming completed

<div class="codework">
<div><h3>Renderer integration</h3><p>ReSTIR DI controls and PDF similarity logic in RTXDI's spatial pass</p></div>
<div><h3>History and weights</h3><p>Directional history, reset behavior, and reservoir-weight checks</p></div>
<div><h3>Run experiments</h3><p>Replay camera and lighting changes; save HDR images and GPU timings.</p></div>
<div><h3>Compare results</h3><p>Compare three seeds and generate error maps and summary tables.</p></div>
</div>
<p class="foot">Completed PDF evaluation: 78 method runs · 8 main conditions · 3 seeds · 1080p</p>


<!--
1:31 to 1:49 | rehearsal target

So far, we've integrated PDF Similarity into RTXDI. Our experiment tools replay camera and lighting changes, save HDR images and GPU timings, and compare results across three random seeds.

Cue: Briefly describe the completed integration and experiment tools without reading each item on the slide.
-->

---

<!-- _class: demo-slide -->
<!-- _paginate: false -->

## Working implementation

<div class="demo"><video controls loop muted playsinline preload="metadata" poster="../assets/results/bistro-exterior-motion-comparison.png" src="../assets/videos/bistro-exterior-motion/comparison.mp4"></video><img class="print-poster" src="../assets/results/bistro-exterior-motion-comparison.png" alt="Bistro exterior, matched frame 48. PDF on left and PDF off right of the diagonal divider."></div>
<p class="demo-caption">PDF on, left · PDF off, right · 96 matched frames<br><a href="../comparison.html?scene=bistro-exterior-motion#sequences" target="_blank">Open draggable comparison</a></p>
<p class="foot">Saved seed-1 output · 1080p · 30 FPS playback · GPU performance measured separately</p>

<!--
1:49 to 2:17 | rehearsal target

This is the Bistro exterior sequence, with PDF Similarity on the left and the baseline on the right. Look near shadow boundaries and across large surfaces. We see less noise in parts of the image, and lower temporal error at the selected frame pairs.

Cue: Play the Bistro exterior comparison and point to shadow boundaries and large surfaces. Allow about 4 seconds for observation. Limit the claims to local appearance and temporal error at the selected frame pairs; do not extend them to the whole sequence.
-->

---

<!-- _class: static-results -->

## Lower static error with extra GPU cost

<div class="comparison-grid"><div><h3>Cornell Box</h3><figure><img src="../assets/results/cornell-static-pdf-off-frame-0128.png" alt="Cornell Box, PDF off, frame 128"><figcaption>PDF off</figcaption></figure><figure><img src="../assets/results/cornell-static-pdf-on-frame-0128.png" alt="Cornell Box, PDF on, frame 128"><figcaption>PDF on</figcaption></figure></div><div><h3>Arcade</h3><figure><img src="../assets/results/arcade-static-pdf-off-frame-0128.png" alt="Arcade, PDF off, frame 128"><figcaption>PDF off</figcaption></figure><figure><img src="../assets/results/arcade-static-pdf-on-frame-0128.png" alt="Arcade, PDF on, frame 128"><figcaption>PDF on</figcaption></figure></div><div><h3>Bistro exterior</h3><figure><img src="../assets/results/bistro-exterior-static-pdf-off-frame-0128.png" alt="Bistro exterior, PDF off, frame 128"><figcaption>PDF off</figcaption></figure><figure><img src="../assets/results/bistro-exterior-static-pdf-on-frame-0128.png" alt="Bistro exterior, PDF on, frame 128"><figcaption>PDF on</figcaption></figure></div></div>
<div class="metric-equation"><math xmlns="http://www.w3.org/1998/Math/MathML" display="inline" aria-label="SMAPE percent equals 100 over N times the sum over pixels of absolute Y minus R divided by absolute Y plus absolute R plus ten to the minus four"><mtext>SMAPE (%)</mtext><mo>=</mo><mfrac><mn>100</mn><mi>N</mi></mfrac><munderover><mo>∑</mo><mrow><mi>p</mi><mo>=</mo><mn>1</mn></mrow><mi>N</mi></munderover><mfrac><mrow><mo>|</mo><msub><mi>Y</mi><mi>p</mi></msub><mo>−</mo><msub><mi>R</mi><mi>p</mi></msub><mo>|</mo></mrow><mrow><mo>|</mo><msub><mi>Y</mi><mi>p</mi></msub><mo>|</mo><mo>+</mo><mo>|</mo><msub><mi>R</mi><mi>p</mi></msub><mo>|</mo><mo>+</mo><msup><mn>10</mn><mrow><mo>−</mo><mn>4</mn></mrow></msup></mrow></mfrac></math><span class="metric-key">Y: rendered linear luminance<br>R: reference luminance · N: pixels</span></div>
<table class="metrics"><thead><tr><th>Scene</th><th>SMAPE % · off → on</th><th>GPU ms · off → on</th></tr></thead><tbody><tr><td>Cornell Box</td><td>7.98 → <strong>6.89</strong></td><td>8.90 → <span class="cost-value">9.60</span></td></tr><tr><td>Arcade</td><td>17.04 → <strong>14.99</strong></td><td>13.78 → <span class="cost-value">15.65</span></td></tr><tr><td>Bistro exterior</td><td>42.24 → <strong>34.48</strong></td><td>27.62 → <span class="cost-value">32.36</span></td></tr></tbody></table>
<p class="foot">Images: seed 1 · Three-seed means · Frame 128</p>

<!--
2:17 to 2:38 | rehearsal target

In these three static views, PDF Similarity lowers SMAPE at an additional GPU cost. SMAPE compares rendered luminance with the reference, normalized by their combined brightness.

Cue: Point briefly to the formula, then the table. Lower SMAPE is better. The quality improvement comes with higher GPU time; this does not establish an equal-time advantage.
-->

---

<!-- _class: indoor-failure -->

## PDF Similarity can regress indoors

<div class="failure-pair"><figure><img class="" src="../assets/results/bistro-interior-static-spatial-only-pdf-off-frame-0128.png" alt="Spatial only · PDF off · SMAPE 72.17%"><figcaption>Spatial only · PDF off · SMAPE 72.17%</figcaption></figure><figure><img class="" src="../assets/results/bistro-interior-static-spatial-only-pdf-on-frame-0128.png" alt="Spatial only · PDF on · SMAPE 73.08%"><figcaption>Spatial only · PDF on · SMAPE 73.08%</figcaption></figure></div>
<p class="failure-analysis">In this spatial-only test, enabling PDF Similarity increases error. Complex visibility patterns may be difficult to represent with one directional lobe. We have not yet isolated the cause.</p>
<p class="foot">Bistro: Amazon Lumberyard / NVIDIA ORCA · CC BY 4.0</p>


<!--
2:38 to 3:00 | rehearsal target

The indoor spatial-only test gets worse with PDF Similarity enabled. Complex surfaces and occlusion may make neighboring pixels need different samples, which a single directional lobe may not distinguish well. That's one possible explanation; we haven't isolated the cause yet.

Cue: Identify this as a spatial-only test. A single directional lobe is still only a possible explanation for the failure. Complex geometry and occlusion are not confirmed causes.
-->

---

<!-- _class: new-scenes -->

## Six additional scenes

<p class="lead">Broader coverage of geometry, materials and lighting</p>
<div class="scene-grid"><figure><img class="" src="../assets/scenes/classroom.png" alt="Classroom — Indoor clutter"><figcaption><span class="scene-name">Classroom</span><span class="scene-desc">Indoor clutter</span></figcaption></figure><figure><img class="" src="../assets/scenes/emerald-square.png" alt="Emerald Square — Urban lighting"><figcaption><span class="scene-name">Emerald Square</span><span class="scene-desc">Urban lighting</span></figcaption></figure><figure><img class="" src="../assets/scenes/san-miguel.png" alt="San Miguel — Foliage and detail"><figcaption><span class="scene-name">San Miguel</span><span class="scene-desc">Foliage and detail</span></figcaption></figure><figure><img class="" src="../assets/scenes/sun-temple.png" alt="Sun Temple — Architectural shadows"><figcaption><span class="scene-name">Sun Temple</span><span class="scene-desc">Architectural shadows</span></figcaption></figure><figure><img class="" src="../assets/scenes/veach-ajar.png" alt="Veach Ajar — Contrasting materials"><figcaption><span class="scene-name">Veach Ajar</span><span class="scene-desc">Contrasting materials</span></figcaption></figure><figure><img class="" src="../assets/scenes/zero-day-measure-one.png" alt="Zero-Day — Emissive machinery"><figcaption><span class="scene-name">Zero-Day</span><span class="scene-desc">Emissive machinery</span></figcaption></figure></div>
<p class="foot">Assets: C. Seux / Blender · NVIDIA · G. M. Leal Llaguno · Epic Games · B. Bitterli · Beeple</p>


<!--
3:00 to 3:12 | rehearsal target

We've also configured six additional scenes with more varied geometry, materials, and lighting. They give us a broader range of settings for future experiments.

Cue: Briefly show the six scene images and explain that they are for later experiments. There is no need to read every name.
-->

---

<!-- _class: closing -->

## Remaining programming and evaluation

<ul>
<li><strong>Adapt CGNS</strong> and verify its sampling probabilities and reservoir weights.</li>
<li><strong>Find and diagnose failure cases</strong> through controlled tests of geometry, visibility, and lighting.</li>
</ul>
<p class="foot">PDF sparse evaluation complete. The broader three-method study continues.</p>


<!--
3:12 to 3:26 | rehearsal target

Next, we'll integrate CGNS into our codebase. We'll also vary geometry, visibility, and lighting in controlled tests to find more failure cases and identify their causes.

Cue: Explain the two tasks: implementing CGNS and designing controlled tests. Save the closing thanks for the next slide.
-->

---

<!-- _class: closing thank-you -->
<!-- _paginate: false -->

# Thank you

<!--
3:26 to 3:30 | rehearsal target

That's all from Group Seven. Thank you.

Cue: Switch to the Thank you slide and close briefly. Finish around 3:30.
-->
