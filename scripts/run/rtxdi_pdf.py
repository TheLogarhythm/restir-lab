"""Temporary, checked adaptations of the pinned FullSample for PDF similarity."""
from pathlib import Path
import shutil
import rtxdi_pdf_viewer_adapt as viewer

HERE = Path(__file__).resolve().parent
PAYLOAD = HERE / "rtxdi_experiments"
SOURCE = "Samples/FullSample/Source/"
SHADERS = "Samples/FullSample/Shaders/LightingPasses/DI/"
FILES = [SOURCE + name for name in (
    "RtxdiResources.cpp", "RtxdiResources.h",
    "RenderPasses/LightingPasses/LightingPasses.cpp",
    "RenderPasses/LightingPasses/LightingPasses.h",
    "RenderPasses/LightingPasses/ReSTIRDIRenderPasses.cpp",
    "RenderPasses/LightingPasses/ReSTIRDIRenderPasses.h")]
FILES += [SHADERS + name for name in ("GenerateInitialSamples.hlsl", "SpatialResampling.hlsl")]
FILES += viewer.FILES
CREATED = [SHADERS + name for name in ("PdfSimilarity.hlsli", "PdfSimilarityMath.h", "PdfReservoirMath.h", "PdfSpatialResampling.hlsli")]
CREATED += viewer.CREATED
SUPPORT = [Path(__file__), PAYLOAD / "PdfSimilarity.hlsli", PAYLOAD / "PdfSimilarityMath.h", PAYLOAD / "PdfReservoirMath.h", *viewer.SUPPORT]


def replace(path, old, new, count=1):
    text = path.read_text(encoding="utf-8")
    if text.count(old) != count:
        raise RuntimeError(f"Unexpected pinned source at {path}: expected {count} matches")
    path.write_text(text.replace(old, new), encoding="utf-8")


