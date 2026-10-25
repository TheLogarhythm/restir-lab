"""Checked, temporary CGNS adaptations of the pinned RTXDI DI pipeline."""
from pathlib import Path
import shutil

HERE = Path(__file__).resolve().parent
PAYLOAD = HERE / "rtxdi_experiments"
SOURCE = "Samples/FullSample/Source/"
SHADERS = "Samples/FullSample/Shaders/"
DI = SHADERS + "LightingPasses/DI/"
FILES = [SOURCE + name for name in (
    "RtxdiResources.cpp", "RtxdiResources.h", "ProfilerSections.h", "Profiler.cpp",
    "RenderPasses/LightingPasses/LightingPasses.cpp",
    "RenderPasses/LightingPasses/ReSTIRDIRenderPasses.cpp",
    "RenderPasses/LightingPasses/ReSTIRDIRenderPasses.h")]
FILES += [SHADERS + "CMakeLists.txt", SHADERS + "Shaders.cfg", DI + "SpatialResampling.hlsl"]
NAMES = ("CgnsMath.h", "Cgns.hlsli", "CgnsSelectNeighbors.hlsl")
CREATED = [DI + name for name in (*NAMES, "CgnsSpatialResampling.hlsli")]
CREATED += [SOURCE + "App/CgnsMath.h"]
SUPPORT = [Path(__file__), *(PAYLOAD / name for name in NAMES)]
AUTHOR_COMMIT = "f28d553f3b2552b1be829feffea6d1abb1945e1d"


def replace(path, old, new, count=1):
    text = path.read_text(encoding="utf-8")
    if text.count(old) != count:
        raise RuntimeError(f"Unexpected pinned source at {path}: expected {count} matches")
    path.write_text(text.replace(old, new), encoding="utf-8")


def adapt_spatial(text):
    """Reuse one stored neighbor list in selection and raytraced normalization."""
    marker = "RTXDI_DIReservoir RTXDI_DISpatialResampling("
    prefix, spatial = text.split(marker)

    def change(old, new):
        nonlocal spatial
        if spatial.count(old) != 1:
            raise RuntimeError("Unexpected pinned DI spatial source")
        spatial = spatial.replace(old, new)

    change("        int2 idx = int2(pixelPosition) + spatialOffset;",
           """        int2 idx = int2(pixelPosition) + spatialOffset;
        if (LabCgnsEnabled())
        {
            if (!LabCgnsNeighbor(pixelPosition, i, idx)) continue;
            spatialOffset = idx - int2(pixelPosition);
        }""")
    change("                idx = RAB_ClampSamplePositionIntoView(idx, false);",
           """                if (LabCgnsEnabled() && !LabCgnsNeighbor(pixelPosition, i, idx)) continue;
                idx = RAB_ClampSamplePositionIntoView(idx, false);""")
    change("if (!RTXDI_IsValidNeighbor(", "if (!LabCgnsEnabled() && !RTXDI_IsValidNeighbor(")
    change("if (sparams.enableMaterialSimilarityTest &&", "if (!LabCgnsEnabled() && sparams.enableMaterialSimilarityTest &&")
    return prefix + marker + spatial


