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

Build both variants with `python scripts/run/build_rtxdi_pdf.py` and `python scripts/run/build_rtxdi_experiments.py --reference`. Run `python scripts/run/rtxdi_pdf_controlled.py --pilot-only` for technical checks only, or omit `--pilot-only` to resume the approved [experiment](../experiments/suites/pdf-similarity.md): all method captures and direct comparison products precede references. Quantitative error products require accepted references. Status, immutable checkpoints, figures and videos are saved under `runs/pdf-controlled-20261018/`; restarting reuses verified work and preserves the total 30-hour deadline in `execution-budget.json`. The 1M reference maximum, budget and precision may change only with prior explicit user approval.

## Course documents

Edit [proposal/main.tex](../writing/course/proposal/main.tex) and [report/main.tex](../writing/course/report/main.tex); keep [original templates](../writing/course/templates/README.md) unchanged. With TeX Live installed, create `build/latex/proposal` and `build/latex/report`, then run from the repository root:

```powershell
pdflatex -interaction=nonstopmode -halt-on-error -output-directory=build/latex/proposal writing/course/proposal/main.tex
bibtex build/latex/proposal/main
pdflatex -interaction=nonstopmode -halt-on-error -output-directory=build/latex/proposal writing/course/proposal/main.tex
pdflatex -interaction=nonstopmode -halt-on-error -output-directory=build/latex/proposal writing/course/proposal/main.tex
pdflatex -interaction=nonstopmode -halt-on-error -output-directory=build/latex/report writing/course/report/main.tex
```
