// Members inserted into LabExperiment by the isolated transport adapter.
bool TransportCgnsEnabled() const
{
    return config.isMember("transport_method") && config["transport_method"]["cgns"].asBool();
}

void ApplyTransport(UIData& ui) const
{
    if (!config.isMember("transport_method")) return;
    const auto& t = config["transport_method"];
    const auto algorithm = t["algorithm"].asString();
    if (t["schema_version"].asUInt() != 1 || (algorithm != "GI" && algorithm != "PT") ||
        !t["cgns"].isBool() || config["definition"].get("cgns", false).asBool() ||
        t["glass"].asString() != "legacy-DI" || t["radiance_clamp"].asBool() ||
        t["decorrelation"].asBool() || t["denoiser_psr"].asBool())
        throw std::runtime_error("Unsupported controlled transport configuration");
    auto& l = ui.lightingSettings;
    l.enableDenoiserPSR = false;
    l.usePSRMvecForResampling = false;
    l.updatePSRwithResampling = false;
    l.brdfptParams.materialOverrideParams.minSecondaryRoughness = t["secondary_roughness_floor"].asFloat();
    l.brdfptParams.enableSecondaryResampling = t["secondary_reuse"].asBool();
    auto& nee = l.brdfptParams.secondarySurfaceReSTIRDIParams.initialSamplingParams;
    nee.localLightSamplingMode = ReSTIRDI_LocalLightSamplingMode::Uniform;
    nee.numLocalLightSamples = t["secondary_nee"]["local"].asUInt();
    nee.numEnvironmentSamples = HasProceduralEnvironment() || config["scene"]["lighting"]["environment"].asString() == "file"
        ? t["secondary_nee"]["environment"].asUInt() : 0;
    nee.numInfiniteLightSamples = t["secondary_nee"]["infinite"].asUInt();
    nee.numBrdfSamples = 0;
    nee.enableInitialVisibility = true;
    nee.environmentMapImportanceSampling = true;
    auto& pt = l.ptParameters;
    pt.nee.initialSamplingParams = nee;
    pt.enableSecondaryDISpatialResampling = t["secondary_reuse"].asBool();
    pt.enableRussianRoulette = t["russian_roulette"].asBool();
    pt.minimumPathThroughput = t["minimum_path_throughput"].asFloat();
    pt.extraMirrorBounceBudget = t["extra_mirror_bounces"].asUInt();
    pt.sampleEmissivesOnSecondaryHit = false;
    pt.sampleEnvMapOnSecondaryMiss = false;
    ui.restirPT.spatialResampling.enableSpatialHeuristicMode = algorithm == "PT" && TransportCgnsEnabled();
    ui.restirPT.spatialResampling.duplicationBasedHistoryReduction = false;
    ui.restirPT.spatialResampling.maxTemporalHistory = config["definition"]["max_history_length"].asUInt();
    ui.restirPT.decorrelation.decorrelationMode = RTXDI_PTDecorrelationMode::None;
    ui.restirPT.decorrelation.fireflyReplacementFilterEnable = false;
    ui.restirPT.decorrelation.fireflyReplacementBiasReduction = false;
    ui.restirPT.hybridMirrorInitial = false;
}

void ConfigureTransport(rtxdi::ImportanceSamplingContext& context) const
{
    if (!config.isMember("transport_method")) return;
    auto& gi = context.GetReSTIRGIContext();
    auto s = gi.GetSpatialResamplingParameters();
    const auto& d = config["definition"];
    // Also supplies selection-only K/early controls to the native PT selector.
    s.pad1 = TransportCgnsEnabled();
    s.pad2 = d.get("cgns_candidates", 32).asUInt();
    s.pad3 = d.get("cgns_early_stopping", true).asBool();
    s.numSamples = d["spatial_neighbors"].asUInt();
    s.samplingRadius = d["spatial_radius"].asFloat();
    if (s.numSamples < 1 || s.numSamples > 4 || s.pad2 < s.numSamples || s.pad2 > 32)
        throw std::runtime_error("Transport CGNS requires 1..4 neighbors <= K <= 32");
    gi.SetSpatialResamplingParameters(s);
}

