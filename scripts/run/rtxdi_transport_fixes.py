"""Common transport corrections, applied identically before the CGNS comparison.

These are estimator corrections, not neighbor selection. The pinned renderer and
SDK remain untouched outside the transactional isolated build.
"""
from pathlib import Path
import shutil
from rtxdi_transport import replace_checked, edit

HERE = Path(__file__).resolve().parent
PAYLOAD = HERE / "rtxdi_experiments"
SHADERS = "Samples/FullSample/Shaders/"
BRIDGE = "LightingPasses/RtxdiApplicationBridge/"
FILES = [SHADERS + BRIDGE + name for name in (
    "RAB_Surface.hlsli", "PathTracer/RAB_PathTracer.hlsli", "PathTracer/RAB_MISCallbacks.hlsli", "RtxdiApplicationBridge.hlsli")]
FILES += [SHADERS + "LightingPasses/BrdfRayTracing.hlsl"]
ENVIRONMENT_FILES = [SHADERS + "PreprocessEnvironmentMap.hlsl", SHADERS + BRIDGE + "RAB_LightSampling.hlsli"]
FILES += ENVIRONMENT_FILES
SEGMENT_FILES = [SHADERS + BRIDGE + name for name in (
    "RAB_RayPayload.hlsli", "RAB_RTShaders.hlsli")]
SEGMENT_PIPELINE = "Samples/FullSample/Source/RenderPasses/RayTracingPass.cpp"
SEGMENT_SCENE = "Samples/FullSample/Source/Scene/SampleScene.cpp"
SEGMENT_FILES += [SEGMENT_PIPELINE, SEGMENT_SCENE]
FILES += SEGMENT_FILES
CREATED = [SHADERS + BRIDGE + name for name in ("TransportMath.hlsli", "TransportDiagnostics.hlsli")]
CREATED += [SHADERS + "LightingPasses/TerminalDelta.hlsli"]
SEGMENT_CREATED = SHADERS + BRIDGE + "OpaqueSegment.hlsli"
CREATED += [SEGMENT_CREATED]
SUPPORT = [Path(__file__), *(PAYLOAD / name for name in ("TransportMath.hlsli", "TerminalDelta.hlsli", "TransportDiagnostics.hlsli", "OpaqueSegment.hlsli"))]


def adapt_ray_payload(text):
    return replace_checked(text, "    float2 barycentrics;",
        "    float2 barycentrics;\n    uint labTraceFlags; // Closest-only mode and transmission observation; default zero preserves legacy rays.")


def adapt_rt_shaders(text):
    text = replace_checked(text, "#if !USE_RAY_QUERY", '#include "OpaqueSegment.hlsli"\n\n#if !USE_RAY_QUERY')
    return replace_checked(text,
        "    if (!ConsiderTransparentMaterial(InstanceID(), GeometryIndex(), PrimitiveIndex(), attrib.uv, payload.throughput))",
        "    bool accepted = (payload.labTraceFlags & LAB_TRACE_CLOSEST_ONLY) != 0\n"
        "        ? LabConsiderOpaqueMaterial(InstanceID(), GeometryIndex(), PrimitiveIndex(), attrib.uv, payload.labTraceFlags)\n"
        "        : ConsiderTransparentMaterial(InstanceID(), GeometryIndex(), PrimitiveIndex(), attrib.uv, payload.throughput);\n"
        "    if (!accepted)")


def adapt_trace_next_bounce(text):
    start = text.index("RAB_RayPayload TraceNextBounce(")
    end = text.index("\nRAB_Surface LoadSurfaceFromRayPayload", start)
    body = text[start:end]
    body = replace_checked(body,
        "    RAB_RayPayload traceResult = (RAB_RayPayload)0;\n    traceResult.instanceID = ~0u;\n    traceResult.throughput = 1.0;\n\n", "")
    query_start = body.index("#if USE_RAY_QUERY")
    # Retain the original instance-mask construction exactly. In particular,
    # masks classify whole instances, so they cannot replace material tests.
    native_query = body[query_start:]
    if native_query.count("traceResult.throughput))") != 1 or not native_query.endswith("\treturn traceResult;\n}\n"):
        raise RuntimeError("Pinned continuation trace changed")
    body = body[:query_start] + "    return LabTraceOpaqueSegment(continuationRay, instanceMask);\n}\n"
    return text[:start] + body + text[end:]


