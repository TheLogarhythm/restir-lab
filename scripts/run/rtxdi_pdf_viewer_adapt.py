"""Checked viewer/UI adaptations, separate from the PDF-similarity algorithm."""
from pathlib import Path
import shutil

SOURCE = "Samples/FullSample/Source/"
PAYLOAD = Path(__file__).resolve().parent / "rtxdi_experiments"
FILES = [SOURCE + "UserInterface.cpp", SOURCE + "UserInterface.h"]
CREATED = [SOURCE + "App/PdfViewerState.h"]
SUPPORT = [Path(__file__), PAYLOAD / "PdfViewerState.h"]

def adapt(renderer, helper, replace):
    """Viewer-only branches leave the controlled experiment lifecycle unchanged."""
    shutil.copy2(PAYLOAD / "PdfViewerState.h", helper.parent / "PdfViewerState.h")
    replace(helper, '#pragma once', '#pragma once\n#include "PdfViewerState.h"')
    replace(helper, '    Json::Value config;', '    Json::Value config;\n    PdfViewerState m_pdfViewer;')
    replace(helper, '        output = config["output"].asString();',
            '        m_pdfViewer.enabled = config["definition"].get("pdf_similarity", false).asBool();\n'
            '        output = config["output"].asString();\n        if (!IsViewer()) {')
    replace(helper, "        timings << '\\n' << std::setprecision(9);", "        timings << '\\n' << std::setprecision(9);\n        }")
    replace(helper, '    bool IsFileScene() const', '''    bool IsViewer() const { return config.get("interactive", false).asBool(); }
    void UpdateViewer(UIData& ui) {
        m_pdfViewer.Update(ui.pdfSimilarity, ui.resetAccumulation || ui.resetISContext, ui.CanUsePdfSimilarity());
        if (m_pdfViewer.frame == 0) ui.resetAccumulation = true;
    }
    const char* ViewerTitle() const {
        return m_pdfViewer.enabled ? "RTXDI | PDF Similarity (DI): ON"
                                   : "RTXDI | PDF Similarity (DI): OFF";
    }
    bool IsFileScene() const''')
    replace(helper, 'return config["frames"][index];', 'return config["frames"][IsViewer() ? 0 : index];')
    replace(helper, 'return Frame()["reset"].asBool();', 'return IsViewer() ? m_pdfViewer.frame == 0 : Frame()["reset"].asBool();')
    replace(helper, 'return index == config["frames"].size();',
            'return IsViewer() ? (config.get("viewer_frames", 0).asUInt() > 0 && index >= config["viewer_frames"].asUInt()) : index == config["frames"].size();')
    replace(helper, '        auto position = Vector(Frame()["position"]);',
            '        if (IsViewer() && index > 0) return Frame()["sampling_frame"].asUInt() + m_pdfViewer.frame;\n'
            '        auto position = Vector(Frame()["position"]);')
    replace(helper, '        ui.verticalFov =',
            '        if (IsViewer()) { ui.showUI = true; ui.pdfViewer = true; ui.pdfSimilarity = m_pdfViewer.enabled; }\n'
            '        ui.verticalFov =')
    replace(helper, '        // Serialize frames so timing queries belong unambiguously to this frame.',
            '        if (IsViewer()) { m_pdfViewer.Advance(); ++index; return; }\n'
            '        // Serialize frames so timing queries belong unambiguously to this frame.')
    path = renderer / SOURCE / "App/SceneRenderer.cpp"
    replace(path, '    m_scene->FinishedLoading(GetFrameIndex());',
            '    m_scene->FinishedLoading(GetFrameIndex());\n'
            '    if (m_labExperiment->IsViewer()) m_ui.resetAccumulation = true;')
    replace(path, '    SetupRenderPasses(renderWidth, renderHeight, exposureResetRequired);',
            '    SetupRenderPasses(renderWidth, renderHeight, exposureResetRequired);\n'
            '    if (lab.IsViewer() && m_rtxdiResourcesCreated)\n    {\n'
            '        m_ui.resetAccumulation = true;\n        lab.UpdateViewer(m_ui);\n'
            '        effectiveFrameIndex = lab.Begin(m_camera);\n        m_prevViewValid = false;\n    }')
    replace(path, '    auto& lab = *m_labExperiment;\n    effectiveFrameIndex = lab.Begin(m_camera);', '''    auto& lab = *m_labExperiment;
    if (lab.IsViewer())
    {
        RunBenchmarkAnimation(activeCamera, effectiveFrameIndex);
        auto* window = GetDeviceManager()->GetWindow();
        lab.UpdateViewer(m_ui);
        if (window) glfwSetWindowTitle(window, lab.ViewerTitle());
    }
    effectiveFrameIndex = lab.Begin(m_camera);''')
    ui_header = renderer / SOURCE / "UserInterface.h"
    replace(ui_header, '#pragma once', '#pragma once\n#include "App/PdfViewerState.h"')
    replace(ui_header, '    bool showUI = true;',
            '    bool showUI = true;\n    bool pdfViewer = false;\n'
            '''    bool pdfSimilarity = true;
    bool CanUsePdfSimilarity() const {
        return PdfViewerState::Supported(lightingSettings.directLightingMode == DirectLightingMode::ReStir,
            restirDI.resamplingMode == rtxdi::ReSTIRDI_ResamplingMode::Spatial
                || restirDI.resamplingMode == rtxdi::ReSTIRDI_ResamplingMode::TemporalAndSpatial,
            restirDI.initialSamplingParams.enableInitialVisibility,
            restirDI.spatialResamplingParams.biasCorrectionMode == ReSTIRDI_SpatialBiasCorrectionMode::Raytraced,
            restirDIStaticParams.CheckerboardSamplingMode != rtxdi::CheckerboardMode::Off);
    }''')
    replace(renderer / SOURCE / "UserInterface.cpp", '            if (ImGui::TreeNode("ReGIR Presampling"))', '''            if (m_ui.pdfViewer)
            {
                bool supported = m_ui.CanUsePdfSimilarity();
                ImGui::BeginDisabled(!supported);
                samplingSettingsChanged |= ImGui::Checkbox("PDF Similarity", &m_ui.pdfSimilarity);
                if (ImGui::Button("Reset history")) m_ui.resetAccumulation = true;
                ImGui::EndDisabled();
                ShowHelpMarker("Applies to primary ReSTIR DI only. Changing it resets rendering history.");
                if (!supported)
                    ImGui::TextWrapped("PDF Similarity inactive: requires Spatial or Temporal + Spatial, "
                        "Initial Visibility, Ray Traced spatial correction and no checkerboard.");
            }

            if (ImGui::TreeNode("ReGIR Presampling"))''')
    replace(path, '    m_ui.lightingSettings.enableRayCounts = false;\n    m_profiler->EnableProfiler(true);',
            '    if (!lab.IsViewer()) { m_ui.lightingSettings.enableRayCounts = false; m_profiler->EnableProfiler(true); }')
    replace(path, '    m_profiler->EnableAccumulation(false);',
            '    if (lab.IsViewer()) m_profiler->ResolvePreviousFrame();\n    else m_profiler->EnableAccumulation(false);')
    replace(path, '    lab.ApplySun(*m_sunLight);', '    if (!lab.IsViewer()) lab.ApplySun(*m_sunLight);')
    replace(path, '    // Denoising and its input formatting are excluded from this experiment.',
            '    if (lab.IsViewer())\n    {\n'
            '        m_DLSSRRInputFormattingPass->Render(m_commandList, m_view);\n'
            '        Denoiser(lightingSettings);\n    }')
    replace(path, '    if (GetDeviceManager()->GetWindow())\n        m_CommonPasses->BlitTexture(m_commandList, framebuffer, m_renderTargets->HdrColor, &m_bindingCache);',
            '    if (lab.IsViewer())\n    {\n        ResolveAA(m_commandList, accumulationWeight);\n'
            '        Bloom();\n        ReferenceImage(cameraIsStatic);\n'
            '        ToneMapping(exposureResetRequired);\n        DebugPathViz();\n'
            '        FinalFramebufferOutput(framebuffer);\n    }\n'
            '    else if (GetDeviceManager()->GetWindow())\n'
            '        m_CommonPasses->BlitTexture(m_commandList, framebuffer, m_renderTargets->HdrColor, &m_bindingCache);')
    replace(path, '    lab.End(GetDevice(),',
            '    if (lab.IsViewer()) ProcessScreenshotFrame();\n    lab.End(GetDevice(),')
    replace(path, '        m_commandList->clearBufferUInt(m_rtxdiResources->PdfDirectionBuffer, 0);',
            '        m_commandList->clearBufferUInt(m_rtxdiResources->PdfDirectionBuffer, 0);\n'
            '        if (lab.IsViewer())\n        {\n'
            '            m_commandList->clearBufferUInt(m_rtxdiResources->GIReservoirBuffer, 0);\n'
            '            m_commandList->clearBufferUInt(m_rtxdiResources->PTReservoirBuffer, 0);\n        }')
    replace(helper, '        record["ray_counts"] = false;',
            '        record["ray_counts"] = IsViewer() && bool(ui.lightingSettings.enableRayCounts);\n'
            '        if (IsViewer())\n        {\n'
            '            record["estimator"] = "interactive_rtxdi";\n'
            '            record["direct_mode"] = uint32_t(ui.lightingSettings.directLightingMode);\n'
            '            record["indirect_mode"] = uint32_t(ui.indirectLightingMode);\n        }')
    replace(helper, '        record["source_format"] =',
            '        if (IsViewer()) record["display_passes"] = "RTXDI denoising, AA, bloom, tone mapping and debug output per UI settings";\n'
            '        record["source_format"] =')
