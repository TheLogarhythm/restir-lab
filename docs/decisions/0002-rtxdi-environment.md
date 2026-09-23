# 0002: RTXDI environment

Use official RTXDI `v3.1.0` (`a6efab966b7c3b272da0461578eb56ac61c7cbff`) as an unmodified submodule at `renderers/rtxdi`. Build Windows x64 / D3D12 / Release in `renderers/rtxdi/build` so the samples locate `Assets/Media`.

The Cornell runner selects Cornell Box in FullSample; unmodified FullSample defaults to BistroMirror. MinimalSample loads Arcade. Fetch Cornell Box and Arcade from the pinned asset submodule with Git LFS.

Build with `DONUT_WITH_VULKAN=OFF` and `DONUT_WITH_DLSS=ON`. FullSample fails to compile with DLSS disabled in this revision; the Cornell runner disables it at runtime. See [setup](../setup.md).
