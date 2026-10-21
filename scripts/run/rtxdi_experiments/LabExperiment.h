// Project integration for pinned RTXDI: deterministic frames and unprocessed readback.
#pragma once
#include <donut/core/json.h>
#include <donut/engine/SceneGraph.h>
#include <cmath>
#include <cstdlib>
#include <fstream>
#include <iomanip>
#include <memory>
#include <stdexcept>
#include <unordered_map>
#include <vector>

void FillReSTIRDIConstants(RTXDI_Parameters&, const rtxdi::ReSTIRDIContext&, const RTXDI_LightBufferParameters&);

class LabExperiment
{
    Json::Value config;
    Json::ArrayIndex index = 0;
    std::filesystem::path output;
    std::ofstream timings;
    std::ofstream frameStates;
    Json::Value frameState;
    std::unordered_map<std::string, std::pair<std::shared_ptr<donut::engine::Material>, float>> originalMaterials;
    std::string loadedScene;
    static constexpr const char* sections[] = {
        "tlas", "environment", "gbuffer", "mesh", "light_pdf", "presample_lights",
        "presample_environment", "regir", "initial", "temporal", "spatial", "shading",
        "brdf", "secondary", "gi_temporal", "gi_spatial", "gi_fused", "gi_shading",
        "pt_initial", "pt_temporal", "pt_neighbor", "pt_spatial", "pt_duplication",
        "pt_smooth_duplication", "pt_shading", "gradients", "denoising", "glass", "resolve", "gpu"
    };

    static std::ofstream Open(const std::filesystem::path& path)
    {
        std::ofstream stream;
        stream.exceptions(std::ios::failbit | std::ios::badbit);
        stream.open(path, std::ios::binary);
        return stream;
    }
    static dm::float3 Vector(const Json::Value& v)
    {
        return dm::float3(v[0].asFloat(), v[1].asFloat(), v[2].asFloat());
    }
    static Json::Value JsonVector(const dm::float3& v)
    {
        Json::Value result(Json::arrayValue);
        result.append(v.x); result.append(v.y); result.append(v.z);
        return result;
    }

public:
    LabExperiment()
    {
        const char* path = std::getenv("RTXDI_EXPERIMENT_CONFIG");
        if (!path) throw std::runtime_error("Use rtxdi_reuse.py to launch this experiment build");
        std::ifstream stream(path);
        if (!stream) throw std::runtime_error("Cannot read experiment configuration");
        stream >> config;
        if (config["schema_version"].asUInt() != 3 || !config["scene"].isObject())
            throw std::runtime_error("Unsupported experiment configuration");
#ifdef LAB_REFERENCE_BUILD
        if (!IsReference()) throw std::runtime_error("Reference executable requires reference configuration");
#else
        if (IsReference()) throw std::runtime_error("Build and use FullSampleReference for reference rendering");
#endif
        if (!config["frames"].isArray() || config["frames"].empty())
            throw std::runtime_error("Experiment has no frame sequence");
        output = config["output"].asString();
        timings = Open(output / "timings.csv");
        frameStates = Open(output / "resolved-frames.jsonl");
        timings << "frame,sampling_frame,capture,history_reset";
        for (auto section : sections) timings << ',' << section << "_ms";
        timings << '\n' << std::setprecision(9);
    }

    bool IsFileScene() const { return config["scene"]["source"]["kind"].asString() == "file"; }
    bool HasProceduralEnvironment() const { return config["scene"]["lighting"]["environment"].asString() == "procedural"; }
    bool IsReference() const { return config.isMember("reference"); }
    float AccumulationWeight() const { return 1.f / float(config["reference"].get("resume_batches", 0).asUInt() + index + 1); }
    void RestoreAccumulation(nvrhi::ICommandList* command, const RenderTargets& targets) const
    {
        if (index != 0 || !config["reference"].get("resume_batches", 0).asUInt()) return;
        auto desc = targets.AccumulatedColor->getDesc();
        if (desc.format != nvrhi::Format::RGBA32_FLOAT)
            throw std::runtime_error("Reference resume requires RGBA32_FLOAT");
        std::vector<float> pixels(size_t(desc.width) * desc.height * 4);
        std::ifstream stream(output / "resume.rgba32f", std::ios::binary);
        const auto bytes = std::streamsize(pixels.size() * sizeof(float));
        if (!stream.read(reinterpret_cast<char*>(pixels.data()), bytes) || stream.peek() != EOF)
            throw std::runtime_error("Missing or invalid reference resume image");
        command->writeTexture(targets.AccumulatedColor, 0, 0, pixels.data(), size_t(desc.width) * 16);
    }