def adapt_brdf_segment(text):
    text = replace_checked(text,
        "    RAB_RayPayload payload = (RAB_RayPayload)0;\n    payload.instanceID = ~0u;\n    payload.throughput = 1.0;\n\n", "")
    start = text.index("#if USE_RAY_QUERY", text.index("uint instanceMask = INSTANCE_MASK_OPAQUE;"))
    end = text.index("#endif", start) + len("#endif")
    body = text[start:end]
    if body.count("payload.throughput))") != 1 or body.count("TraceRay(SceneBVH, RAY_FLAG_NONE, instanceMask, 0, 0, 0, ray, payload);") != 1:
        raise RuntimeError("Pinned GI BRDF trace changed")
    return text[:start] + "    RAB_RayPayload payload = LabTraceOpaqueSegment(ray, instanceMask);" + text[end:]


def adapt_segments(renderer):
    for name, transform in (("RAB_RayPayload.hlsli", adapt_ray_payload), ("RAB_RTShaders.hlsli", adapt_rt_shaders)):
        path = renderer / SHADERS / BRIDGE / name
        path.write_text(transform(path.read_text(encoding="utf-8")), encoding="utf-8")
    shutil.copyfile(PAYLOAD / "OpaqueSegment.hlsli", renderer / SEGMENT_CREATED)
    edit(renderer / SEGMENT_PIPELINE, "    rtPipelineDesc.maxPayloadSize = 40;",
        "    rtPipelineDesc.maxPayloadSize = 44; // RAB_RayPayload includes controlled segment trace flags.")
    # Multiplicative transmission must observe each physical triangle at most
    # once. DXR otherwise permits duplicate AnyHit invocations for one ray.
    edit(renderer / SEGMENT_SCENE, ": nvrhi::rt::GeometryFlags::None;",
        ": nvrhi::rt::GeometryFlags::NoDuplicateAnyHitInvocation;")


def sdk_created(renderer):
    sdk = renderer / "Libraries/Rtxdi/Include/Rtxdi"
    return [renderer / SHADERS / "LabSdk/Rtxdi" / p.relative_to(sdk) for p in sdk.rglob("*") if p.is_file()]


def adapt_trace_context(text, *, initial):
    addition = "        ptState.traceResult = rp;\n        ptState.pathThroughput *= rp.throughput;"
    if initial:
        addition += "\n        if (ptState.bounceDepth > ptState.rcVertexLength)\n            ptState.rcPathThroughput *= rp.throughput;"
    text = replace_checked(text, "        ptState.traceResult = rp;", addition)
    text = replace_checked(text,
        "SetContinuationRayBrdfOverPdf(raySample.brdfTimesNoL / raySample.outPdf);",
        "LabObserveFinite(raySample.brdfTimesNoL);\n        LabObserveFinite(float3(raySample.outPdf, 0, 0));\n"
        "        SetContinuationRayBrdfOverPdf(raySample.outPdf > 0 ? raySample.brdfTimesNoL / raySample.outPdf : float3(0,0,0));")
    if initial:
        text = replace_checked(text,
            "        if (any(radianceFromLights > 0.f) && RTXDI_SampledLightData_IsValidLightData(ptState.sampledLightDataForDI))",
            "        LabObserveFinite(radianceFromLights);\n        if (any(radianceFromLights > 0.f) && RTXDI_SampledLightData_IsValidLightData(ptState.sampledLightDataForDI))")
    return text


def adapt_reconnection(text, *, temporal):
    old = ("RAB_GetConservativeVisibility(curSurface, prevSample.translatedWorldPosition)" if temporal else
           "RAB_GetConservativeVisibility(surface, neighborReservoir.translatedWorldPosition)")
    return replace_checked(text, old, old.replace("RAB_GetConservativeVisibility(", "GetFinalVisibility(SceneBVH, "))


