# Final presentation

The English final deck keeps the previous Marp source structure and adopts the visual language of the supplied `2023ReSTIR_Course_Preliminaries.pptx`: white content areas, cream title bands, Arial headings, orange/gold emphasis and dark brown footer rules. The cover uses a warm tan field. Conference logos and author identities are not copied. Full-screen demo videos use the matching course layout and retain their recorded GPU timing overlays. The source is editable; generated HTML, PDF, previews and media stay local and ignored by Git.

## Present

Open **`final.html`** in Chrome or Edge, then enter fullscreen. Arrow keys advance slides; native video controls allow pausing. Only the active slide's video plays. Each demo is a synchronized three-method comparison with full views and identical magnified crops. The magenta rectangles identify the crops. Videos retain 1× speed and 30 FPS playback; GPU FPS is a separate recorded measurement.

The main deck has **17 slides** and a **4:40 rehearsal target**. Media starts when its slide opens and plays once. Advance on the rehearsal cues. The two Bistro comparisons run for 14 seconds with two 2-second holds each. Zero Day and Classroom run continuously for 10 seconds. The final NRD montage plays the four complete 10-second routes in sequence.

| Slides | Time | Content |
| --- | --- | --- |
| 1 | 0:00–0:08 | Title |
| 2 | 0:08–0:25 | The Bistro Exterior shadow boundary |
| 3–5 | 0:25–1:12 | Pipeline, PDF Similarity and CGNS |
| 6–10 | 1:12–2:28 | Fixed-view results and GPU cost |
| 11–14 | 2:28–3:34 | Four three-method trajectory comparisons |
| 15 | 3:34–4:17 | Four final renders with CGNS and NRD |
| 16–17 | 4:17–4:40 | Takeaways and thanks |

The separate **`appendix.html`** contains seven backup slides: full quality table, stage costs, covariance, temporal ablation, a local CGNS failure, validation limits and full resources. It is outside the timed presentation. PDF versions in `build/` use static video posters; **use HTML for the demo**, not PDF. The full speaker notes live in the main Markdown, and `build/rehearsal-script.md` extracts the spoken paragraphs and timing cues.

## Sources and structure

- `source/final.md`: main slides, English narration and rehearsal timings.
- `source/appendix.md`: editable backup slides. `tools/build_appendix.py` refreshes only the quality table; it never regenerates the prose.
- `source/theme.css`: the shared Marp theme for both decks. Use `theme: restir-final` and register this file in your editor.
- `source/playback.js`: active-slide video control, without changing playback speed.
- `assets/diagrams/`: generated explanatory SVGs. The separately credited CGNS paper excerpt has provenance in `data/cgns-figure2.json`.
- `assets/figures/`: derived static charts, error maps and scene images. Inputs and processing hashes: `data/figures.json`.
- `assets/videos/` contains four FPS comparisons, the CGNS + NRD montage and their posters. `data/current-media.json` pins the active assets. The `*-course-v2` files and receipts preserve the previous course presentation media.
- `data/`: current asset selection and immutable derivation/source receipts.
- `templates/handoff/`: English handoff documentation and a thin wrapper around the same build entry point used in the repository.
- `tools/`: reproducible build and validation scripts.
- `build/`: generated previews, PDF/PPTX exports, notes and current verification reports; earlier generated checks are retained in `build/verification-history/`.

Numerical evidence and figures come from the consolidated statistics archive `runs/pt-6-views-spatial-compare` (`statistics/`, `data/`, `images/`, and `figures/`). Full method HDR has been retired; the retained tables and maps support figure redesign. The twelve original video files come from `runs/pt-4-trajectories-spatial-compare`. The slide build reads those directories and never renders new GPU experiments or edits historical results. The fixed-view experiment and later motion-support code are distinct versions; the videos are qualitative demonstrations, not new fixed-view measurements.

## Build

From the repository root, with Marp CLI 4.5.1 installed in local `node_modules/` or the existing npm cache, Chrome/Edge, FFmpeg, NumPy, Pillow and Matplotlib installed:

```powershell
# Generate HTML, PDFs, 1920×1080 slide previews and notes from existing media.
.\writing\final\tools\build.ps1 -Python build/falcor/verify-env/Scripts/python.exe -PreviewImages -Pdf

# Optional: export a submission PPTX with embedded current videos (Windows PowerPoint).
.\writing\final\tools\build.ps1 -Python build/falcor/verify-env/Scripts/python.exe -Pptx

# Rebuild figures or media from the immutable sources when needed.
.\writing\final\tools\build.ps1 -Python build/falcor/verify-env/Scripts/python.exe -Figures -Media

# Static asset / timing-plan verification; browser checks use local Chrome.
& build/falcor/verify-env/Scripts/python.exe -B writing/final/tools/verify.py
node writing/final/tools/verify_browser.cjs

# Read-only validation of exactly the videos referenced by the deck.
& build/falcor/verify-env/Scripts/python.exe -B writing/final/tools/build_media.py --check
```

The default build only renders existing sources/assets; it does not rewrite the slide body or regenerate images/videos. `-Figures` refreshes generated figures and the appendix data table. `-Media` uses the current course builder and reuses outputs only when source, recipe and hashes match. The old `build_media_course.py --scene ...` command remains a compatibility wrapper. The build intentionally does not fetch dependencies. Supply `-Marp` for an explicit Marp CLI path, `MARP_CLI_PATH` for browser verification, or install the pinned package locally. Media processing creates presentation copies; it never changes the original 1080p videos. Preserve the `final.html`, `appendix.html`, `source/playback.js` and `assets/` relative layout when copying the presentation to another machine. Online paper links are optional; all slides and embedded videos work offline.

## How the staff feedback is addressed

1. **Subtle differences:** slide 6 uses same-scale signed error-change maps; every demo adds synchronized magnified regions. The three-method clips show pre-denoise images on the same display transform. The final montage shows CGNS followed by NRD.
2. **Judgment and surprises:** slides 6–10 and 16 recommend CGNS for the tested workload, explain the extra cost, expose PDF's Emerald regression and show that temporal/spatial covariance move in opposite directions. The appendix adds a local Classroom regression despite CGNS's whole-scene gain.
3. **Benefits and failure cases:** the report should retain both improvements and regressions, distinguish relative percentages from percentage points, and separate observations from causal hypotheses. The PDF first-hop representation may lose transport information, but the stored images do not diagnose the regression. Do not turn matching-settings results into equal-time superiority or unbiasedness claims.

Scene attributions and method citations appear in appendix A7. The diagrams are project-authored schematics, and all plotted experiment values are project measurements. No published paper results are presented as our own.

Expanded result panels are rebuilt by `tools/build_results_panels.py`; source/output hashes and selection provenance are recorded in `data/results-panels.json`. Local strip scores and illustrative square crops are explicitly distinguished.

## Submission and data handoff

Use `build/final-with-videos.pptx` for PowerPoint submission. Five MP4s are embedded with automatic one-pass playback. Non-video pages preserve Marp layout as full-slide images; edit their content in `source/final.md` and rebuild. This is a presentation copy, not a fully editable native-text PowerPoint deck. `build/final.pdf` uses static video posters and does not contain playable video. Keep HTML plus its assets for the browser version.

The retained six-view archive contains CSV statistics, display PNGs, error/covariance arrays and reproducible figure scripts. Full method HDR frames have been retired. CSVs and arrays support replots, crop changes and analysis of the stored metric definitions; display PNGs do not support recomputing arbitrary scene-linear HDR metrics, changing luminance epsilon, or reconstructing the original path reservoirs. Finite 16384-spp references have no independent reference-covariance estimate. Motion videos are qualitative; there is no trajectory reference or motion SMAPE ground truth. Presentation crops selected for observed gains are illustrative, not unbiased scene samples. GPU timing is measured without image export; stage events can be nested.


## Package a reporting handoff

Run `python -B writing/final/tools/package_handoff.py --output build/handoffs/NEW-NAME` after checking the exported deck. The output directory must not exist. This command creates a new main bundle and optional original-video bundle, then verifies their extracted checksums. It does not run at module import. The package's `tools/build_slides.ps1` delegates to `writing/final/tools/build.ps1`; no second build implementation is embedded in the packager. Templates live in `templates/handoff/`. The package includes the current index's pinned media receipts (including selected `build/media-receipts/` files) and available ASS overlay sources. Playback verification needs the five current MP4s, posters and receipts. A full media rebuild uses the original trajectory footage and timings, the reviewed Bistro previews in build/presentation-preview-20261119, and the retained CGNS + NRD videos in the experiment runs. This is an editing/reporting bundle, not a complete renderer installation.