def configure(helper):
    replace(helper, '    void ApplySun(', '''    void ConfigureCgns(rtxdi::ReSTIRDIContext& di) const
    {
        auto enabled = config["definition"].get("cgns", false);
        auto candidates = config["definition"].get("cgns_candidates", 32);
        auto early = config["definition"].get("cgns_early_stopping", true);
        if (!enabled.isBool() || !early.isBool() ||
            (candidates.type() != Json::intValue && candidates.type() != Json::uintValue) ||
            !candidates.isUInt() || candidates.asUInt() < 1 || candidates.asUInt() > 32)
            throw std::runtime_error("Invalid CGNS configuration");
        if (config["definition"].get("pdf_similarity", false).asBool())
            throw std::runtime_error("Use the separate PDF similarity executable");
        auto spatial = di.GetSpatialResamplingParameters();
        auto mode = di.GetResamplingMode();
        if (enabled.asBool() &&
            ((mode != rtxdi::ReSTIRDI_ResamplingMode::Spatial && mode != rtxdi::ReSTIRDI_ResamplingMode::TemporalAndSpatial) ||
             !di.GetInitialSamplingParameters().enableInitialVisibility ||
             spatial.biasCorrectionMode != ReSTIRDI_SpatialBiasCorrectionMode::Raytraced ||
             di.GetStaticParameters().CheckerboardSamplingMode != rtxdi::CheckerboardMode::Off ||
             spatial.numSamples < 1 || spatial.numSamples > 4 || spatial.numSamples > candidates.asUInt() ||
             spatial.numDisocclusionBoostSamples > spatial.numSamples ||
             di.GetStaticParameters().RenderWidth >= 65536 || di.GetStaticParameters().RenderHeight >= 65536))
            throw std::runtime_error("CGNS requires unfused spatial DI, initial visibility, raytraced correction, no checkerboard and 1..4 neighbors <= K");
        // App-private flags preserve the upstream constant-buffer ABI.
        spatial.pad1 = enabled.asBool();
        spatial.pad2 = candidates.asUInt();
        spatial.pad3 = early.asBool();
        di.SetSpatialResamplingParameters(spatial);
    }

    void ApplySun(''')
    replace(helper, '        record["scene_id"] = config["scene_id"];',
            '        record["scene_id"] = config["scene_id"];\n'
            '        record["cgns"] = bool(p.spatialResamplingParams.pad1);\n'
            '        record["cgns_candidates"] = p.spatialResamplingParams.pad2;\n'
            '        record["cgns_early_stopping"] = bool(p.spatialResamplingParams.pad3);\n'
            '        record["cgns_solid_angle"] = 0.05; record["cgns_normal_beta"] = 8;\n'
            '        record["cgns_extra_bytes"] = uint64_t(di.GetStaticParameters().RenderWidth) * di.GetStaticParameters().RenderHeight * 4 + 8192 * 8;')
    replace(helper, '"temporal", "spatial",', '"temporal", "neighbor_selection", "spatial",')
    replace(helper, '            if (config["diagnostics"].asBool())', '''            if (config["diagnostics"].asBool() && di.GetSpatialResamplingParameters().pad1)
            {
                const auto bytes = uint64_t(desc.width) * desc.height * sizeof(uint32_t);
                nvrhi::BufferDesc statsDesc;
                statsDesc.byteSize = bytes;
                statsDesc.cpuAccess = nvrhi::CpuAccessMode::Read;
                statsDesc.initialState = nvrhi::ResourceStates::CopyDest;
                auto readback = device->createBuffer(statsDesc);
                command->open();
                command->copyBuffer(readback, 0, resources.CgnsStatisticsBuffer, 0, bytes);
                command->close();
                device->executeCommandList(command);
                device->waitForIdle();
                auto data = static_cast<const char*>(device->mapBuffer(readback, nvrhi::CpuAccessMode::Read));
                if (!data) throw std::runtime_error("Cannot map CGNS statistics");
                try { auto stream = Open(stem.string() + ".cgns"); stream.write(data, bytes); }
                catch (...) { device->unmapBuffer(readback); throw; }
                device->unmapBuffer(readback);
            }
            if (config["diagnostics"].asBool())''')


def resources(renderer):
    source = renderer / SOURCE
    replace(source / "RtxdiResources.h", '    nvrhi::BufferHandle NeighborOffsetsBuffer;',
            '    nvrhi::BufferHandle NeighborOffsetsBuffer;\n'
            '    nvrhi::BufferHandle CgnsOffsetsBuffer;\n    nvrhi::BufferHandle CgnsStatisticsBuffer;')
    resource = source / "RtxdiResources.cpp"
    replace(resource, '#include "RtxdiResources.h"', '#include "RtxdiResources.h"\n#include <cmath>\n#include "App/CgnsMath.h"')
    replace(resource, '    NeighborOffsetsBuffer = device->createBuffer(neighborOffsetBufferDesc);', '''    NeighborOffsetsBuffer = device->createBuffer(neighborOffsetBufferDesc);
    auto cgnsOffsets = neighborOffsetBufferDesc;
    cgnsOffsets.byteSize = LAB_CGNS_DISK_SAMPLES * sizeof(LabCgnsOffset);
    cgnsOffsets.format = nvrhi::Format::RG32_FLOAT;
    cgnsOffsets.debugName = "CgnsOffsets";
    CgnsOffsetsBuffer = device->createBuffer(cgnsOffsets);
    nvrhi::BufferDesc statistics;
    statistics.byteSize = uint64_t(context.GetStaticParameters().RenderWidth) * context.GetStaticParameters().RenderHeight * 4;
    statistics.structStride = 4;
    statistics.canHaveUAVs = true;
    statistics.initialState = nvrhi::ResourceStates::UnorderedAccess;
    statistics.keepInitialState = true;
    statistics.debugName = "CgnsStatistics";
    CgnsStatisticsBuffer = device->createBuffer(statistics);''')
    replace(resource, '    m_neighborOffsetsInitialized = true;', '''    std::vector<LabCgnsOffset> cgnsOffsets(LAB_CGNS_DISK_SAMPLES);
    for (uint32_t i = 0; i < LAB_CGNS_DISK_SAMPLES; ++i) cgnsOffsets[i] = LabCgnsDiskOffset(i);
    commandList->writeBuffer(CgnsOffsetsBuffer, cgnsOffsets.data(), cgnsOffsets.size() * sizeof(LabCgnsOffset));
    m_neighborOffsetsInitialized = true;''')
    lighting = source / "RenderPasses/LightingPasses/LightingPasses.cpp"
    replace(lighting, '        nvrhi::BindingLayoutItem::TypedBuffer_SRV(21),',
            '        nvrhi::BindingLayoutItem::TypedBuffer_SRV(21),\n'
            '        nvrhi::BindingLayoutItem::TypedBuffer_SRV(26),\n'
            '        nvrhi::BindingLayoutItem::StructuredBuffer_UAV(31),')
    replace(lighting, '            nvrhi::BindingSetItem::TypedBuffer_SRV(21, resources.NeighborOffsetsBuffer),',
            '            nvrhi::BindingSetItem::TypedBuffer_SRV(21, resources.NeighborOffsetsBuffer),\n'
            '            nvrhi::BindingSetItem::TypedBuffer_SRV(26, resources.CgnsOffsetsBuffer),\n'
            '            nvrhi::BindingSetItem::StructuredBuffer_UAV(31, resources.CgnsStatisticsBuffer),')
    replace(lighting, 'context, m_DIReservoirBuffer);', 'context, m_DIReservoirBuffer, m_SpatialNeighborSelectionBuffer);')