def adapt_hybrid(text):
    text = replace_checked(text, "    const bool isVisible = RAB_GetConservativeVisibility(surface, lightSample);",
                           "    const float3 visibility = GetFinalVisibility(SceneBVH, surface, RAB_LightSamplePosition(lightSample));")
    text = replace_checked(text,
        "float3 targetFunction = isVisible ? RAB_GetReflectedBsdfRadianceForSurface(RAB_LightSamplePosition(lightSample), RAB_LightSampleRadiance(lightSample), surface) : float3(0.0f, 0.0f, 0.0f);",
        "float3 targetFunction = visibility * RAB_GetReflectedBsdfRadianceForSurface(RAB_LightSamplePosition(lightSample), RAB_LightSampleRadiance(lightSample), surface);")
    # A reconnected edge is continuous. Forward and inverse footprint tests must
    # use the same mixed-measure density, including low-roughness diffuse paths.
    text = replace_checked(text, "scatterPdf = RAB_SurfaceEvaluateBrdfPdf(surfaceForResampling, reconnectionDir);",
                           "scatterPdf = LabContinuousBsdfPdf(surfaceForResampling, reconnectionDir);")
    return replace_checked(text, "scatterPdf = RAB_SurfaceEvaluateBrdfPdf(surfaceForResampling, lightDirection);",
                           "scatterPdf = LabContinuousBsdfPdf(surfaceForResampling, lightDirection);")


def adapt_gi_reservoir(text):
    text = replace_checked(text, "reservoir.weightSum = samplePdf > 0.0 ? 1.0 / samplePdf : 0.0;",
                           "\n#ifdef LAB_TRANSPORT_DIAGNOSTICS\n    LabObserveFinite(sampleRadiance);\n#endif\n    reservoir.weightSum = samplePdf > 0.0 && any(sampleRadiance != 0) ? 1.0 / samplePdf : 0.0;")
    text = replace_checked(text, "    const float risWeight = targetPdf * newReservoir.weightSum * newReservoir.M;",
                           "#ifdef LAB_TRANSPORT_DIAGNOSTICS\n    LabObserveFinite(newReservoir.radiance);\n    LabObserveFinite(float3(targetPdf, newReservoir.weightSum, 0));\n#endif\n    const float risWeight = targetPdf * newReservoir.weightSum * newReservoir.M;")
    return replace_checked(text, "bool selectSample = (random * reservoir.weightSum <= risWeight);",
                           "bool selectSample = risWeight > 0 && (random * reservoir.weightSum <= risWeight);")


def adapt_gi_nulls(text, *, temporal):
    donor = "temporalReservoir" if temporal else "neighborReservoir"
    other_surface = "temporalSurface" if temporal else "neighborSurface"
    old = f"float jacobian = RTXDI_CalculateJacobian(RAB_GetSurfaceWorldPos(surface), RAB_GetSurfaceWorldPos({other_surface}), {donor}.position, {donor}.normal);"
    text = replace_checked(text, old,
        f"bool labNull = {donor}.weightSum == 0 || !any({donor}.radiance != 0);\n        " +
        old.replace("= RTXDI_", "= labNull ? 1.f : RTXDI_"))
    text = replace_checked(text, "if (!RAB_ValidateGISampleWithJacobian(jacobian))",
                           "if (!labNull && !RAB_ValidateGISampleWithJacobian(jacobian))")
    # The temporal target evaluation occurs outside labNull's lexical scope.
    for reservoir in ("inputReservoir", donor, "curReservoir"):
        source = "surface" if reservoir != "curReservoir" else other_surface
        old = f"RAB_GetGISampleTargetPdfForSurface({reservoir}.position, {reservoir}.radiance, {source})"
        text = replace_checked(text, old,
            f"({reservoir}.weightSum == 0 || !any({reservoir}.radiance != 0) ? 0.f : {old})")
    return text