def adapt(renderer, helper):
    source = renderer / SOURCE
    shader = renderer / SHADERS
    for name in ("PdfSimilarity.hlsli", "PdfSimilarityMath.h", "PdfReservoirMath.h"):
        shutil.copy2(PAYLOAD / name, shader / name)
    replace(source / "App/SceneRenderer.cpp", '"shaders/full-sample"', '"shaders/full-sample-pdf"')
    replace(source / "App/SceneRenderer.cpp", '    lab.Resolved(',
            '    lab.ConfigurePdf(m_isContext->GetReSTIRDIContext());\n    lab.Resolved(')
    replace(source / "App/SceneRenderer.cpp", '        m_commandList->clearBufferUInt(m_rtxdiResources->DIReservoirBuffer, 0);',
            '        m_commandList->clearBufferUInt(m_rtxdiResources->DIReservoirBuffer, 0);\n'
            '        m_commandList->clearBufferUInt(m_rtxdiResources->PdfDirectionBuffer, 0);')
    replace(helper, '    void ApplySun(', '''    void ConfigurePdf(rtxdi::ReSTIRDIContext& di) const
    {
        bool enabled = IsViewer() ? m_pdfViewer.enabled : config["definition"].get("pdf_similarity", false).asBool();
        auto mode = di.GetResamplingMode();
        auto spatial = di.GetSpatialResamplingParameters();
        bool supported = PdfViewerState::Supported(true,
            mode == rtxdi::ReSTIRDI_ResamplingMode::Spatial || mode == rtxdi::ReSTIRDI_ResamplingMode::TemporalAndSpatial,
            di.GetInitialSamplingParameters().enableInitialVisibility,
            spatial.biasCorrectionMode == ReSTIRDI_SpatialBiasCorrectionMode::Raytraced,
            di.GetStaticParameters().CheckerboardSamplingMode != rtxdi::CheckerboardMode::Off);
        if (IsViewer()) enabled &= supported;
        else if (enabled && !supported)
            throw std::runtime_error("PDF similarity requires unfused spatial DI, initial visibility, raytraced correction and no checkerboard");
        spatial.pad1 = enabled; // App-private flag; preserves the pinned constant-buffer ABI.
        di.SetSpatialResamplingParameters(spatial);
    }

    void ApplySun(''')
    replace(helper, '        record["scene_id"] = config["scene_id"];',
            '        record["scene_id"] = config["scene_id"];\n'
            '        record["pdf_similarity"] = bool(p.spatialResamplingParams.pad1);\n'
            '        record["pdf_direction_bytes"] = uint64_t(di.GetStaticParameters().RenderWidth) * di.GetStaticParameters().RenderHeight * 64;')

    replace(source / "RtxdiResources.h", '    nvrhi::BufferHandle DIReservoirBuffer;',
            '    nvrhi::BufferHandle DIReservoirBuffer;\n    nvrhi::BufferHandle PdfDirectionBuffer;')
    replace(source / "RtxdiResources.cpp", '    DIReservoirBuffer = device->createBuffer(diReservoirBufferDesc);',
            '    DIReservoirBuffer = device->createBuffer(diReservoirBufferDesc);\n'
            '    auto pdfDesc = diReservoirBufferDesc;\n'
            '    pdfDesc.byteSize = uint64_t(context.GetStaticParameters().RenderWidth) * context.GetStaticParameters().RenderHeight * 64;\n'
            '    pdfDesc.structStride = 32;\n    pdfDesc.debugName = "PdfDirectionBuffer";\n'
            '    PdfDirectionBuffer = device->createBuffer(pdfDesc);')
    lighting = source / "RenderPasses/LightingPasses/LightingPasses.cpp"
    replace(lighting, '        nvrhi::BindingLayoutItem::StructuredBuffer_UAV(0),',
            '        nvrhi::BindingLayoutItem::StructuredBuffer_UAV(0),\n        nvrhi::BindingLayoutItem::StructuredBuffer_UAV(31),')
    replace(lighting, '            nvrhi::BindingSetItem::StructuredBuffer_UAV(0, resources.DIReservoirBuffer),',
            '            nvrhi::BindingSetItem::StructuredBuffer_UAV(0, resources.DIReservoirBuffer),\n'
            '            nvrhi::BindingSetItem::StructuredBuffer_UAV(31, resources.PdfDirectionBuffer),')
    replace(lighting, '    m_DIReservoirBuffer = resources.DIReservoirBuffer;',
            '    m_DIReservoirBuffer = resources.DIReservoirBuffer;\n    m_PdfDirectionBuffer = resources.PdfDirectionBuffer;')
    replace(lighting, 'context, m_DIReservoirBuffer);', 'context, m_DIReservoirBuffer, m_PdfDirectionBuffer);')
    replace(source / "RenderPasses/LightingPasses/LightingPasses.h", '    nvrhi::BufferHandle m_DIReservoirBuffer;',
            '    nvrhi::BufferHandle m_DIReservoirBuffer;\n    nvrhi::BufferHandle m_PdfDirectionBuffer;')
    for suffix in ("h", "cpp"):
        replace(source / f"RenderPasses/LightingPasses/ReSTIRDIRenderPasses.{suffix}",
                'nvrhi::BufferHandle diReservoirBuffer)',
                'nvrhi::BufferHandle diReservoirBuffer, nvrhi::BufferHandle pdfDirectionBuffer)')
    passes = source / "RenderPasses/LightingPasses/ReSTIRDIRenderPasses.cpp"
    replace(passes, '        if (context.GetResamplingMode() == rtxdi::ReSTIRDI_ResamplingMode::Temporal ||',
            '        nvrhi::utils::BufferUavBarrier(commandList, pdfDirectionBuffer);\n\n'
            '        if (context.GetResamplingMode() == rtxdi::ReSTIRDI_ResamplingMode::Temporal ||')
    replace(shader / "GenerateInitialSamples.hlsl", '#include <Rtxdi/DI/ReservoirStorage.hlsli>',
            '#include <Rtxdi/DI/ReservoirStorage.hlsli>\n#include "PdfSimilarity.hlsli"')
    replace(shader / "GenerateInitialSamples.hlsl", '    RTXDI_StoreDIReservoir(reservoir,',
            '    if (LabPdfEnabled() && all(pixelPosition < uint2(g_Const.view.viewportSize)))\n'
            '        LabUpdateDirection(pixelPosition, surface, reservoir, lightSample);\n\n'
            '    RTXDI_StoreDIReservoir(reservoir,')
    replace(shader / "SpatialResampling.hlsl", '#include <Rtxdi/DI/SpatialResampling.hlsli>',
            '#include "PdfSimilarity.hlsli"\n#include "PdfSpatialResampling.hlsli"')
    # Generate a local adaptation, keeping the vendor library itself untouched.
    spatial = shader / "PdfSpatialResampling.hlsli"
    spatial.write_text(adapt_spatial((renderer / "Libraries/Rtxdi/Include/Rtxdi/DI/SpatialResampling.hlsli").read_text(encoding="utf-8")), encoding="utf-8")
    viewer.adapt(renderer, helper, replace)


def adapt_spatial(text):
    """Apply identical fractional candidate counts in selection and normalization."""
    def change(old, new, count=1):
        nonlocal text
        if text.count(old) != count:
            raise RuntimeError(f"Unexpected pinned spatial source: expected {count} matches")
        text = text.replace(old, new)
    change('if (!RTXDI_IsValidNeighbor(', 'if (!LabPdfEnabled() && !RTXDI_IsValidNeighbor(', 2)
    change('if (sparams.enableMaterialSimilarityTest &&', 'if (!LabPdfEnabled() && sparams.enableMaterialSimilarityTest &&', 2)
    change('        neighborSample.spatialDistance += spatialOffset;',
           '        neighborSample.M *= LabSpatialWeight(pixelPosition, uint2(idx), centerSurface, neighborSurface);\n'
           '        neighborSample.spatialDistance += spatialOffset;', 2)
    change('                piSum += ps * neighborSample.M;',
           '                neighborSample.M *= LabSpatialWeight(pixelPosition, uint2(idx), centerSurface, neighborSurface);\n'
           '                piSum += ps * neighborSample.M;')
    return text
