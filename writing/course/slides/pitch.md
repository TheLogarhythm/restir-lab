---
marp: true
theme: default
size: 16:9
paginate: true
title: "ReSTIR Spatial Reuse: Implementation and Evaluation"
author: "Luoyi Zhang and Zelin Gao"
description: "COMP5411 Group 7 — project proposal pitch draft"
style: |
  section {
    background: #f7f8f6;
    color: #182c38;
    font-family: 'Segoe UI', Arial, sans-serif;
    font-size: 28px;
    padding: 52px 66px 160px;
    display: block;
    line-height: 1.32;
  }
  section::before { content: ''; position: absolute; left: 0; top: 0; width: 12px; height: 100%; background: #16847e; }
  section::after { top: 28px; right: 36px; bottom: auto; color: #70868c; font-size: 17px; }
  section h1 { font-size: 55px; line-height: 1.08; letter-spacing: -1.5px; color: #182c38; margin: 0 0 22px; }
  section h2 { font-size: 43px; line-height: 1.12; letter-spacing: -0.8px; color: #182c38; margin: 0 0 24px; }
  h3 { color: #16847e; font-size: 28px; margin: 0 0 10px; }
  p { margin: 0 0 20px; }
  strong { color: #08716c; }
  a { color: #08716c; }
  .subtitle { font-size: 29px; color: #506570; }
  .credit { font-size: 15px; line-height: 1.3; color: #536771; margin-top: 6px; }
  .bottom { position: absolute; left: 66px; bottom: 50px; width: 890px; font-size: 24px; }
  section[data-class="cover"] { background: #142b37; color: #f4f6f3; padding-top: 76px; }
  section[data-class="cover"] h1 { color: #f4f6f3; width: 650px; font-size: 57px; }
  section[data-class="cover"] .subtitle { color: #9cddd4; font-size: 32px; width: 610px; }
  section[data-class="cover"] .names { font-size: 25px; margin-top: 50px; line-height: 1.65; }
  section[data-class="cover"] .hero { position: absolute; right: 0; top: 0; width: 475px; height: 540px; object-fit: cover; object-position: 46% center; }
  section[data-class="cover"] .credit { position: absolute; right: 28px; top: 548px; width: 440px; color: #bdccc9; }
  section[data-class="cover"] .bottom { color: #b7c7c9; font-size: 20px; }
  .wide-figure { display: block; width: 1065px; height: 365px; object-fit: contain; background: #fff; margin: 0; }
  .columns { display: grid; grid-template-columns: 1fr 1fr; gap: 65px; }
  .columns p { font-size: 27px; }
  .columns h3:not(:first-child) { margin-top: 28px; }
  table { display: table; width: 100%; border-collapse: collapse; font-size: 27px; margin: 12px 0 24px; }
  th { background: #e5edeb; color: #304e59; text-align: left; font-size: 22px; font-weight: 600; }
  td, th { border: none; border-bottom: 1px solid #cbd8d7; padding: 18px 16px; }
  tr { background: transparent !important; }
  td:first-child { width: 360px; font-weight: 600; }
  .evaluation { display: grid; grid-template-columns: 540px 1fr; gap: 46px; align-items: start; }
  .evaluation img { display: block; width: 540px; height: 300px; object-fit: contain; background: #fff; }
  .evaluation p { font-size: 26px; }
  .evaluation .credit { font-size: 15px; }
  section[data-class="schedule"] table { font-size: 26px; }
  section[data-class="schedule"] td { padding: 16px; }
  section[data-class="schedule"] td:first-child { width: 150px; color: #08716c; }
  section[data-class="closing"] { background: #142b37; color: #f4f6f3; }
  section[data-class="closing"] h2 { color: #f4f6f3; width: 1000px; font-size: 49px; }
  section[data-class="closing"] strong, section[data-class="closing"] a { color: #9cddd4; }
  section[data-class="closing"] .outcome { font-size: 35px; margin: 35px 0; }
  section[data-class="closing"] .bottom { font-size: 23px; }
  /* Revised copy: the narration is visible in complete bullet points. */
  section h2 { margin-bottom: 33px; }
  section ul { padding-left: 29px; margin: 0; }
  section li { padding-left: 5px; margin: 0 0 22px; line-height: 1.4; }
  section li::marker { color: #16847e; }
  section .footer { position: absolute; left: 66px; bottom: 47px; width: 900px; font-size: 20px; color: #536771; }
  section.cover { background: #142b37; color: #f4f6f3; padding-top: 74px; }
  section.cover h1 { color: #f4f6f3; width: 670px; font-size: 57px; }
  section.cover .subtitle { color: #9cddd4; font-size: 32px; width: 610px; }
  section.cover .names { font-size: 25px; margin: 40px 0 26px; line-height: 1.6; }
  section.cover .intro { width: 620px; font-size: 27px; line-height: 1.45; margin: 0; }
  section.cover .hero { position: absolute; right: 0; top: 0; width: 475px; height: 540px; object-fit: cover; object-position: 46% center; }
  section.cover .credit { position: absolute; right: 28px; top: 548px; width: 440px; color: #bdccc9; }
  section.cover .footer { color: #b7c7c9; }
  .explanation { display: grid; grid-template-columns: 510px 1fr; gap: 38px; align-items: start; }
  .explanation ul { font-size: 27px; line-height: 1.35; }
  .explanation li { margin-bottom: 18px; }
  .figure { padding-top: 18px; }
  .figure img { width: 100%; display: block; object-fit: contain; background: #fff; }
  section.eval .explanation { grid-template-columns: 595px 1fr; gap: 38px; }
  section.eval .figure { padding-top: 28px; }
  section.closing { background: #142b37; color: #f4f6f3; }
  section.closing h2 { color: #f4f6f3; font-size: 43px; }
  section.closing ul { font-size: 32px; line-height: 1.45; max-width: 1060px; }
  section.closing li { margin-bottom: 28px; }
  section.closing li::marker, section.closing strong, section.closing a { color: #9cddd4; }
  section.closing .footer { color: #b7c7c9; }
  section.challenges ul { font-size: 26px; }
  section.challenges li { line-height: 1.35; margin-bottom: 16px; }
---

<!-- _class: cover -->
<!-- _paginate: false -->

# ReSTIR Spatial Reuse

<p class="subtitle">Implementation and Evaluation</p>
<p class="names">Group 7<br>Luoyi Zhang · Zelin Gao</p>
<p class="intro">We&#x27;ll study how ReSTIR reuses samples from nearby pixels, and compare three methods in the same renderer.</p>
<img class="hero" src="assets/bistro-exterior.png" alt="Bistro exterior, a candidate test scene">
<p class="credit">Bistro · Amazon Lumberyard / ORCA<br>CC BY 4.0 · cropped to fit</p>
<p class="footer">COMP5411 · Fall 2026 · Project proposal</p>

<!--
00:00–00:18 · rehearsal target; read the visible text in order.

We're Group Seven, Luoyi Zhang and Zelin Gao. Our project is ReSTIR Spatial Reuse: Implementation and Evaluation.

We'll study how ReSTIR reuses samples from nearby pixels, and compare three methods in the same renderer.

Visual source: Amazon Lumberyard Bistro, ORCA (2017), https://developer.nvidia.com/orca/amazon-lumberyard-bistro. CC BY 4.0. This is a source illustration, not a project render.
-->

---

## Why neighbor selection matters

<div class="explanation">
<ul>
<li>With many lights, testing every light at every pixel is too expensive.</li>
<li>ReSTIR reuses samples from nearby pixels and previous frames to make better use of a small sampling budget.</li>
<li>Nearby pixels can lie on different surfaces or opposite sides of a shadow, so their samples may be less useful.</li>
<li>Our question is: which neighbors should we reuse to improve image quality at the same rendering cost?</li>
</ul>
<div class="figure">
<img src="assets/cgns-comparison.png" alt="Published CGNS paper illustration">
<p class="credit">Published comparison, not our results.<br>Junkins et al., 2026, Fig. 1 · CC BY 4.0<br>“Ours” means the authors’ method.</p>
</div>
</div>

<!--
00:18–00:50 · rehearsal target; read the visible text in order.

With many lights, testing every light at every pixel is too expensive.

ReSTIR reuses samples from nearby pixels and previous frames to make better use of a small sampling budget.

Nearby pixels can lie on different surfaces or opposite sides of a shadow, so their samples may be less useful.

Our question is: which neighbors should we reuse to improve image quality at the same rendering cost?

Sources: Bitterli et al. (2020), https://research.nvidia.com/labs/rtr/publication/bitterli2020spatiotemporal/; Junkins et al. (2026), https://doi.org/10.1145/3820024, Figure 1. Figure rendered from the paper with margins/caption removed; comparison labels and measurements preserved. Copyright the authors, CC BY 4.0. No performance result is claimed for our implementation.
-->

---

## The three methods

<ul>
<li><strong>ReSTIR DI (2020):</strong> we&#x27;ll build the baseline with reservoir sampling and reuse across pixels and frames.</li>
<li><strong>PDF Similarity (2023):</strong> we&#x27;ll estimate sampling distributions and reject reuse between pixels whose distributions are too different.</li>
<li><strong>CGNS (2026):</strong> we&#x27;ll score neighbors by geometric compatibility, then choose them randomly using those scores as weights.</li>
<li>We&#x27;ll compare each extension separately against the baseline, keeping direct lighting, scenes, and other sampling settings consistent.</li>
</ul>

<!--
00:50–01:23 · rehearsal target; read the visible text in order.

ReSTIR DI (2020): we'll build the baseline with reservoir sampling and reuse across pixels and frames.

PDF Similarity (2023): we'll estimate sampling distributions and reject reuse between pixels whose distributions are too different.

CGNS (2026): we'll score neighbors by geometric compatibility, then choose them randomly using those scores as weights.

We'll compare each extension separately against the baseline, keeping direct lighting, scenes, and other sampling settings consistent.

Sources: Bitterli et al. (2020), DOI 10.1145/3386569.3392481; Tokuyoshi (2023), DOI 10.1145/3585501; Junkins et al. (2026), DOI 10.1145/3820024. Full entries: ../../references.bib. PDF Similarity includes temporal safeguards; CGNS transfer from the authors' path tracer to DI must be validated.
-->

---

<!-- _class: challenges -->

## Implementation and technical challenges

<ul>
<li>We&#x27;ll build on the RTXDI sample and use the authors&#x27; Falcor code as a reference.</li>
<li><strong>Correct sample weights:</strong> We must evaluate reused samples at the receiving pixel and handle reservoir normalization and visibility consistently. We&#x27;ll check brightness against a converged reference.</li>
<li><strong>Stable PDF estimates:</strong> PDF Similarity estimates distributions from limited samples. We&#x27;ll test its rejection decisions near shadow edges and reset invalid history when camera motion reveals new surfaces.</li>
<li><strong>Adapting CGNS:</strong> We must transfer weighted neighbor selection from the authors&#x27; path tracer to direct lighting, checking which compatibility terms and estimator assumptions still apply.</li>
<li><strong>Quality versus cost:</strong> Lower image error can still leave persistent noise. We&#x27;ll measure temporal behavior and include neighbor scoring and extra memory accesses in GPU timings.</li>
</ul>

<!--
01:23–02:10 · rehearsal target; read the visible text in order.

We'll build on the RTXDI sample and use the authors' Falcor code as a reference.

Correct sample weights: We must evaluate reused samples at the receiving pixel and handle reservoir normalization and visibility consistently. We'll check brightness against a converged reference.

Stable PDF estimates: PDF Similarity estimates distributions from limited samples. We'll test its rejection decisions near shadow edges and reset invalid history when camera motion reveals new surfaces.

Adapting CGNS: We must transfer weighted neighbor selection from the authors' path tracer to direct lighting, checking which compatibility terms and estimator assumptions still apply.

Quality versus cost: Lower image error can still leave persistent noise. We'll measure temporal behavior and include neighbor scoring and extra memory accesses in GPU timings.

Sources: project proposal and scope; Bitterli et al. (2020), https://research.nvidia.com/labs/rtr/publication/bitterli2020spatiotemporal/; Tokuyoshi (2023), https://doi.org/10.1145/3585501; Junkins et al. (2026), https://research.nvidia.com/labs/rtr/publication/junkins2026compatibility/; author code, https://github.com/orion-junkins/ReSTIR-CGNS. These are planned validation tasks, not observed implementation failures. Backend and exact revision remain provisional.
-->

---

<!-- _class: eval -->

## How we will evaluate the methods

<div class="explanation">
<ul>
<li>We&#x27;ll use Cornell Box, Bistro, and Arcade, with static views and short camera moves.</li>
<li>We&#x27;ll measure GPU frame time and compare raw HDR images with a high-sample reference, using the same time budget.</li>
<li>We&#x27;ll repeat runs with different random seeds, switch reuse on and off, and vary the number of neighbors.</li>
<li>The paper figure shows errors persisting across frames as vertical streaks. We&#x27;ll look for similar behavior in our results.</li>
</ul>
<div class="figure">
<img src="assets/cgns-temporal.png" alt="Published CGNS paper illustration">
<p class="credit">Each row is a frame.<br>Junkins et al., 2026, Fig. 5 · CC BY 4.0<br>Published Veach Ajar example; “Ours” means the authors’ method.</p>
</div>
</div>

<!--
02:10–02:44 · rehearsal target; read the visible text in order.

We'll use Cornell Box, Bistro, and Arcade, with static views and short camera moves.

We'll measure GPU frame time and compare raw HDR images with a high-sample reference, using the same time budget.

We'll repeat runs with different random seeds, switch reuse on and off, and vary the number of neighbors.

The paper figure shows errors persisting across frames as vertical streaks. We'll look for similar behavior in our results.

Sources: project scenes/README.md and experiments/protocol.md; assets https://github.com/NVIDIA-RTX/RTXDI-Assets. Illustration: Junkins et al. (2026), DOI 10.1145/3820024, Figure 5, Veach Ajar scene. The pictured author experiment is not our shortlisted scene suite or our own result. Cropped from PDF to preserve the complete figure, without its caption. CC BY 4.0. Our temporal metric definitions will be fixed before experiments.
-->

---

## Our provisional schedule

<ul>
<li><strong>Weeks 1–2:</strong> get the renderer running and check that both extensions can fit into it.</li>
<li><strong>Weeks 3–5:</strong> implement ReSTIR DI, check the baseline, and add PDF Similarity.</li>
<li><strong>Weeks 6–8:</strong> integrate CGNS, check correctness and cost, and prepare the demo.</li>
<li><strong>Weeks 9–10:</strong> run the main comparisons and finish the report. We&#x27;ll split the work and review each other&#x27;s code.</li>
</ul>

<!--
02:44–03:12 · rehearsal target; read the visible text in order.

Weeks 1–2: get the renderer running and check that both extensions can fit into it.

Weeks 3–5: implement ReSTIR DI, check the baseline, and add PDF Similarity.

Weeks 6–8: integrate CGNS, check correctness and cost, and prepare the demo.

Weeks 9–10: run the main comparisons and finish the report. We'll split the work and review each other's code.

Source: docs/roadmap.md. Week numbers are planning assumptions, not confirmed course milestones. Detailed task status lives in https://github.com/users/TheLogarhythm/projects/1.
-->

---

<!-- _class: closing -->

## What we plan to deliver

<ul>
<li>We&#x27;ll leave three methods running in one renderer, with documented settings and code that we can extend.</li>
<li>We&#x27;ll provide repeatable tests and a report explaining where each method helps and where it struggles.</li>
</ul>
<p class="footer">Thank you.<br><a href="https://github.com/TheLogarhythm/restir-lab">github.com/TheLogarhythm/restir-lab</a></p>

<!--
03:12–03:28 · rehearsal target; read the visible text in order.

We'll leave three methods running in one renderer, with documented settings and code that we can extend.

We'll provide repeatable tests and a report explaining where each method helps and where it struggles.

Thank you.

Source: project proposal and scope. These are planned deliverables; implementation and experiments have not yet begun.
-->
