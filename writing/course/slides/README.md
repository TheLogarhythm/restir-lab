# Course slides

The [pitch draft](pitch.md) is a seven-slide English Marp deck with speaker notes, planned for **3 minutes 15 seconds**. It follows the proposal; all implementations and experiments remain planned work.

## Edit and preview

Edit `pitch.md` in Marp for VS Code (enable HTML), or build with Node.js/npm from the repository root:

Windows:

```powershell
powershell -ExecutionPolicy Bypass -File writing/course/slides/build.ps1
```

macOS:

```bash
bash writing/course/slides/build.sh
```

Both scripts use Marp CLI 4.5.1 and a locally installed Chrome or Edge. The first run may download Marp through npm. Each writes a self-contained `pitch.html`, `pitch.pdf` with notes, and `pitch-notes.txt` under ignored `build/slides/`. Add `-Images` on Windows or `--images` on macOS to export 1920 × 1080 PNG slides. The shell script uses Bash 3.2-compatible syntax and requires no extra Python tools. The Markdown is the editable source; generated files do not belong in Git.

## Recording

- Rehearse the notes and adjust the pacing to stay within **3:00–3:30**; timings are targets, not measured narration.
- Keep the opening title and required course identifiers visible for at least three seconds.
- Reserve the lower-right corner for the speaker video (approximately 280 × 170 pixels at 1920 × 1080). The slides leave that region clear.
- Record FullHD 1920 × 1080 MP4; do not artificially speed up narration. Check Canvas for any revised instructions before recording.

These requirements come from the [course webpage](https://course.cse.ust.hk/comp5411/) supplied for this project. Logarhythm records the pitch; Logarhythm and Friday review it together. [Issue #1](https://github.com/TheLogarhythm/restir-lab/issues/1) tracks preparation and submission.

See [sources](sources.md) for illustration credits and references. Paper figures are explicitly labeled as author results, not project results. When adding our own figures later, link them to experiment run IDs.