    std::filesystem::path AssetRoot() const
    {
        return std::filesystem::path(config["repository_root"].asString()) / config["scene"]["source"]["root"].asString();
    }
    std::filesystem::path Entry() const { return config["scene"]["source"]["entry"].asString(); }
    void SetScenePath(const std::filesystem::path& path) { loadedScene = path.relative_path().generic_string(); }
    float EmissiveScale() const { return config["scene"]["lighting"]["emissive_scale"].asFloat(); }

    void ApplySettings(UIData& ui) const
    {
        ui.enableAnimations = false;
        ui.verticalFov = config["scene"]["camera"]["vertical_fov"].asFloat();
        ui.environmentIntensityBias = config["scene"]["lighting"]["environment_intensity_ev"].asFloat();
        ui.environmentRotation = config["scene"]["lighting"]["environment_rotation_degrees"].asFloat();
    }

    void ConfigureEnvironment(SampleScene& scene, UIData& ui, donut::engine::DirectionalLight& sun) const
    {
        const auto kind = config["scene"]["lighting"]["environment"].asString();
        if (kind == "none") { ui.environmentMapIndex = -1; sun.irradiance = 0.f; }
        else if (kind == "file")
        {
            const auto name = config["scene"]["lighting"]["environment_map"].asString();
            auto& maps = scene.GetEnvironmentMaps();
            maps.push_back((std::filesystem::path("/Assets/Experiment") / name).generic_string());
            ui.environmentMapIndex = int(maps.size()) - 1;
        }
        ui.environmentMapDirty = 2;
    }

    void ApplySun(donut::engine::DirectionalLight& sun) const
    {
        // Keep the procedural sky intact; disable the separate analytic light before light preparation.
        if (!config["definition"].get("analytic_sun", true).asBool()
            || !HasProceduralEnvironment()) sun.irradiance = 0.f;
    }

    const Json::Value& Frame() const { return config["frames"][index]; }
    bool Reset() const { return Frame()["reset"].asBool(); }
    bool Done() const { return index == config["frames"].size(); }

    bool HasLogicalTime() const { return Frame().isMember("logical_time_seconds"); }
    float FrameElapsedSeconds() const
    {
        if (!HasLogicalTime() || index == 0) return 0.f;
        const double previous = config["frames"][index - 1]["logical_time_seconds"].asDouble();
        const double elapsed = Frame()["logical_time_seconds"].asDouble() - previous;
        if (!std::isfinite(elapsed) || elapsed < 0.)
            throw std::runtime_error("Logical scene time must be finite and nondecreasing");
        return float(elapsed);
    }

    uint32_t Begin(donut::app::FirstPersonCamera& camera)
    {
        auto position = Vector(Frame()["position"]);
        camera.LookAt(position, position + Vector(Frame()["direction"]), Vector(Frame()["up"]));
        frameState = Json::Value(Json::objectValue);
        frameState["frame"] = Frame()["frame"];
        frameState["sampling_frame"] = Frame()["sampling_frame"];
        frameState["position"] = JsonVector(camera.GetPosition());
        frameState["direction"] = JsonVector(camera.GetDir());
        frameState["up"] = JsonVector(camera.GetUp());
        frameState["history_reset"] = Reset();
        if (HasLogicalTime()) frameState["logical_time_seconds"] = Frame()["logical_time_seconds"];
        return Frame()["sampling_frame"].asUInt();
    }

