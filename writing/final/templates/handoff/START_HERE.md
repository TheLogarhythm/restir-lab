# ReSTIR final project handoff

Group 7 — Luoyi Zhang and Zelin Gao. Snapshot: 17 November 2026.

## Start here

1. Submit/present `presentation/final-with-videos.pptx` in desktop PowerPoint. It contains 15 slides and four embedded MP4s, with automatic looping on demo slides. Video playback was tested in PowerPoint on the source machine. Internet and external video paths are not needed. Uploaded web previews or other office applications may behave differently; download and rehearse in PowerPoint.
2. PDFs in `presentation/` are static review copies. They cannot play the videos.
3. Open `writing/final/final.html` in Chrome/Edge for the browser presentation. Keep its `source/playback.js` and `assets/` in their current relative locations. Four comparisons show the three methods simultaneously, with matching crops and authentic GPU timing overlays.
4. Edit `writing/final/source/final.md` for slide content, layout and speaker notes. The submission PPTX preserves ordinary slides as full-page images; its text cannot be edited as individual PowerPoint paragraphs. The embedded video objects can be selected/replaced. A fully editable native-text PPTX is NOT included. PDF/PPTX/HTML exports are separate snapshots; rebuild after editing the Markdown.
5. Read `REPORT_GUIDE.md` and `DATA_INDEX.md` before writing the report or making new plots.

## Edit and rebuild

The editable source is Marp Markdown, with HTML/CSS layouts and KaTeX mathematics. Both decks share `writing/final/source/theme.css`; the build registers it automatically. The appendix prose is editable source; `-Figures` refreshes only its data table. VS Code + Marp is convenient. English narration and timings are inside Markdown comments; `presentation/rehearsal-script.md` is an extracted copy.

For Windows rebuilding, install Node.js, Python 3.11, PowerShell and Chrome/Edge. From this extracted root:

```powershell
npm install
python -m pip install -r requirements-analysis.txt
.\tools\build_slides.ps1 -Pdf
# Also rebuild static charts from preserved data:
.\tools\build_slides.ps1 -Figures -Pdf
# Also regenerate the submission PPTX with embedded videos (desktop PowerPoint required):
.\tools\build_slides.ps1 -Pdf -Pptx
```

The first two install commands download dependencies when explicitly run. Prebuilt HTML/PDF/PPTX need no development environment. Plot builders use Windows Arial/Segoe fonts. On macOS/Linux, adjust the font paths in the figure builders or use the supplied prebuilt figures. No Falcor runtime, GPU or scene geometry is needed to edit slides/replot retained data. Do not run GPU capture entry points merely to rebuild the presentation.

Use `python -B tools/verify_handoff.py` to check packaged file hashes before editing. Changes after editing are expected to invalidate snapshot hashes. Original receipts may include historical machine paths and retired files; the package checksum list describes the delivered files.

## What is included

- Complete editable slide source, required static assets, current four course-style comparison videos, seven-slide appendix, submission PPTX, PDF and narration.
- Complete compact six-view statistics archive: CSV tables, PNG displays, plot PDFs/PNGs, NPZ arrays, metadata and replot tools. Deep historical records are nested in records.zip to avoid Windows path-length failures.
- Method/experiment documentation, configurations, analysis code, report/template source, bibliography, four relevant papers and attribution notices.
- Original twelve separate method videos and retained trajectory timing/capture metadata are in the separate OPTIONAL original-video ZIP. Extract it beside this package and copy/merge its `runs/` and `scenes/` directories only if needed for recomposition. It does not contain retired raw image sequences or diagnostic HDR.

## Important boundaries

This is an editing/reporting handoff, not a self-contained rendering installation. Large scene assets, renderer binaries/build trees, private runtimes, full reference EXRs and retired full method HDR are not included. Historical receipts remain provenance, not a promise that their original paths or inputs still exist. Do not claim the bundle can resume rendering or regenerate retired inputs.

The target talk is 4:30 including 2:00 of demo. Fifteen main slides include a separate final thank-you page. Rehearse timing; it is a plan, not a measured final recording. The current report main.tex is still a course template containing placeholders, not a completed final report.

All original experiment files were copied, never modified. No commit or push was made. This snapshot includes uncommitted workspace changes; the recorded Git HEAD alone does not reproduce the snapshot. See provenance/source-state.json and checksums.sha256.
