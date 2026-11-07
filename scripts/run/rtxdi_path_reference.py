"""Conventional PT reference integration, isolated from historical DI reference."""
from pathlib import Path
import shutil
import build_rtxdi_experiments as base
from rtxdi_transport import replace_checked, edit, preserve_invalid_radiance
import rtxdi_transport_fixes as fixes

HERE = Path(__file__).resolve().parent
PAYLOAD = HERE / "rtxdi_experiments"
SOURCE = "Samples/FullSample/Source/"
FILES = [SOURCE + "RenderPasses/LightingPasses/LightingPasses.h", "Samples/FullSample/Shaders/CompositingPass.hlsl"]
SURFACE = fixes.SHADERS + fixes.BRIDGE + "RAB_Surface.hlsli"
FILES += [SURFACE]
FILES += fixes.ENVIRONMENT_FILES
FILES += [*fixes.SEGMENT_FILES, fixes.SHADERS + fixes.BRIDGE + "PathTracer/RAB_PathTracer.hlsli"]
CREATED = [fixes.SHADERS + fixes.BRIDGE + "TransportMath.hlsli", fixes.SEGMENT_CREATED]
SUPPORT = [Path(__file__), PAYLOAD / "PathReference.hlsl", Path(fixes.__file__), PAYLOAD / "TransportMath.hlsli", PAYLOAD / "OpaqueSegment.hlsli"]


def adapt():
    base.adapt_reference()
    preserve_invalid_radiance(base.RENDERER)
    fixes.adapt_segments(base.RENDERER)
    path = base.RENDERER / fixes.SHADERS / fixes.BRIDGE / "PathTracer/RAB_PathTracer.hlsli"
    path.write_text(fixes.adapt_trace_next_bounce(path.read_text(encoding="utf-8")), encoding="utf-8")
    fixes.adapt_environment(base.RENDERER)
    surface = base.RENDERER / SURFACE
    surface.write_text(fixes.adapt_surface(surface.read_text(encoding="utf-8")), encoding="utf-8")
    shutil.copyfile(PAYLOAD / "TransportMath.hlsli", base.RENDERER / CREATED[0])
    source = base.RENDERER / SOURCE
    scene = source / "App/SceneRenderer.cpp"
    edit(scene, '"shaders/full-sample-reference"', '"shaders/full-sample-path-reference"')
    helper = base.DEST
    edit(helper, '        if (!IsReference()) throw std::runtime_error("Reference executable requires reference configuration");',
        '''        if (!IsReference() || config["reference"]["estimator"].asString() != "conventional_path_tracing")
            throw std::runtime_error("Path reference executable requires a path-spp configuration");
        const auto depth = config["transport"]["max_surface_scattering"].asUInt();
        if (depth < 1 || depth > 2 || config["reference"]["paths_per_iteration"].asUInt() != 1)
            throw std::runtime_error("Unsupported path reference scattering/sample count");''')
    edit(helper, '    void ApplySun(', '''    void ConfigurePathReference(rtxdi::ReSTIRDIContext& di) const
    {
        if (di.GetResamplingMode() != rtxdi::ReSTIRDI_ResamplingMode::None)
            throw std::runtime_error("Path reference cannot use reservoirs");
        auto s = di.GetSpatialResamplingParameters();
        s.pad1 = config["transport"]["max_surface_scattering"].asUInt();
        di.SetSpatialResamplingParameters(s);
    }

    void ApplySun(''')
    edit(helper, '        ui.enableAnimations = false;', '''        ui.lightingSettings.enableDenoiserPSR = false;
        ui.lightingSettings.usePSRMvecForResampling = false;
        ui.lightingSettings.updatePSRwithResampling = false;
        ui.enableAnimations = false;''')
    edit(helper, 'IsReference() ? "conventional_light_sampling" : "restir_di"',
         'IsReference() ? "conventional_path_tracing" : "restir_di"')
    edit(helper, '        auto stream = Open(output / "resolved.json");', '''        record["max_surface_scattering"] = p.spatialResamplingParams.pad1;
        record["paths_per_iteration"] = 1;
        record["reference_mis"] = "off-disjoint-support";
        record["reference_roulette"] = false;
        record["reference_cutoff"] = 0.0;
        record["reference_glass"] = "legacy-DI";
        auto stream = Open(output / "resolved.json");''')
    edit(helper, '            std::ostringstream name;', '''            const auto completed = config["reference"].get("resume_batches", 0).asUInt() + index + 1;
            if (completed != Frame()["frame"].asUInt() ||
                Frame()["sampling_frame"].asUInt() != config["seed"].asUInt() * 1048576u + completed - 1)
                throw std::runtime_error("Path reference sample index/count diverged");
            Json::Value checkpoint;
            checkpoint["completed_spp"] = completed;
            checkpoint["next_sample_index"] = completed;
            checkpoint["paths_per_iteration"] = 1;
            { auto file = Open(output / "path-checkpoint.json"); file << checkpoint << '\\n'; }
            std::ostringstream name;''')
    edit(scene, '    lab.Resolved(', '    lab.ConfigurePathReference(m_isContext->GetReSTIRDIContext());\n    lab.Resolved(')
    # Direct shading normally needs no secondary material/environment state.
    # The reference uses that dispatch for an ordinary path loop, so fill both.
    cpp = source / "RenderPasses/LightingPasses/LightingPasses.cpp"
    text = cpp.read_text(encoding="utf-8")
    begin = text.index("void LightingPasses::PrepareForLightSampling(")
    end = text.index("\nvoid LightingPasses::RenderDirectLighting", begin)
    body = text[begin:end]
    body = replace_checked(body, "    const RenderSettings& localSettings,",
        "    const RenderSettings& localSettings,\n    const EnvironmentLight& environmentLight,")
    body = replace_checked(body, "    commandList->writeBuffer(m_constantBuffer, &constants, sizeof(constants));", '''    constants.brdfPT.materialOverrideParams.roughnessOverride = -1.f;
    constants.brdfPT.materialOverrideParams.metalnessOverride = -1.f;
    constants.brdfPT.materialOverrideParams.minSecondaryRoughness = 0.f;
    constants.sceneConstants.enableEnvironmentMap = environmentLight.textureIndex >= 0;
    constants.sceneConstants.environmentMapTextureIndex = environmentLight.textureIndex >= 0 ? environmentLight.textureIndex : 0;
    constants.sceneConstants.environmentScale = environmentLight.radianceScale.x;
    constants.sceneConstants.environmentRotation = environmentLight.rotation;
    commandList->writeBuffer(m_constantBuffer, &constants, sizeof(constants));''')
    cpp.write_text(text[:begin] + body + text[end:], encoding="utf-8")
    header = source / "RenderPasses/LightingPasses/LightingPasses.h"
    text = header.read_text(encoding="utf-8")
    begin = text.index("    void PrepareForLightSampling(")
    end = text.index(";", begin)
    body = replace_checked(text[begin:end], "        const RenderSettings& localSettings,",
                           "        const RenderSettings& localSettings,\n        const EnvironmentLight& environmentLight,")
    header.write_text(text[:begin] + body + text[end:], encoding="utf-8")
    edit(scene, "            lightingSettings,\n            /* enableAccumulation = */",
         "            lightingSettings,\n            *m_environmentLight,\n            /* enableAccumulation = */")
    shutil.copyfile(PAYLOAD / "PathReference.hlsl", base.RENDERER / base.REFERENCE_FILES[-1])