def adapt_gi_final_nulls(text):
    start = text.index("    if (RTXDI_IsValidGIReservoir(reservoir))")
    end = text.index("\n    StoreShadingOutput(", start)
    replacement = '''    LabObserveFinite(reservoir.radiance);
    LabObserveFinite(float3(reservoir.weightSum, 0, 0));
    if (reservoir.M != 0 && reservoir.weightSum != 0 && any(reservoir.radiance != 0))
    {
        float3 radiance = reservoir.radiance * reservoir.weightSum;
        if (g_Const.restirGI.finalShadingParams.enableFinalVisibility)
            radiance *= GetFinalVisibility(SceneBVH, primarySurface, reservoir.position);
        const SplitBrdf brdf = EvaluateBrdf(primarySurface, reservoir.position);
        float finalWeight = 1;
        if (g_Const.restirGI.finalShadingParams.enableFinalMIS)
        {
            RAB_Surface roughened = primarySurface;
            roughened.material.roughness = max(roughened.material.roughness, kMISRoughness);
            finalWeight = 1 - GetMISWeight(EvaluateBrdf(roughened, reservoir.position), brdf, primarySurface.material.diffuseAlbedo);
        }
        diffuse += brdf.demodulatedDiffuse * radiance * finalWeight;
        specular += brdf.specular * radiance * finalWeight;
    }
    if (g_Const.restirGI.finalShadingParams.enableFinalMIS)
    {
        const RTXDI_GIReservoir initial = LoadInitialSampleReservoir(reservoirPosition, primarySurface);
        LabObserveFinite(initial.radiance);
        LabObserveFinite(float3(initial.weightSum, 0, 0));
        if (initial.M != 0 && initial.weightSum != 0 && any(initial.radiance != 0))
        {
            const SplitBrdf brdf = EvaluateBrdf(primarySurface, initial.position);
            RAB_Surface roughened = primarySurface;
            roughened.material.roughness = max(roughened.material.roughness, kMISRoughness);
            float initialWeight = GetMISWeight(EvaluateBrdf(roughened, initial.position), brdf, primarySurface.material.diffuseAlbedo);
            float3 radiance = initial.radiance * initial.weightSum;
            diffuse += brdf.demodulatedDiffuse * radiance * initialWeight;
            specular += brdf.specular * radiance * initialWeight;
        }
    }
    specular = DemodulateSpecular(primarySurface.material.specularF0, specular);
'''
    return text[:start] + replacement + text[end:]


def adapt_surface(text):
    text = replace_checked(text, '#include "RAB_Material.hlsli"',
                           '#include "RAB_Material.hlsli"\n#include "TransportMath.hlsli"')
    text = replace_checked(text,
        "        specularPdf = ImportanceSampleGGX_VNDF_PDF(max(surface.material.roughness, kMinRoughness), surface.normal, surface.viewDir, dir);",
        "        specularPdf = LabGgxVndfPdf(surface.material.roughness, surface.normal, surface.viewDir, dir);")
    text = replace_checked(text, "        s = F / (1.f - surface.diffuseProbability);", "        s = F; // Discrete numerator; the caller divides by pDelta exactly once.")
    signature = "float RAB_SurfaceEvaluateBsdfPdf(RAB_Surface surface, float3 dir, RTXDI_BrdfRaySampleProperties brsp)\n{"
    text = replace_checked(text, signature, signature + "\n    if (brsp.IsDelta())\n        return dot(surface.normal, dir) > 0 ? 1.f - surface.diffuseProbability : 0;")
    signature = "float3 RAB_GetReflectedBsdfRadianceForSurface("
    text = replace_checked(text, signature, '''// Continuous density for NEE and reconnection; excludes discrete mirror mass.
float LabContinuousBsdfPdf(RAB_Surface surface, float3 direction)
{
    RTXDI_BrdfRaySampleProperties properties = RTXDI_DefaultBrdfRaySampleProperties();
    properties.SetContinuous();
    return RAB_SurfaceEvaluateBsdfPdf(surface, direction, properties);
}

float3 RAB_GetReflectedBsdfRadianceForSurface(''')
    return text


