"""Checked temporary adaptations of the pinned GI/PT renderer.

Do not edit the SDK in place. Adapted headers are published in the isolated shader
tree by the transport build. Neighbor selection changes coordinates only.
"""
from pathlib import Path
import shutil
import rtxdi_cgns as cgns

HERE = Path(__file__).resolve().parent
PAYLOAD = HERE / "rtxdi_experiments"
SOURCE = "Samples/FullSample/Source/"
SHADERS = "Samples/FullSample/Shaders/"
LIGHTING = SHADERS + "LightingPasses/"
FILES = [SOURCE + "RenderPasses/LightingPasses/ReSTIRGIRenderPasses." + ext for ext in ("cpp", "h")]
FILES += [LIGHTING + name for name in ("GI/SpatialResampling.hlsl", "GI/FinalShading.hlsl",
          "PT/SpatialNeighborSelection.hlsl", "PT/SpatialResampling.hlsl", "ShadeSecondarySurfaces.hlsl")]
FILES += [SHADERS + name for name in ("GlassPass.hlsl", "CompositingPass.hlsl")]
CREATED = [LIGHTING + name for name in ("GI/CgnsSelectNeighbors.hlsl", "GI/CgnsSpatialResampling.hlsli",
                                       "PT/CgnsSpatialResampling.hlsli")]
SUPPORT = [Path(__file__), PAYLOAD / "TransportControls.h"]


def replace_checked(text, old, new, count=1):
    if text.count(old) != count:
        raise RuntimeError(f"Pinned transport source changed: expected {count} occurrence(s) of {old[:70]!r}")
    return text.replace(old, new)


def adapt_gi_spatial(text):
    coordinate = ("int2 idx = int2(pixelPosition) + RTXDI_CalculateSpatialResamplingOffset("
                  "neighborSampleStartIdx + i, sparams.samplingRadius, rParams.neighborOffsetMask);")
    # Both rounds read exactly the same list. The SDK cachedResult mask is set
    # only after geometry, material, reservoir and Jacobian validation succeeds.
    text = replace_checked(text, coordinate, coordinate + "\n"
        "        if (LabTransportCgnsEnabled() && !LabCgnsNeighbor(pixelPosition, i, idx)) continue;", 2)
    text = replace_checked(text, "    uint cachedResult = 0;",
                           "    uint cachedResult = 0;\n    uint labMergedNeighbors = 0;")
    text = replace_checked(text, "        cachedResult |= (1u << uint(i));",
                           "        cachedResult |= (1u << uint(i));\n        ++labMergedNeighbors;")
    text = replace_checked(text, "    return curReservoir;",
                           "    LabRecordSpatialNeighbors(pixelPosition, labMergedNeighbors);\n    return curReservoir;")
    return text


def adapt_gi_final(text):
    # SDK Spatial/TAS writes array 1, whereas native FullSample shades array 0.
    # Use the explicit SDK final index in every mode, including CGNS-off.
    return replace_checked(text, "g_Const.restirGI.bufferIndices.secondarySurfaceReSTIRDIOutputBufferIndex",
                           "g_Const.restirGI.bufferIndices.finalShadingInputBufferIndex")


def adapt_gi_secondary(text):
    # Delta-specular paths deliberately bypass GI reservoirs; actually output
    # their precomputed radiance instead of replacing it with zero.
    text = replace_checked(text, "        if (!isDeltaSurface)",
                           "        if (!isDeltaSurface || isSpecularRay)")
    text = replace_checked(text,
        "        // Firefly suppression\n"
        "        float indirectLuminance = CalcLuminance(radiance);\n"
        "        if (indirectLuminance > c_MaxIndirectRadiance)\n"
        "            radiance *= c_MaxIndirectRadiance / indirectLuminance;",
        "        // Controlled transport: no radiance clamp, in either method.")
    return text


def adapt_pt_spatial(text):
    # The official PT consumer already caches its neighbor set and performs its
    # native forward/inverse hybrid shift, Jacobian and proposal correction.
    # Count the SDK acceptance mask; do not insert a second validity policy.
    return replace_checked(text, "    return targetReservoir;",
        "    LabRecordSpatialNeighbors(srrParams.pixelPosition, countbits(cachedResult));\n"
        "    return targetReservoir;")