def passes(renderer):
    source = renderer / SOURCE
    for extension in ("h", "cpp"):
        replace(source / f"RenderPasses/LightingPasses/ReSTIRDIRenderPasses.{extension}",
                'nvrhi::BufferHandle diReservoirBuffer)',
                'nvrhi::BufferHandle diReservoirBuffer, nvrhi::BufferHandle neighborSelectionBuffer)')
    replace(source / "RenderPasses/LightingPasses/ReSTIRDIRenderPasses.h", '    RayTracingPass m_spatialResamplingPass;',
            '    RayTracingPass m_spatialResamplingPass;\n    RayTracingPass m_cgnsSelectionPass;')
    path = source / "RenderPasses/LightingPasses/ReSTIRDIRenderPasses.cpp"
    replace(path, '    // Resampling shaders',
            '    m_cgnsSelectionPass.Init(device, shaderFactory, "app/LightingPasses/DI/CgnsSelectNeighbors.hlsl", {}, true, RTXDI_SCREEN_SPACE_GROUP_SIZE, bindingLayout, nullptr, bindlessLayout);\n'
            '    // Resampling shaders')
    replace(path, '            ExecuteRayTracingPass(commandList, m_spatialResamplingPass,', '''            if (context.GetSpatialResamplingParameters().pad1)
            {
                nvrhi::utils::BufferUavBarrier(commandList, neighborSelectionBuffer);
                ExecuteRayTracingPass(commandList, m_cgnsSelectionPass, false, "DINeighborSelection", dispatchSize, *m_profiler, ProfilerSection::DINeighborSelection, m_descriptorTable, m_bindingSet);
                nvrhi::utils::BufferUavBarrier(commandList, neighborSelectionBuffer);
            }
            ExecuteRayTracingPass(commandList, m_spatialResamplingPass,''')
    replace(source / "ProfilerSections.h", '        SpatialResampling,', '        DINeighborSelection,\n        SpatialResampling,')
    replace(source / "Profiler.cpp", '    "Spatial Resampling",', '    "DI - Neighbor Selection",\n    "Spatial Resampling",')
    replace(renderer / SHADERS / "CMakeLists.txt", '   LightingPasses/DI/SpatialResampling.hlsl',
            '   LightingPasses/DI/CgnsSelectNeighbors.hlsl\n   LightingPasses/DI/SpatialResampling.hlsl')
    replace(renderer / SHADERS / "Shaders.cfg", 'LightingPasses/DI/SpatialResampling.hlsl -T cs',
            'LightingPasses/DI/CgnsSelectNeighbors.hlsl -T cs -E main -D USE_RAY_QUERY=1\nLightingPasses/DI/SpatialResampling.hlsl -T cs')


def adapt(renderer, helper):
    for name in NAMES:
        shutil.copyfile(PAYLOAD / name, renderer / DI / name)
    shutil.copyfile(PAYLOAD / "CgnsMath.h", renderer / SOURCE / "App/CgnsMath.h")
    scene = renderer / SOURCE / "App/SceneRenderer.cpp"
    replace(scene, '"shaders/full-sample"', '"shaders/full-sample-cgns"')
    replace(scene, '    lab.Resolved(', '    lab.ConfigureCgns(m_isContext->GetReSTIRDIContext());\n    lab.Resolved(')
    configure(helper)
    resources(renderer)
    passes(renderer)
    replace(renderer / DI / "SpatialResampling.hlsl", '#include <Rtxdi/DI/SpatialResampling.hlsli>',
            '#include "Cgns.hlsli"\n#include "CgnsSpatialResampling.hlsli"')
    spatial = renderer / "Libraries/Rtxdi/Include/Rtxdi/DI/SpatialResampling.hlsli"
    (renderer / DI / "CgnsSpatialResampling.hlsli").write_text(adapt_spatial(spatial.read_text(encoding="utf-8")), encoding="utf-8")