def adapt_path(text):
    text = adapt_trace_next_bounce(text)
    text = replace_checked(text,
        "float3 envMapRadiance = RAB_GetEnvironmentRadiance(ctx.GetContinuationRay().Direction);",
        "float3 envMapRadiance = ctx.GetBrdfRaySample().properties.IsDelta()\n"
        "                    ? RAB_GetEnvironmentRadiance(ctx.GetContinuationRay().Direction)\n"
        "                    : LabContinuousEnvironmentRadiance(ctx.GetContinuationRay().Direction);")
    text = replace_checked(text, "prevSurface.material.roughness < kMinRoughness && ctx.GetBounceDepth() == 2",
                           "ctx.GetBrdfRaySample().properties.IsDelta() && ctx.GetBounceDepth() == 2")
    text = replace_checked(text, "           && ctx.GetIntersectionSurface().material.roughness >= kMinRoughness", "")
    text = replace_checked(text,
        "    return (FacingNextSurface ? RAB_GetEmissiveColor(RAB_GetMaterial(ctx.GetIntersectionSurface())) : float3(0.0f, 0.0f, 0.0f));", '''    if (!FacingNextSurface) return 0;
    const RAB_RayPayload hit = ctx.GetTraceResult();
    uint emitter = GetLightIndex(hit.instanceID, hit.geometryIndex, hit.primitiveIndex);
    if (!ctx.GetBrdfRaySample().properties.IsDelta() && emitter != RTXDI_InvalidLightIndex)
        return UnpackLightColor(RAB_LoadLightInfo(emitter, false));
    return RAB_GetEmissiveColor(RAB_GetMaterial(ctx.GetIntersectionSurface()));''')
    text = replace_checked(text, "scatterPdf = RAB_SurfaceEvaluateBrdfPdf(intersectionSurface,", "scatterPdf = LabContinuousBsdfPdf(intersectionSurface,")
    text = replace_checked(text, "radianceFromLights *= RAB_GetConservativeVisibility(intersectionSurface, lightSample.position);",
                           "radianceFromLights *= GetFinalVisibility(SceneBVH, intersectionSurface, lightSample.position);")
    # Enum-vs-bool typo in the author bridge; avoid changing current MIS behavior.
    text = replace_checked(text, "if(g_Const.pt.lightSamplingMode == IsNeeOnlySamplingEnabled())", "if(IsNeeOnlySamplingEnabled())")
    return text


def adapt_mis(text):
    text = replace_checked(text, '#include "Rtxdi/Utils/BrdfRaySample.hlsli"',
                           '#include "Rtxdi/Utils/BrdfRaySample.hlsli"\n#include "../TransportMath.hlsli"')
    text = replace_checked(text, "RAB_SamplePolymorphicLight(lightInfo, prevSurface, rayPayload.barycentrics)",
                           "RAB_SamplePolymorphicLight(lightInfo, prevSurface, LabTriangleRandomFromBarycentrics(rayPayload.barycentrics))")
    # Native reservoirs cache BSDF endpoint MIS, while NEE reconnections compute
    # it at the receiver. A fixed sample-count partition is invariant under this
    # shift, retaining the hybrid map without adding per-endpoint metadata.
    text = replace_checked(text, "return NEEMisTerm / (NEEMisTerm + scatterPdf);",
        "return float(numSamples) / (float(numSamples) + 1.f); // Shift-invariant MIS partition.")
    text = replace_checked(text,
        "float pdfSum = sampleParams.numLocalLightSamples * lightSourcePdf + brs.outPdf;\n    return brs.outPdf / pdfSum;",
        "return 1.f / (float(sampleParams.numLocalLightSamples) + 1.f);")
    return replace_checked(text,
        "float pdfSum = sampleParams.numEnvironmentSamples * lightSourcePdf + brs.outPdf;\n    return brs.outPdf / pdfSum;",
        "return 1.f / (float(sampleParams.numEnvironmentSamples) + 1.f);")


def adapt_environment(renderer):
    # The bilinearly filtered radiance can be positive inside a black PDF cell.
    # Give every in-bounds cell positive FP16-representable proposal support;
    # this changes only sampling, never radiance. Padding must remain zero.
    preprocess = renderer / ENVIRONMENT_FILES[0]
    edit(preprocess, "    float3 color = t_EnvironmentMap[position].rgb;",
         "    if (any(position >= g_Const.sourceSize)) return 0;\n    float3 color = t_EnvironmentMap[position].rgb;")
    edit(preprocess, "return clamp(luma * relativeSolidAngle, 0, maxWeight);",
         "return clamp(luma * relativeSolidAngle, 1.f / 1024.f, maxWeight);")
    light = renderer / ENVIRONMENT_FILES[1]
    edit(light, "float3 RAB_GetEnvironmentRadiance(float3 direction)", '''// Continuous endpoints share the NEE light's packed scale and rotation.
// Delta/background paths deliberately keep the historical authored environment.
float3 LabContinuousEnvironmentRadiance(float3 direction)
{
    if (!g_Const.sceneConstants.enableEnvironmentMap) return 0;
    EnvironmentLight environment = EnvironmentLight::Create(
        RAB_LoadLightInfo(g_Const.lightBufferParams.environmentLightParams.lightIndex, false));
    float2 uv = DirectionToEquirectUV(direction);
    uv.x -= environment.rotation;
    Texture2D texture = t_BindlessTextures[environment.textureIndex];
    return environment.radianceScale * texture.SampleLevel(s_EnvironmentSampler, uv, 0).rgb;
}

float3 RAB_GetEnvironmentRadiance(float3 direction)''')


