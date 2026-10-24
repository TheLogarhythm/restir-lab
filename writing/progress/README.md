# PDF Similarity: experiment viewer and progress report

Use these two pages:

| Purpose | Page |
| --- | --- |
| Videos, original images, error maps, ROIs and three-seed statistics | `comparison.html` |
| Play the Marp slides and record the report | `progress.html` |

HTML pages and videos are generated local outputs and are excluded from Git. Use the [build script](tools/build.ps1) and the instructions below to create them from the tracked sources.

## Video comparison

Each of the four experiments has three videos: PDF off, PDF on and an automatic diagonal comparison. Each video is 1920×1080, with 96 frames at 30 FPS, lasts 3.2 seconds and has no audio. The two views are aligned exactly. PDF on appears on the left and PDF off on the right of a diagonal running from bottom left to top right (/). The separate comparison video sweeps automatically from all off to all on.

The comparison page supports playback, pause, slow motion, looping, frame selection and fullscreen. Drag the diagonal in the image or adjust the slider below it. The divider handle also supports the arrow keys, Home and End. The page displays only matched frame pairs and retains the previous complete pair while decoding.

The H.264 CRF 20 videos are lossy presentation copies. To inspect noise and detail, pause and click "Inspect original PNGs" to load the unchanged PNGs for the same frame on both sides. These images retain the experiment's display transform and cannot replace linear HDR error analysis.

Automatic comparison videos: Arcade: `assets/videos/arcade-motion/comparison.mp4` · Bistro interior: `assets/videos/bistro-interior-motion/comparison.mp4` · Bistro exterior: `assets/videos/bistro-exterior-motion/comparison.mp4` · Bistro lighting change: `assets/videos/bistro-lighting/comparison.mp4`.

## File locations

- assets/: selected slide images, the paper's Figure 2 crop, one demo poster frame and 12 videos. Media files are excluded from Git.
- data/: overview CSVs, field definitions, source and scene indexes, video build records, verification reports and cleanup inventories.
- [source/progress.md](source/progress.md): the single source for the slides, narration and rehearsal timings.
- HTML/CSS/JS in source/: templates and interaction code for the experiment viewer.
- tools/: build and verification tools.

The full experiment display images, error maps, frame PNGs and raw statistics remain in the local `runs/pdf-similarity-archive/` directory. The comparison page reads them through relative paths without copying the experiment directory. The complete gallery of additional scenes remains in the local `runs/scene-gallery/` directory; this folder contains only the selected report images. Preserve the current repository directory structure when using the full comparison page.

See the [experiment report](../../results/summaries/pdf-similarity/README.md) for the formal statistics, reference policy and scope of observations. Images use seed 1; numerical results use seeds 1/2/3. The five Cornell/Arcade reference states retain their original precision acceptance, while precision remains unevaluated for the ten Bistro reference states. Local temporal metrics cover only 31→32, 47→48 and 95→96. This cleanup preserves all statistical values.

## Editing and building

After editing the Marp source, run this from the repository root:

~~~powershell
.\writing\progress\tools\build.ps1
~~~

By default, the build produces only the two HTML files. It requires local installations of Python, Node.js and Marp CLI 4.5.1. Missing slide images are restored from the source index. If the Figure 2 crop is missing, Poppler's pdftoppm extracts it again from page 3 of the local paper. The paper hash, crop parameters and attribution are in [paper-figure.json](data/paper-figure.json). FFmpeg is required to build videos for the first time or rebuild changed media:

~~~powershell
.\writing\progress\tools\build.ps1 -Media
python -B writing/progress/tools/verify.py --media --write
~~~

-PreviewImages generates eleven preview images on request, and -Notes exports speaker notes. Both go into the ignored build/ directory and can be deleted. The default build does not produce PDF or PPTX files. HTML output and media are also ignored; Git retains the sources, templates, scripts and small data indexes.

The pages work offline in a recent version of Chrome or Edge. The verification script checks all source hashes, image combinations and links, eleven slides, video frame counts and synchronization logic. The browser tool rejected file:// access during the recorded check, so browser interaction remains marked as unverified in that record.

## Recording

The eleven-slide draft has a rehearsal target of **3:30 (210 seconds)**, including 65 seconds of recap across the first three slides. The English narration contains 354 words and has been edited using the humanizer guidance. Each slide's notes give a time range and a short delivery cue. Slide 6 allows 28 seconds for playback and observation. Slide 4 uses Tokuyoshi's (2023) Figure 2 to explain PDF Similarity: lit and shadowed pixels have different target direction distributions, approximated by vMF lobes whose directions and concentration are compared to reduce unsuitable reuse. Slide 6 plays the Bistro exterior diagonal comparison; the interactive page also supports slow motion and dragging the divider at frame 48. Slide 7 presents off/on images for three static scenes, the SMAPE definition and a quality/cost table. Slide 8 shows an indoor spatial-only regression and keeps its explanation as an untested hypothesis. Slide 10 covers CGNS integration and controlled failure-case tests; slide 11 closes with thanks. The demo uses saved render output, so playback speed does not indicate GPU performance. Narration and timings are maintained together in the source notes; the actual duration needs rehearsal. Longer source and scientific-scope notes are kept in [speaker-note-sources.json](data/speaker-note-sources.json), separate from the delivery cues.

The course requirements in [GitHub issue 3](https://github.com/TheLogarhythm/restir-lab/issues/3) were last checked on 2026-10-22: a total duration of 3:30 to 4:00, a 60 to 90 second opening recap, a demonstration of the implementation, and an explanation of completed and remaining programming work. Submit progress.mp4 to Canvas by 2026-10-25 23:59 (Hong Kong time). The recording at `COMP5411/progress.mp4` (outside this repository) was reviewed on 2026-10-24: it lasts 3:35.167, includes about 70 seconds of opening recap, and passes full audio/video decoding. The user confirmed successful Canvas submission on 2026-10-24. Issue 3 is closed and the project item is Done. The source rehearsal timings and 354-word script above remain draft targets, not measured timestamps from the recording.

Scene licenses and sources are retained in the [scene index](data/scenes.json) and [THIRD_PARTY.md](../../THIRD_PARTY.md). The OIDN images of the six additional scenes show scene setup progress and are outside this round of controlled PDF comparisons.
