# Report writing guide

## Starting files

`writing/course/report/main.tex` is the working copy of the supplied course template, not a drafted report. Replace Group X / Student A / Student B with Group7 / Luoyi Zhang / Zelin Gao, then write the paper. Preserve the original course formatting in `writing/course/templates/report.tex`. The existing bibliography is `writing/references.bib`; check that all cited works, including GRIS/ReSTIR PT, are present before compiling. Method details are in `docs/reproductions/falcor-pdf-pt.md`, `falcor-cgns-pt.md` and `pt-6-views-spatial-compare.md`. Use THIRD_PARTY.md for assets/licenses and the appendix for resource attribution.

## Suggested evidence order

1. Motivation and earlier RTXDI DI checkpoint; final focus on Falcor ReSTIR PT.
2. Ordinary reuse, first-hop contribution/history/effective-M PDF adaptation, geometry-guided cached CGNS. Explain preserved native path shifts, Jacobians, visibility and reservoir normalization. Distinguish author algorithms, author code and our adaptations.
3. Shared fixed-view protocol: six scenes, matched cameras/transport/seeds, temporalon, 1spp,40warmup, four seeds×16frames; finite16384spp references. Ordinary temporaloff is the control.
4. SMAPE and GPU timing; then temporal/spatial covariance; then whole-scene and local failures. Use full report tables, not rounded slide labels, when computing new numbers.
5. Qualitative moving-camera demos and remaining correlation/visibility challenges.
6. Scoped conclusions, limitations and next steps.

## Defensible findings

- CGNS reduces scene-mean SMAPE in6/6views by3.93–22.75%; adds3.95–5.92% GPU frame time in five eligible timing views.
- PDF relative SMAPE reductions range from−5.63% to+2.09%; its measured overhead is8.16–26.93%. It does not beat CGNS on mean SMAPE in any of the six views or timing in any of the five eligible views.
- Emerald shows the largest CGNS gain and PDF regression; do not attach a timing conclusion to Emerald.
- CGNS temporal covariance decreases8.8–40.4%, while spatial covariance increases1.7–24.9% in the scene-wide estimates. Local ROI trends can differ.
- Classroom improves7.53% overall under CGNS, but blackboard stripB increases10.932→11.340% SMAPE. RegionA was selected for observed gain; B by reference structure/material contrast.
- Ordinary temporalon reduces SMAPE56.6–82.6% compared with the retained temporaloff control in this captured window.

Do not claim general superiority, equal-time superiority, a proof of unbiasedness, or a diagnosed cause of the PDF regression. The PDF first-hop directional marginal, decayed temporal statistics and effective-M integration are project adaptations of a single-bounce method. One directional lobe may lose multi-lobe information; history may lag changes. CGNS is our Fast-inspired point-reservoir adaptation, not the paper's full area-reservoir/splatting setup. Geometric compatibility does not guarantee visibility or transport compatibility.

## Papers supplied for private group work

Bitterli2020 (original ReSTIR); Lin2022 (GRIS/ReSTIR PT); Tokuyoshi2023 (PDF Similarity); Junkins2026 (CGNS). PDFs and credits are retained under assets/papers and THIRD_PARTY.md. Do not remove notices or imply all source PDFs have an open redistribution license.