    void ApplyLighting(donut::engine::SceneGraph& scene)
    {
        if (!Frame().isMember("lighting")) return;
        const auto& lighting = Frame()["lighting"];
        const auto multiplierValue = lighting["emissive_intensity_multiplier"];
        if (!lighting.isObject() || lighting.size() != 2 || !lighting["material"].isString()
            || lighting["material"].asString().empty() || !multiplierValue.isNumeric())
            throw std::runtime_error("Invalid per-frame material lighting state");
        const double multiplier = multiplierValue.asDouble();
        if (!std::isfinite(multiplier) || multiplier <= 0.)
            throw std::runtime_error("Material intensity multiplier must be positive and finite");
        const auto name = lighting["material"].asString();
        std::shared_ptr<donut::engine::Material> target;
        unsigned matches = 0;
        for (const auto& material : scene.GetMaterials())
            if (material->name == name) { target = material; ++matches; }
        if (matches != 1)
            throw std::runtime_error("Lighting material must resolve to exactly one existing material: " + name);
        auto original = originalMaterials.find(name);
        if (original == originalMaterials.end())
            original = originalMaterials.emplace(name, std::make_pair(target, target->emissiveIntensity)).first;
        if (original->second.first != target || !std::isfinite(original->second.second)
            || original->second.second <= 0.f || !dm::any(target->emissiveColor != 0.f))
            throw std::runtime_error("Lighting target must remain the same positive emissive material");
        const float intensity = float(double(original->second.second) * multiplier);
        if (!std::isfinite(intensity) || intensity <= 0.f
            || !target->SetProperty("emissiveIntensity", dm::float4(intensity, 0.f, 0.f, 0.f)))
            throw std::runtime_error("Cannot set positive material emissive intensity");
        uint64_t triangles = 0, geometries = 0;
        for (const auto& instance : scene.GetMeshInstances())
            for (const auto& geometry : instance->GetMesh()->geometries)
                if (geometry->material == target)
                { triangles += geometry->numIndices / 3; ++geometries; }
        if (!triangles) throw std::runtime_error("Lighting material has no emitting triangles");
        frameState["lighting"] = lighting;
        auto& resolved = frameState["material_update"];
        resolved["material_id"] = target->materialID;
        resolved["original_emissive_intensity"] = original->second.second;
        resolved["emissive_intensity"] = target->emissiveIntensity;
        resolved["emissive_color"] = JsonVector(target->emissiveColor);
        resolved["emitting_geometries"] = Json::UInt64(geometries);
        resolved["emitting_triangles"] = Json::UInt64(triangles);
        resolved["dirty_before_upload"] = target->dirty;
    }

    template<typename LightPreparation>
    void RecordFrame(const rtxdi::ImportanceSamplingContext& context, const LightPreparation& preparation)
    {
        if (!frameStates.is_open()) return;
        const auto& lights = context.GetLightBufferParameters();
        const auto& correspondence = preparation.GetLabCorrespondence();
        frameState["local_lights"] = lights.localLightBufferRegion.numLights;
        frameState["local_light_buffer_offset"] = lights.localLightBufferRegion.firstLightIndex;
        frameState["infinite_lights"] = lights.infiniteLightBufferRegion.numLights;
        frameState["environment_present"] = lights.environmentLightParams.lightPresent;
        auto& record = frameState["light_correspondence"];
        record["emissive_triangles"] = correspondence.emissiveTriangles;
        record["mapped_emissive_triangles"] = correspondence.mappedEmissiveTriangles;
        record["same_offset_emissive_triangles"] = correspondence.sameOffsetEmissiveTriangles;
        record["primitive_lights"] = correspondence.primitiveLights;
        record["mapped_primitive_lights"] = correspondence.mappedPrimitiveLights;
        record["same_offset_primitive_lights"] = correspondence.sameOffsetPrimitiveLights;
        record["source"] = "CPU PrepareLights tasks; stable instance/geometry and primitive-light identities";
        record["sampling_pdf_mip0_refreshed"] = true;
        record["sampling_pdf_mips_refreshed"] = context.IsLocalLightPowerRISEnabled();
        Json::StreamWriterBuilder writer;
        writer["indentation"] = "";
        frameStates << Json::writeString(writer, frameState) << '\n';
        frameStates.flush();
    }

