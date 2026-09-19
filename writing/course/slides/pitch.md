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
---

<!-- _class: cover -->
<!-- _paginate: false -->

# ReSTIR Spatial Reuse

<p class="subtitle">Implementation and Evaluation</p>

<p class="names">Group 7<br>Luoyi Zhang · Zelin Gao</p>

<img class="hero" src="assets/bistro-exterior.png" alt="Amazon Lumberyard Bistro exterior, a candidate test scene">
<p class="credit">Bistro scene illustration · Amazon Lumberyard / ORCA<br>CC BY 4.0 · cropped to fit</p>
<p class="bottom">COMP5411 · Fall 2026 · Project proposal</p>

<!--
00:00–00:15 · 15 seconds. Keep the title, group ID, and names visible for at least 3 seconds.

Hello, we are Group Seven, Luoyi Zhang and Zelin Gao. Our project is ReSTIR Spatial Reuse: Implementation and Evaluation. We plan to study how choosing neighboring samples affects real-time rendering quality.

Visual source: Amazon Lumberyard Bistro, ORCA (2017), https://developer.nvidia.com/orca/amazon-lumberyard-bistro. CC BY 4.0. This is a source illustration, not a project render.
-->

---

## ReSTIR reuses light samples

<p class="subtitle">Across neighboring pixels and previous frames</p>

<img class="wide-figure" src="assets/cgns-comparison.png" alt="CGNS paper Figure 1: path tracing, ReSTIR, CGNS, and reference image comparisons">
<p class="credit">Junkins et al., 2026, Fig. 1 · CC BY 4.0 · “Ours” means the paper authors’ method</p>

<p class="bottom"><strong>Our question:</strong> Which neighbors provide useful samples?</p>

<!--
00:15–00:45 · 30 seconds.

Rendering a scene with many lights is expensive because each pixel can test only a few samples per frame. ReSTIR keeps a representative light sample with weights, then reuses samples across pixels and frames. But nearby pixels can have different materials, visibility, or lighting. This published comparison illustrates the effect of neighbor selection. These are the authors' results; our project asks when better spatial reuse helps under the same rendering budget.

Sources: Bitterli et al. (2020), https://research.nvidia.com/labs/rtr/publication/bitterli2020spatiotemporal/; Junkins et al. (2026), https://doi.org/10.1145/3820024, Figure 1. Figure rendered from the paper with margins/caption removed; comparison labels and measurements preserved. Copyright the authors, CC BY 4.0. No performance result is claimed for our implementation.
-->

---

## Three methods on one shared baseline

| Method | What we will implement or adapt |
| :--- | :--- |
| **ReSTIR DI** · 2020 | Reservoir sampling, temporal reuse, and spatial reuse |
| **PDF Similarity** · 2023 | Estimate sampling distributions; reject unsuitable reuse |
| **CGNS** · 2026 | Score compatibility; sample neighbors with those weights |

<p class="subtitle">Compare each extension separately against ReSTIR DI</p>
<p class="bottom">Shared direct lighting, scenes, and rendering budget</p>

<!--
00:45–01:20 · 35 seconds.

We selected three works with increasing sophistication. The original ReSTIR DI provides our baseline. PDF Similarity estimates sampling distributions and rejects spatial reuse when those distributions differ too much. Compatibility-Guided Neighbor Selection, or CGNS, scores candidate neighbors and samples them according to compatibility. We will compare each extension separately against the same DI baseline. Combining both extensions is optional, so the main project stays focused. These are planned reproductions, not a claim that we have already implemented them.

Sources: Bitterli et al. (2020), DOI 10.1145/3386569.3392481; Tokuyoshi (2023), DOI 10.1145/3585501; Junkins et al. (2026), DOI 10.1145/3820024. Full entries: ../../references.bib. PDF Similarity includes temporal safeguards; CGNS transfer from the authors' path tracer to DI must be validated.
-->

---

## Implementation and technical challenges

<div class="columns">
<div>
<h3>Existing renderer</h3>
<p>RTXDI preferred<br>Scene loading, materials, ray tracing, display</p>
<h3>Our contribution</h3>
<p>Core algorithm implementations or ports, diagnostic controls, and repeatable comparisons</p>
</div>
<div>
<h3>Correct weights</h3>
<p>Reuse must preserve the intended lighting estimate</p>
<h3>Reliable adaptation</h3>
<p>Validate PDF estimates, temporal safeguards, and CGNS in DI</p>
<h3>Fair timing</h3>
<p>Include neighbor-selection overhead</p>
</div>
</div>

