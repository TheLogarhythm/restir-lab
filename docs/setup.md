# Setup

## Falcor and live demo

Use Windows x64, an NVIDIA RTX GPU with a Direct3D 12 driver, Git, Python 3.11, Visual Studio 2022 with the C++ desktop workload, Windows SDK `10.0.22621.0` and CUDA 12.6 headers. Choose a checkout path without spaces and allow at least 15 GiB for the build. [Falcor build details](../renderers/falcor/README.md)

From PowerShell, build the pinned Falcor Release and install Veach Ajar (about 9 MB, Python conversion).

```powershell
git clone https://github.com/TheLogarhythm/restir-lab.git
Set-Location restir-lab
python -m pip install -r scripts/assets/requirements.txt
.\scripts\falcor\setup.ps1 -Jobs 4
python -B scripts/assets/install_scene.py --scene veach-ajar
.\run-demo.ps1 -Scene "Veach Ajar"
```

The first launch builds the demo executable. Later launches reuse it. Run `.\run-demo.ps1` for the scene selector, or `.\run-demo.ps1 -PrecompileShaders -Scene "Veach Ajar"` to warm that scene's shaders before a demo.

### Install more scenes

Run `python -B -m scripts.falcor.live_demo.scenes` to list installed presets. Restart the demo after adding assets. [Scene downloads and checksums](../scenes/manifest.yaml)

| Preset | Preparation |
| --- | --- |
| Bistro Exterior | Extract ORCA Bistro 5.2 with its textures and HDR. [Extraction command](../experiments/configs/falcor-pt-spatial-comparison/PREPARATION.md#bistro-exterior) |
| Bistro Interior | Fetch the RTXDI Bistro assets and bake the environment. [Media and sky commands](../experiments/configs/falcor-pt-spatial-comparison/PREPARATION.md#bistro-interior) |
| Classroom | Convert the Blender scene and fetch `urban_street_04_4k.exr`. [Classroom setup](../scripts/assets/README.md#falcor-environment-maps) |
| San Miguel | Convert the low-poly OBJ, run `python -m pip install -r scripts/falcor/requirements.txt`, then run `python -B -m scripts.falcor.live_demo.scenes --prepare` to bake the sky. [Conversion](../scripts/assets/README.md#san-miguel-and-classroom) |
| Sun Temple | Run `python -B scripts/assets/install_scene.py --scene sun-temple` with Blender 5.2. [Installer](../scripts/assets/README.md#emerald-square-sun-temple-and-veach-ajar) |
| Zero Day Measure Seven | Export visible geometry at frame 1 and fetch `derelict_overpass_4k.exr`. [Conversion](../experiments/configs/falcor-pt-spatial-comparison/PREPARATION.md#classroom-emerald-square-veach-ajar-and-zero-day) / [Environment map](../scripts/assets/README.md#falcor-environment-maps) |

## RTXDI

The separate direct-lighting experiments use Visual Studio 2022, CMake 3.22+ and Git LFS. From the repository root, fetch the sample assets, build and render Cornell Box. [RTXDI experiments](reproductions/rtxdi.md)

```powershell
$previousLfsSetting = $env:GIT_LFS_SKIP_SMUDGE
try {
    $env:GIT_LFS_SKIP_SMUDGE = '1'
    git -c core.autocrlf=true submodule update --init --recursive renderers/rtxdi
} finally {
    $env:GIT_LFS_SKIP_SMUDGE = $previousLfsSetting
}
git -C renderers/rtxdi/Assets/Media lfs pull --include=CornellBox/**,Arcade/**,fonts/**,ies-profiles/** --exclude=
cmake -S renderers/rtxdi -B renderers/rtxdi/build -G 'Visual Studio 17 2022' -A x64 -DDONUT_WITH_VULKAN=OFF -DDONUT_WITH_DLSS=ON -DRTXDI_CONSOLE_APP=ON
cmake --build renderers/rtxdi/build --config Release --target MinimalSample FullSample --parallel 4
python -B scripts/run/rtxdi.py
```

## Course report

With TeX Live and `latexmk` on PATH, run `.\writing\course\report\build.ps1` to regenerate the [report PDF](../writing/report/report.pdf) from the [LaTeX source](../writing/course/report/main.tex).