def edit(path, old, new, count=1):
    path.write_text(replace_checked(path.read_text(encoding="utf-8"), old, new, count), encoding="utf-8")


def preserve_invalid_radiance(renderer):
    # Never disguise an invalid linear sample as a finite display blue value.
    # Export validation then rejects a non-finite HDR instead of accepting it.
    edit(renderer / SHADERS / "CompositingPass.hlsl",
         "    if(any(isnan(compositedColor)))\n        compositedColor = float3(0, 0, 1);",
         "    // Controlled HDR: preserve NaN/Inf for fail-closed export validation.")


def adapt(renderer, helper):
    """Called only inside build_variant's backup/restore transaction."""
    cgns.adapt(renderer, helper)
    preserve_invalid_radiance(renderer)
    source, shaders, lighting = renderer / SOURCE, renderer / SHADERS, renderer / LIGHTING
    edit(source / "App/SceneRenderer.cpp", '"shaders/full-sample-cgns"', '"shaders/full-sample-transport"')
    edit(source / "App/SceneRenderer.cpp", "    lab.ConfigureCgns(m_isContext->GetReSTIRDIContext());",
         "    lab.ConfigureCgns(m_isContext->GetReSTIRDIContext());\n    lab.ConfigureTransport(*m_isContext);")
    edit(helper, "public:\n", "public:\n" + (PAYLOAD / "TransportControls.h").read_text(encoding="utf-8") + "\n")
    edit(helper, "        ui.enableAnimations = false;", "        ApplyTransport(ui);\n        ui.enableAnimations = false;")
    edit(helper, '        auto stream = Open(output / "resolved.json");',
         '        RecordTransport(record, context, ui);\n        auto stream = Open(output / "resolved.json");')
    edit(helper, '"gi_temporal", "gi_spatial",', '"gi_temporal", "gi_neighbor", "gi_spatial",')
    edit(helper, "                    if (di.GetSpatialResamplingParameters().pad1)",
         "                    if (di.GetSpatialResamplingParameters().pad1 || TransportCgnsEnabled())")

    # GI gains a selection pass; PT already owns one with the correct resources.
    for ext in ("h", "cpp"):
        edit(source / f"RenderPasses/LightingPasses/ReSTIRGIRenderPasses.{ext}",
             "nvrhi::BufferHandle giReservoirBuffer)",
             "nvrhi::BufferHandle giReservoirBuffer, nvrhi::BufferHandle neighborSelectionBuffer)")
    edit(source / "RenderPasses/LightingPasses/LightingPasses.cpp",
         "restirGIContext, m_GIReservoirBuffer);", "restirGIContext, m_GIReservoirBuffer, m_SpatialNeighborSelectionBuffer);")
    edit(source / "RenderPasses/LightingPasses/ReSTIRGIRenderPasses.h",
         "    RayTracingPass m_GISpatialResamplingPass;",
         "    RayTracingPass m_GISpatialResamplingPass;\n    RayTracingPass m_GICgnsSelectionPass;")
    gi = source / "RenderPasses/LightingPasses/ReSTIRGIRenderPasses.cpp"
    edit(gi, '    m_GISpatialResamplingPass.Init(',
         '    m_GICgnsSelectionPass.Init(device, shaderFactory, "app/LightingPasses/GI/CgnsSelectNeighbors.hlsl", {}, true, RTXDI_SCREEN_SPACE_GROUP_SIZE, bindingLayout, nullptr, bindlessLayout);\n    m_GISpatialResamplingPass.Init(')
    edit(gi, "            ExecuteRayTracingPass(commandList, m_GISpatialResamplingPass,", '''            if (context.GetSpatialResamplingParameters().pad1)
            {
                nvrhi::utils::BufferUavBarrier(commandList, neighborSelectionBuffer);
                ExecuteRayTracingPass(commandList, m_GICgnsSelectionPass, false, "GINeighborSelection", dispatchSize, *m_profiler, ProfilerSection::GINeighborSelection, m_descriptorTable, m_bindingSet, nullptr);
                nvrhi::utils::BufferUavBarrier(commandList, neighborSelectionBuffer);
            }
            ExecuteRayTracingPass(commandList, m_GISpatialResamplingPass,''')
    edit(source / "ProfilerSections.h", "        GISpatialResampling,", "        GINeighborSelection,\n        GISpatialResampling,")
    edit(source / "Profiler.cpp", '    "GI - Spatial Resampling",', '    "GI - Neighbor Selection",\n    "GI - Spatial Resampling",')
    edit(shaders / "CMakeLists.txt", "   LightingPasses/GI/SpatialResampling.hlsl",
         "   LightingPasses/GI/CgnsSelectNeighbors.hlsl\n   LightingPasses/GI/SpatialResampling.hlsl")
    edit(shaders / "Shaders.cfg", "LightingPasses/GI/SpatialResampling.hlsl -T cs",
         "LightingPasses/GI/CgnsSelectNeighbors.hlsl -T cs -E main -D USE_RAY_QUERY=1\nLightingPasses/GI/SpatialResampling.hlsl -T cs")

    selection = (PAYLOAD / "CgnsSelectNeighbors.hlsl").read_text(encoding="utf-8")
    selection = replace_checked(selection, '#include "Cgns.hlsli"', '#include "../DI/Cgns.hlsli"')
    gi_selection = replace_checked(selection, "RTXDI_DISpatialResamplingParameters params = g_Const.restirDI.spatialResamplingParams;",
                                  "RTXDI_GISpatialResamplingParameters params = g_Const.restirGI.spatialResamplingParams;")
    (lighting / "GI/CgnsSelectNeighbors.hlsl").write_text(gi_selection, encoding="utf-8")
    pt_selection = replace_checked(selection, "RTXDI_DISpatialResamplingParameters params = g_Const.restirDI.spatialResamplingParams;",
        "RTXDI_GISpatialResamplingParameters params = g_Const.restirGI.spatialResamplingParams;\n"
        "        params.numSamples = g_Const.restirPT.spatialResampling.numSpatialSamples;\n"
        "        params.samplingRadius = g_Const.restirPT.spatialResampling.samplingRadius;")
    (lighting / "PT/SpatialNeighborSelection.hlsl").write_text(pt_selection, encoding="utf-8")

    sdk = renderer / "Libraries/Rtxdi/Include/Rtxdi"
    (lighting / "GI/CgnsSpatialResampling.hlsli").write_text(
        adapt_gi_spatial((sdk / "GI/SpatialResampling.hlsli").read_text(encoding="utf-8")), encoding="utf-8")
    (lighting / "PT/CgnsSpatialResampling.hlsli").write_text(
        adapt_pt_spatial((sdk / "PT/SpatialResampling.hlsli").read_text(encoding="utf-8")), encoding="utf-8")
    edit(lighting / "GI/SpatialResampling.hlsl", "#include <Rtxdi/GI/SpatialResampling.hlsli>",
         '#include "../DI/Cgns.hlsli"\nbool LabTransportCgnsEnabled() { return g_Const.restirGI.spatialResamplingParams.pad1 != 0; }\n#include "CgnsSpatialResampling.hlsli"')
    edit(lighting / "GI/SpatialResampling.hlsl", "    if (any(pixelPosition > int2(g_Const.view.viewportSize)))",
         "    LabClearSpatialNeighbors(pixelPosition);\n    if (any(pixelPosition >= int2(g_Const.view.viewportSize)))")
    edit(lighting / "PT/SpatialResampling.hlsl", "#include <Rtxdi/PT/SpatialResampling.hlsli>",
         '#include "../DI/Cgns.hlsli"\n#include "CgnsSpatialResampling.hlsli"')
    edit(lighting / "PT/SpatialResampling.hlsl", "    RTXDI_PTSpatialResamplingRuntimeParameters srrParams =",
         "    LabClearSpatialNeighbors(pixelPosition);\n    RTXDI_PTSpatialResamplingRuntimeParameters srrParams =")
    for path, transform in ((lighting / "GI/FinalShading.hlsl", adapt_gi_final),
                            (lighting / "ShadeSecondarySurfaces.hlsl", adapt_gi_secondary)):
        path.write_text(transform(path.read_text(encoding="utf-8")), encoding="utf-8")
    # Freeze the same existing glass overlay used by the reusable DI artifacts.
    edit(shaders / "GlassPass.hlsl", "if (g_Const.indirectLightingMode != INDIRECT_LIGHTING_MODE_RESTIRPT)",
         "if (true) // Controlled legacy-DI glass policy for all methods")
