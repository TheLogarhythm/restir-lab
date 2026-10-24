# Setup

Run `python scripts/check_scaffold.py` from the repository root to check the layout and original course files. Local `assets/`, `runs/`, `build/`, and renderer builds are ignored.

## RTXDI on Windows

Requires an NVIDIA RTX GPU and driver, Visual Studio 2022 C++ tools with a Windows SDK, CMake 3.22+, Git LFS, and Python 3.11+. Run these commands in PowerShell from the repository root:

```powershell
$previousLfsSetting = $env:GIT_LFS_SKIP_SMUDGE
try {
    $env:GIT_LFS_SKIP_SMUDGE = '1'
    git submodule update --init --recursive
} finally {
    $env:GIT_LFS_SKIP_SMUDGE = $previousLfsSetting
}
git -C renderers/rtxdi/Assets/Media lfs pull --include 'CornellBox/**,Arcade/**,fonts/**,ies-profiles/**' --exclude ''
cmake -S renderers/rtxdi -B renderers/rtxdi/build -G 'Visual Studio 17 2022' -A x64 -DDONUT_WITH_VULKAN=OFF -DDONUT_WITH_DLSS=ON -DRTXDI_CONSOLE_APP=ON
cmake --build renderers/rtxdi/build --config Release --target MinimalSample FullSample --parallel 4
python scripts/run/rtxdi.py
```

The run saves a 1280 × 720 Cornell Box BMP and its command, configuration, and log under ignored `runs/`. Use `python scripts/run/rtxdi.py --interactive` for an interactive FullSample, or `./renderers/rtxdi/build/bin/MinimalSample.exe` for Arcade. Keep DLSS compiled in for this upstream revision; the Cornell runner selects denoising and AA `OFF` at runtime. See the [RTXDI decision](decisions/0002-rtxdi-environment.md).

## Controlled PDF comparison

The completed 78-run campaign is now the local archive at `runs/pdf-similarity-archive/`. It contains all three-seed CSV/timings, full seed-1 PNG sequences, and selected HDR for static frame 128 and temporal frames 31/32/47/48/95/96. Cornell/Arcade retain five original precision acceptances; Bistro uses ten seed-1001 / 262,144-local-sample fixed references whose precision is not evaluated.

Verify the archive without GPU work:

```powershell
python -B scripts/analysis/pdf_archive.py verify --decode
python -B scripts/analysis/pdf_archive.py numerical
```

The second command recomputes sparse spatial/local-temporal metrics and checks numeric maps against the saved pre-deletion array hashes. Original metadata paths are historical; archive-inputs.json supplies current paths. The old MP4s and full reference-generation chain have been removed. Use the generated viewer at `writing/progress/comparison.html#sequences` (build instructions are in the [progress README](../writing/progress/README.md)) to play synchronized video previews and inspect the complete archived PNG sequences.

The original reference window and scheduled launch are finished. The renderer runner rejects the retired output name; a new experiment needs a new campaign name and its own approved budget. Original supervision, source/configuration snapshots and audit records survive under runs/pdf-similarity-archive/audits/.

## Course documents

Edit [proposal/main.tex](../writing/course/proposal/main.tex) and [report/main.tex](../writing/course/report/main.tex); keep [original templates](../writing/course/templates/README.md) unchanged. With TeX Live installed, create `build/latex/proposal` and `build/latex/report`, then run from the repository root:

```powershell
pdflatex -interaction=nonstopmode -halt-on-error -output-directory=build/latex/proposal writing/course/proposal/main.tex
bibtex build/latex/proposal/main
pdflatex -interaction=nonstopmode -halt-on-error -output-directory=build/latex/proposal writing/course/proposal/main.tex
pdflatex -interaction=nonstopmode -halt-on-error -output-directory=build/latex/proposal writing/course/proposal/main.tex
pdflatex -interaction=nonstopmode -halt-on-error -output-directory=build/latex/report writing/course/report/main.tex
```