<p class="bottom">Falcor author code is a reference; we maintain one primary backend</p>

<!--
01:20–01:55 · 35 seconds.

We will reuse an existing renderer for scene loading, materials, ray tracing, and display. RTXDI is our preferred backend, with Falcor author code as a reference. Our work is implementing or adapting the selected algorithms and building diagnostic and evaluation tools. The hardest parts are getting reservoir weights correct, making distribution estimates reliable during motion, and validating CGNS in direct lighting. We must also include the extra selection cost when comparing performance. We will document upstream code and our changes.

Sources: project proposal and scope; NVIDIA RTXDI, https://github.com/NVIDIA-RTX/RTXDI; CGNS author code, https://github.com/orion-junkins/ReSTIR-CGNS. Backend and exact revision remain provisional until the feasibility check.
-->

---

## Quality, cost, and behavior over time

<div class="evaluation">
<div>
<img src="assets/cgns-temporal.png" alt="CGNS paper Figure 5: pixel strips over time showing temporal correlation in ReSTIR variants">
<p class="credit">Published temporal-correlation illustration<br>Junkins et al., 2026, Fig. 5 · CC BY 4.0<br>Each row is a frame; vertical streaks show correlation<br>“Ours” refers to the authors’ method</p>
</div>
<div>
<h3>Shared test scenes</h3>
<p>Cornell Box · Bistro · Arcade</p>
<h3>Matched-time comparisons</h3>
<p>HDR error against a converged reference; GPU frame time</p>
<h3>Static views + camera motion</h3>
<p>Independent seeds; reuse and neighbor-count ablations</p>
</div>
</div>

<p class="bottom">Evaluate before denoising or tone mapping; scene imports remain to be validated</p>

<!--
01:55–02:30 · 35 seconds.

Our initial scene shortlist is Cornell Box, Bistro, and Arcade, starting with the simplest case. We will compare linear HDR output against converged direct-lighting references, measure GPU frame time, and use independent random seeds. Static views test image error; short camera paths test behavior over time. The published figure illustrates why one screenshot is insufficient: vertical streaks reveal persistent errors. We will also disable reuse stages and vary neighbor count to understand which components cause differences.

Sources: project scenes/README.md and experiments/protocol.md; assets https://github.com/NVIDIA-RTX/RTXDI-Assets. Illustration: Junkins et al. (2026), DOI 10.1145/3820024, Figure 5, Veach Ajar scene. The pictured author experiment is not our shortlisted scene suite or our own result. Cropped from PDF to preserve the complete figure, without its caption. CC BY 4.0. Our temporal metric definitions will be fixed before experiments.
-->

---

<!-- _class: schedule -->

## A provisional ten-week plan

| Weeks | Main milestone |
| :--- | :--- |
| **1–2** | Proposal, backend build, and feasibility check |
| **3–5** | ReSTIR DI baseline and PDF Similarity |
| **6–8** | CGNS integration, diagnostics, and demo |
| **9–10** | Evaluation, report, and reproduction check |

<p class="bottom">Check feasibility early; reduce optional experiments if time becomes tight</p>

<!--
02:30–02:55 · 25 seconds.

The plan spans ten provisional weeks. We will first confirm that the backend builds and that the extensions fit. Then we develop the baseline and PDF Similarity, followed by CGNS and integration. The final weeks are reserved for experiments and writing. We will split implementation and evaluation work, review each other's code, and reduce optional experiments if necessary.

Source: docs/roadmap.md. Week numbers are planning assumptions, not confirmed course milestones. Detailed task status lives in https://github.com/users/TheLogarhythm/projects/1.
-->

---

<!-- _class: closing -->

## A reusable starting point for ReSTIR research

<p class="outcome"><strong>Three selectable methods</strong><br>on one documented rendering pipeline</p>

<p class="outcome"><strong>Repeatable comparisons</strong><br>with evidence of strengths and limitations</p>

<p class="bottom">Code, configurations, and report<br><a href="https://github.com/TheLogarhythm/restir-lab">github.com/TheLogarhythm/restir-lab</a></p>

<!--
02:55–03:15 · 20 seconds.

Our deliverable is three selectable methods on one documented pipeline, together with repeatable comparisons and a report explaining strengths and limitations. Beyond the course, this repository should help us identify concrete research questions from measured failure cases. We are aiming for a reliable foundation, rather than promising a new algorithm. Thank you.

Source: project proposal and scope. These are planned deliverables; implementation and experiments have not yet begun.
-->