void RecordTransport(Json::Value& record, const rtxdi::ImportanceSamplingContext& context, const UIData& ui) const
{
    if (!config.isMember("transport_method")) return;
    auto& r = record["transport_controls"];
    r["schema_version"] = 1;
    r["indirect_mode"] = uint32_t(ui.indirectLightingMode);
    r["direct_mode"] = uint32_t(ui.lightingSettings.directLightingMode);
    const auto& gi = context.GetReSTIRGIContext();
    const auto& pt = context.GetReSTIRPTContext();
    auto gs = gi.GetSpatialResamplingParameters();
    auto gt = gi.GetTemporalResamplingParameters();
    auto gf = gi.GetFinalShadingParameters();
    auto gb = gi.GetBoilingFilterParameters();
    auto ps = pt.GetSpatialResamplingParameters();
    auto pi = pt.GetInitialSamplingParameters();
    auto ph = pt.GetHybridShiftParameters();
    auto ptp = pt.GetTemporalResamplingParameters();
    auto pd = pt.GetDecorrelationParameters();
    auto pb = pt.GetBoilingFilterParameters();
#define TRANSPORT_FIELD(object, field) r[#object][#field] = object.field
#define TRANSPORT_ENUM(object, field) r[#object][#field] = uint32_t(object.field)
    r["gi_mode"] = uint32_t(gi.GetResamplingMode());
    r["pt_mode"] = uint32_t(pt.GetResamplingMode());
    TRANSPORT_FIELD(gs, numSamples); TRANSPORT_FIELD(gs, samplingRadius);
    TRANSPORT_FIELD(gs, normalThreshold); TRANSPORT_FIELD(gs, depthThreshold);
    TRANSPORT_ENUM(gs, biasCorrectionMode);
    TRANSPORT_FIELD(gs, pad1); TRANSPORT_FIELD(gs, pad2); TRANSPORT_FIELD(gs, pad3);
    TRANSPORT_FIELD(gt, maxHistoryLength); TRANSPORT_FIELD(gt, maxReservoirAge);
    TRANSPORT_FIELD(gt, enableFallbackSampling); TRANSPORT_FIELD(gt, enablePermutationSampling);
    TRANSPORT_ENUM(gt, biasCorrectionMode);
    TRANSPORT_FIELD(gf, enableFinalVisibility); TRANSPORT_FIELD(gf, enableFinalMIS);
    TRANSPORT_FIELD(gb, enableBoilingFilter);
    TRANSPORT_FIELD(ps, numSpatialSamples); TRANSPORT_FIELD(ps, numDisocclusionBoostSamples);
    TRANSPORT_FIELD(ps, samplingRadius); TRANSPORT_FIELD(ps, normalThreshold); TRANSPORT_FIELD(ps, depthThreshold);
    TRANSPORT_FIELD(ps, enableSpatialHeuristicMode); TRANSPORT_FIELD(ps, duplicationBasedHistoryReduction);
    TRANSPORT_FIELD(ps, maxTemporalHistory);
    TRANSPORT_FIELD(pi, numInitialSamples); TRANSPORT_FIELD(pi, maxBounceDepth); TRANSPORT_FIELD(pi, maxRcVertexLength);
    TRANSPORT_FIELD(ph, maxBounceDepth); TRANSPORT_FIELD(ph, maxRcVertexLength);
    TRANSPORT_FIELD(ptp, maxHistoryLength); TRANSPORT_FIELD(ptp, maxReservoirAge);
    TRANSPORT_FIELD(ptp, enableFallbackSampling); TRANSPORT_FIELD(ptp, enablePermutationSampling);
    TRANSPORT_FIELD(ptp, enableVisibilityBeforeCombine); TRANSPORT_FIELD(ptp, enableAgeBasedRejection);
    TRANSPORT_FIELD(ptp, duplicationBasedHistoryReduction);
    TRANSPORT_ENUM(pd, decorrelationMode); TRANSPORT_FIELD(pd, fireflyReplacementFilterEnable);
    TRANSPORT_FIELD(pb, enableBoilingFilter);
    auto nee = config["transport_method"]["algorithm"].asString() == "PT"
        ? ui.lightingSettings.ptParameters.nee.initialSamplingParams
        : ui.lightingSettings.brdfptParams.secondarySurfaceReSTIRDIParams.initialSamplingParams;
    TRANSPORT_FIELD(nee, numLocalLightSamples); TRANSPORT_FIELD(nee, numEnvironmentSamples);
    TRANSPORT_FIELD(nee, numInfiniteLightSamples); TRANSPORT_FIELD(nee, numBrdfSamples);
    TRANSPORT_ENUM(nee, localLightSamplingMode); TRANSPORT_FIELD(nee, enableInitialVisibility);
    auto path = ui.lightingSettings.ptParameters;
    TRANSPORT_FIELD(path, enableSecondaryDISpatialResampling); TRANSPORT_FIELD(path, enableRussianRoulette);
    TRANSPORT_FIELD(path, minimumPathThroughput); TRANSPORT_FIELD(path, extraMirrorBounceBudget);
    TRANSPORT_FIELD(path, sampleEmissivesOnSecondaryHit); TRANSPORT_FIELD(path, sampleEnvMapOnSecondaryMiss);
    TRANSPORT_ENUM(path, lightSamplingMode);
#undef TRANSPORT_FIELD
#undef TRANSPORT_ENUM
    r["secondary_roughness_floor"] = ui.lightingSettings.brdfptParams.materialOverrideParams.minSecondaryRoughness;
    r["secondary_reuse"] = bool(ui.lightingSettings.brdfptParams.enableSecondaryResampling);
    r["primary_roughness_override"] = bool(ui.gbufferSettings.enableRoughnessOverride);
    r["primary_metalness_override"] = bool(ui.gbufferSettings.enableMetalnessOverride);
    r["denoiser_psr"] = bool(ui.lightingSettings.enableDenoiserPSR);
    r["gi_final_reservoir"] = gi.GetBufferIndices().finalShadingInputBufferIndex;
    r["gi_common_fixes"] = "final-reservoir-index+delta-output+no-radiance-clamp+terminal-delta+joint-mixture-null-M+final-MIS";
    r["transport_revision"] = 2;
    r["glass"] = "legacy-DI";
}
