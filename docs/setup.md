# Setup

Run commands from PowerShell at the repository root. Both renderers use Windows x64, D3D12 and a compatible NVIDIA RTX GPU and driver. Install Python 3.11+ and the C++ build tools listed for your backend.

## Falcor and live demo

Build the pinned Falcor 9.0 Release tree using Visual Studio 2022, Windows SDK `10.0.22621.0` and a checkout path without spaces. Prepare the scene assets and install the Falcor Python requirements. [Falcor build guide](../renderers/falcor/README.md) · [Assets and runtime preparation](../experiments/configs/falcor-pt-spatial-comparison/PREPARATION.md)

~~~powershell
.\scripts\falcor\setup.ps1 -Jobs 4
python -m pip install -r scripts/falcor/requirements.txt
python -B scripts/falcor/run.py --mode restir-pt --output runs/falcor/restir-pt-smoke
~~~

In a checkout with the live demo launcher, run `.\run-demo.ps1 -Scene Classroom` after preparing its assets. The live runtime requires matching development libraries and CUDA headers. Use `-Prepare` after changing native integration code. [Fixed-view benchmark](reproductions/pt-6-views-spatial-compare.md)

## RTXDI

Install Visual Studio 2022, a Windows SDK, CMake 3.22+ and Git LFS. Fetch only the samples needed for the initial smoke run.

~~~powershell
$previousLfsSetting = $env:GIT_LFS_SKIP_SMUDGE
try {
    $env:GIT_LFS_SKIP_SMUDGE = '1'
    git submodule update --init --recursive renderers/rtxdi
} finally {
    $env:GIT_LFS_SKIP_SMUDGE = $previousLfsSetting
}
git -C renderers/rtxdi/Assets/Media lfs pull --include 'CornellBox/**,Arcade/**,fonts/**,ies-profiles/**' --exclude ''
cmake -S renderers/rtxdi -B renderers/rtxdi/build -G 'Visual Studio 17 2022' -A x64 -DDONUT_WITH_VULKAN=OFF -DDONUT_WITH_DLSS=ON -DRTXDI_CONSOLE_APP=ON
cmake --build renderers/rtxdi/build --config Release --target MinimalSample FullSample --parallel 4
python -B scripts/run/rtxdi.py
~~~

The runner captures Cornell Box. Add `--interactive` to open FullSample. MinimalSample loads Arcade. The pinned FullSample needs DLSS enabled at build time. The Cornell configuration disables denoising and antialiasing at runtime. [RTXDI experiments](reproductions/rtxdi.md)

## Course report

Edit the [working LaTeX file](../writing/course/report/main.tex). For report revisions that supply `build.ps1`, run `.\writing\course\report\build.ps1` with TeX Live and Poppler to extract the figures and compile `report.pdf`.