    void Resolved(const rtxdi::ImportanceSamplingContext& context, const UIData& ui,
                  const donut::engine::DirectionalLight& sun, bool headless)
    {
        if (index != 0) return;
        const auto& di = context.GetReSTIRDIContext();
        RTXDI_Parameters p{};
        FillReSTIRDIConstants(p, di, context.GetLightBufferParameters());
        Json::Value record;
        record["scene_id"] = config["scene_id"];
        record["estimator"] = IsReference() ? "conventional_light_sampling" : "restir_di";
        record["headless"] = headless;
        record["loaded_scene"] = loadedScene;
        record["environment_intensity_ev"] = ui.environmentIntensityBias;
        record["environment_rotation_degrees"] = ui.environmentRotation;
        record["emissive_scale"] = EmissiveScale();
        record["analytic_sun_irradiance"] = sun.irradiance;
        record["vertical_fov_degrees"] = ui.verticalFov;
        record["resolution_scale"] = ui.resolutionScale;
        record["near_plane"] = 0.01;
        record["width"] = di.GetStaticParameters().RenderWidth;
        record["height"] = di.GetStaticParameters().RenderHeight;
        record["mode"] = uint32_t(di.GetResamplingMode());
        record["checkerboard"] = uint32_t(di.GetStaticParameters().CheckerboardSamplingMode);
        record["local_lights"] = context.GetLightBufferParameters().localLightBufferRegion.numLights;
        record["infinite_lights"] = context.GetLightBufferParameters().infiniteLightBufferRegion.numLights;
        record["environment_present"] = context.GetLightBufferParameters().environmentLightParams.lightPresent;
        record["denoiser"] = uint32_t(ui.denoiserMode);
        record["aa"] = uint32_t(ui.aaMode);
        record["pixel_jitter"] = bool(ui.enablePixelJitter);
        record["textures"] = bool(ui.enableTextures);
        record["ray_counts"] = false;
        record["display_passes"] = headless ? "bypassed; no display output" : "bypassed; raw HDR blit for window only";
        record["source_format"] = IsReference() ? "RGBA32_FLOAT accumulated reference" : "RGBA16_FLOAT; export decoded losslessly to float32 PFM";
#define LAB_FIELD(group, field) record[#group][#field] = p.group.field
#define LAB_ENUM(group, field) record[#group][#field] = uint32_t(p.group.field)
        LAB_FIELD(initialSamplingParams, numLocalLightSamples);
        LAB_FIELD(initialSamplingParams, numInfiniteLightSamples);
        LAB_FIELD(initialSamplingParams, numEnvironmentSamples);
        LAB_FIELD(initialSamplingParams, numBrdfSamples);
        LAB_FIELD(initialSamplingParams, brdfCutoff);
        LAB_FIELD(initialSamplingParams, brdfRayMinT);
        LAB_ENUM(initialSamplingParams, localLightSamplingMode);
        LAB_FIELD(initialSamplingParams, enableInitialVisibility);
        LAB_FIELD(initialSamplingParams, environmentMapImportanceSampling);
        LAB_FIELD(temporalResamplingParams, maxHistoryLength);
        LAB_ENUM(temporalResamplingParams, biasCorrectionMode);
        LAB_FIELD(temporalResamplingParams, depthThreshold);
        LAB_FIELD(temporalResamplingParams, normalThreshold);
        LAB_FIELD(temporalResamplingParams, enableVisibilityShortcut);
        LAB_FIELD(temporalResamplingParams, enablePermutationSampling);
        LAB_FIELD(temporalResamplingParams, uniformRandomNumber);
        LAB_FIELD(spatialResamplingParams, numSamples);
        LAB_FIELD(spatialResamplingParams, numDisocclusionBoostSamples);
        LAB_FIELD(spatialResamplingParams, samplingRadius);
        LAB_ENUM(spatialResamplingParams, biasCorrectionMode);
        LAB_FIELD(spatialResamplingParams, depthThreshold);
        LAB_FIELD(spatialResamplingParams, normalThreshold);
        LAB_FIELD(spatialResamplingParams, targetHistoryLength);
        LAB_FIELD(spatialResamplingParams, enableMaterialSimilarityTest);
        LAB_FIELD(spatialResamplingParams, discountNaiveSamples);
        LAB_FIELD(boilingFilterParams, enableBoilingFilter);
        LAB_FIELD(shadingParams, enableFinalVisibility);
        LAB_FIELD(shadingParams, reuseFinalVisibility);
        LAB_FIELD(shadingParams, enableDenoiserInputPacking);
#undef LAB_FIELD
#undef LAB_ENUM
        auto stream = Open(output / "resolved.json");
        stream << record << '\n';
    }