def adapt_brdf_trace(text):
    text = replace_checked(text,
        "specular_PDF = saturate(CalcLuminance(specular_BRDF_over_PDF) /\n            CalcLuminance(specular_BRDF_over_PDF + diffuse_BRDF_over_PDF * surface.material.diffuseAlbedo));",
        "specular_PDF = 1.f - surface.diffuseProbability; // Fixed before either direction is drawn.")
    text = replace_checked(text,
        "const float specularLobe_PDF = ImportanceSampleGGX_VNDF_PDF(surface.material.roughness, surface.normal, V, ray.Direction);",
        "const float specularLobe_PDF = isDeltaSurface ? 0.f : LabGgxVndfPdf(surface.material.roughness, surface.normal, V, ray.Direction);")
    text = replace_checked(text, "        payload.committedRayT = rayQuery.CommittedRayT();",
                           "        payload.committedRayT = rayQuery.CommittedRayT();\n        payload.frontFace = rayQuery.CommittedTriangleFrontFace();")
    text = replace_checked(text, "overall_PDF = isDeltaSurface ? diffuseLobe_PDF :",
                           "overall_PDF = isDeltaSurface ? (1.f - specular_PDF) * diffuseLobe_PDF :")
    text = replace_checked(text, "        if (includeEmissiveComponent)", "        if (includeEmissiveComponent && RAB_RayPayloadIsFrontFace(payload))")
    return adapt_brdf_segment(text)