    void End(nvrhi::IDevice* device, Profiler& profiler, const RenderTargets& targets,
             const RtxdiResources& resources, const rtxdi::ReSTIRDIContext& di)
    {
        // Serialize frames so timing queries belong unambiguously to this frame.
        device->waitForIdle();
        profiler.ResolveCompletedFrame();
        timings << Frame()["frame"].asUInt() << ',' << Frame()["sampling_frame"].asUInt()
                << ',' << Frame()["capture"].asBool() << ',' << Reset();
        for (uint32_t section = 0; section < ProfilerSection::MaterialReadback; ++section)
            timings << ',' << profiler.GetTimer(ProfilerSection::Enum(section));
        timings << '\n';
        timings.flush();
        if (Frame()["capture"].asBool())
        {
            std::ostringstream name;
            name << "frame-" << std::setw(4) << std::setfill('0') << Frame()["frame"].asUInt();
            const auto stem = output / name.str();
            auto source = IsReference() ? targets.AccumulatedColor : targets.HdrColor;
            auto desc = source->getDesc();
            if (desc.format != (IsReference() ? nvrhi::Format::RGBA32_FLOAT : nvrhi::Format::RGBA16_FLOAT))
                throw std::runtime_error("Unexpected HDR render target format");
            auto staging = device->createStagingTexture(desc, nvrhi::CpuAccessMode::Read);
            auto command = device->createCommandList();
            command->open();
            command->copyTexture(staging, nvrhi::TextureSlice(), source, nvrhi::TextureSlice());
            command->close();
            device->executeCommandList(command);
            device->waitForIdle();
            size_t pitch = 0;
            auto pixels = static_cast<const char*>(device->mapStagingTexture(staging, nvrhi::TextureSlice(), nvrhi::CpuAccessMode::Read, &pitch));
            if (!pixels) throw std::runtime_error("Cannot map HDR capture");
            try
            {
                auto stream = Open(stem.string() + (IsReference() ? ".rgba32f" : ".rgba16f"));
                for (uint32_t y = 0; y < desc.height; ++y)
                    stream.write(pixels + y * pitch, size_t(desc.width) * (IsReference() ? 16 : 8));
            }
            catch (...) { device->unmapStagingTexture(staging); throw; }
            device->unmapStagingTexture(staging);

            if (config["diagnostics"].asBool())
            {
                const auto params = di.GetReservoirBufferParameters();
                const uint64_t bytes = uint64_t(params.reservoirArrayPitch) * sizeof(RTXDI_PackedDIReservoir);
                nvrhi::BufferDesc bufferDesc;
                bufferDesc.byteSize = bytes;
                bufferDesc.cpuAccess = nvrhi::CpuAccessMode::Read;
                bufferDesc.initialState = nvrhi::ResourceStates::CopyDest;
                auto readback = device->createBuffer(bufferDesc);
                command->open();
                command->copyBuffer(readback, 0, resources.DIReservoirBuffer,
                    uint64_t(di.GetBufferIndices().shadingInputBufferIndex) * bytes, bytes);
                command->close();
                device->executeCommandList(command);
                device->waitForIdle();
                auto data = static_cast<const char*>(device->mapBuffer(readback, nvrhi::CpuAccessMode::Read));
                if (!data) throw std::runtime_error("Cannot map reservoir capture");
                try
                {
                    auto stream = Open(stem.string() + ".reservoir");
                    stream.write(data, bytes);
                }
                catch (...) { device->unmapBuffer(readback); throw; }
                device->unmapBuffer(readback);
            }
        }
        ++index;
    }
};