def adapt(renderer):
    shaders = renderer / SHADERS
    adapt_segments(renderer)
    adapt_environment(renderer)
    # A private complete include tree preserves relative SDK includes. The real
    # SDK checkout is never edited, including while building this variant.
    shutil.copytree(renderer / "Libraries/Rtxdi/Include/Rtxdi", shaders / "LabSdk/Rtxdi",
                    copy_function=shutil.copyfile, dirs_exist_ok=True)
    edit(shaders / "CMakeLists.txt", "      -I ${RTXDI_RUNTIME_INCLUDE_PATH}",
         "      -I ${CMAKE_CURRENT_SOURCE_DIR}/LabSdk\n      -I ${RTXDI_RUNTIME_INCLUDE_PATH}", 2)
    sdk = shaders / "LabSdk/Rtxdi/PT"
    for name, transform in (("InitialSamplingPathTracerContext.hlsli", lambda s:adapt_trace_context(s, initial=True)),
                            ("HybridShiftPathTracerContext.hlsli", lambda s:adapt_trace_context(s, initial=False)),
                            ("HybridShift.hlsli", adapt_hybrid),
                            ("SpatialResampling.hlsli", lambda s:adapt_reconnection(s, temporal=False)),
                            ("TemporalResampling.hlsli", lambda s:adapt_reconnection(s, temporal=True))):
        path = sdk / name
        path.write_text(transform(path.read_text(encoding="utf-8")), encoding="utf-8")
    gi = shaders / "LabSdk/Rtxdi/GI"
    for name, transform in (("Reservoir.hlsli", adapt_gi_reservoir),
                            ("SpatialResampling.hlsli", lambda s:adapt_gi_nulls(s, temporal=False)),
                            ("TemporalResampling.hlsli", lambda s:adapt_gi_nulls(s, temporal=True))):
        path = gi / name
        path.write_text(transform(path.read_text(encoding="utf-8")), encoding="utf-8")
    gi_spatial = shaders / "LightingPasses/GI/CgnsSpatialResampling.hlsli"
    gi_spatial.write_text(adapt_gi_nulls(gi_spatial.read_text(encoding="utf-8"), temporal=False), encoding="utf-8")
    spatial = shaders / "LightingPasses/PT/CgnsSpatialResampling.hlsli"
    spatial.write_text(adapt_reconnection(spatial.read_text(encoding="utf-8"), temporal=False), encoding="utf-8")
    initial_context = sdk / "InitialSamplingPathTracerContext.hlsli"
    edit(initial_context, "        const float3 targetFunctionOverP = currentLightRadiance * ptState.pathThroughput;",
         "        const float3 targetFunctionOverP = currentLightRadiance * ptState.pathThroughput;\n        LabObserveFinite(targetFunctionOverP);")
    for name, transform in ((BRIDGE + "RAB_Surface.hlsli", adapt_surface),
                            (BRIDGE + "PathTracer/RAB_PathTracer.hlsli", adapt_path),
                            (BRIDGE + "PathTracer/RAB_MISCallbacks.hlsli", adapt_mis),
                            ("LightingPasses/BrdfRayTracing.hlsl", adapt_brdf_trace)):
        path = shaders / name
        path.write_text(transform(path.read_text(encoding="utf-8")), encoding="utf-8")
    shutil.copyfile(PAYLOAD / "TransportMath.hlsli", shaders / BRIDGE / "TransportMath.hlsli")
    shutil.copyfile(PAYLOAD / "TransportDiagnostics.hlsli", shaders / BRIDGE / "TransportDiagnostics.hlsli")
    edit(shaders / BRIDGE / "RtxdiApplicationBridge.hlsli", '#include "RAB_Buffers.hlsli"',
         '#include "RAB_Buffers.hlsli"\n#include "TransportDiagnostics.hlsli"')
    edit(shaders / "LightingPasses/DI/Cgns.hlsli", "RWStructuredBuffer<uint> u_CgnsStatistics : register(u31);", "// Declared by TransportDiagnostics.hlsli.")
    shutil.copyfile(PAYLOAD / "TerminalDelta.hlsli", shaders / "LightingPasses/TerminalDelta.hlsli")
    secondary = shaders / "LightingPasses/ShadeSecondarySurfaces.hlsl"
    edit(secondary, '#include "ShadingHelpers.hlsli"',
         '#include "ShadingHelpers.hlsli"\n#include "RtxdiApplicationBridge/PathTracer/RAB_PathTracer.hlsli"\n#include "TerminalDelta.hlsli"')
    edit(secondary, "        radiance += indirectDiffuse * secondarySurface.material.diffuseAlbedo + indirectSpecular;",
         "        radiance += indirectDiffuse * secondarySurface.material.diffuseAlbedo + indirectSpecular;\n        radiance += LabSecondaryDeltaEndpoint(secondarySurface);")
    edit(secondary, "        uint2 reservoirPosition = RTXDI_PixelPosToReservoirPos",
         "        // A sampled delta lobe is a zero contribution to the continuous GI component.\n"
         "        // Keep its attempt in M so mixture PDFs and reuse normalization agree.\n"
         "        if (RAB_IsSurfaceValid(primarySurface) && reservoir.M == 0) reservoir.M = 1;\n"
         "        uint2 reservoirPosition = RTXDI_PixelPosToReservoirPos")
    final = shaders / "LightingPasses/GI/FinalShading.hlsl"
    final.write_text(adapt_gi_final_nulls(final.read_text(encoding="utf-8")), encoding="utf-8")
    source = renderer / "Samples/FullSample/Source"
    edit(source / "RtxdiResources.cpp", "context.GetStaticParameters().RenderHeight * 8;",
         "context.GetStaticParameters().RenderHeight * 8 + 4;")
    edit(source / "RtxdiResources.cpp", "    m_neighborOffsetsInitialized = true;",
         "    commandList->clearBufferUInt(CgnsStatisticsBuffer, 0);\n    m_neighborOffsetsInitialized = true;")
    helper = source / "App/LabExperiment.h"
    edit(helper, "const auto bytes = countBytes * 2;", "const auto bytes = countBytes * 2 + 4;")
    edit(helper, '                    auto stream = Open(stem.string() + ".spatial-counts");',
         '''                    const auto invalid = *reinterpret_cast<const uint32_t*>(data + countBytes * 2);
                    { auto file = Open(stem.string() + ".transport-invalid"); file.write(data + countBytes * 2, 4); }
                    if (invalid != 0) throw std::runtime_error("Nonfinite GI/PT contribution detected before reservoir sanitization");
                    auto stream = Open(stem.string() + ".spatial-counts");''')
