// Ordinary bounded Monte Carlo path tracing. No reservoir is generated or merged.
// One invocation = one path sample, including zero/background contributions.
// NEE: one independent proposal per present light class at each scattering vertex.
// MIS is disabled: indexed continuous emitter/environment paths use NEE; delta
// endpoint paths (and unindexed emitters) use BSDF tracing, with disjoint support.
#pragma pack_matrix(row_major)
#include "../RtxdiApplicationBridge/RtxdiApplicationBridge.hlsli"
#include <Rtxdi/LightSampling/PresamplingFunctions.hlsli>
// Reuse ray/geometry loading helpers only, never RAB_PathTrace or its RIS NEE.
#include "../RtxdiApplicationBridge/PathTracer/RAB_PathTracer.hlsli"

float3 PathLightSample(RAB_Surface surface, uint index, float2 uv, float sourcePdf)
{
    if (sourcePdf <= 0) return 0;
    RAB_LightSample light = RAB_SamplePolymorphicLight(RAB_LoadLightInfo(index, false), surface, uv);
    if (light.solidAnglePdf <= 0) return 0;
    float3 L = normalize(light.position - surface.worldPos);
    if (dot(L, surface.geoNormal) <= 0) return 0;
    SplitBrdf brdf = EvaluateBrdf(surface, light.position);
    return (brdf.demodulatedDiffuse * surface.material.diffuseAlbedo + brdf.specular)
        * light.radiance * GetFinalVisibility(SceneBVH, surface, light.position)
        / (sourcePdf * light.solidAnglePdf);
}

float3 PathNee(RAB_Surface surface, inout RTXDI_RandomSamplerState rng)
{
    float3 result = 0;
    RTXDI_LightBufferRegion local = g_Const.lightBufferParams.localLightBufferRegion;
    if (local.numLights > 0)
    {
        uint2 texel; float pdf;
        RTXDI_SamplePdfMipmap(rng, t_LocalLightPdfTexture, g_Const.localLightPdfTextureSize, texel, pdf);
        uint index = RTXDI_ZCurveToLinearIndex(texel);
        float2 uv = float2(RTXDI_GetNextRandom(rng), RTXDI_GetNextRandom(rng));
        if (index < local.numLights)
            result += PathLightSample(surface, local.firstLightIndex + index, uv, pdf);
    }
    if (g_Const.lightBufferParams.environmentLightParams.lightPresent)
    {
        uint2 texel; float pdf;
        RTXDI_SamplePdfMipmap(rng, t_EnvironmentPdfTexture, g_Const.environmentPdfTextureSize, texel, pdf);
        float2 uv = (float2(texel) + float2(RTXDI_GetNextRandom(rng), RTXDI_GetNextRandom(rng)))
            / float2(g_Const.environmentPdfTextureSize);
        result += PathLightSample(surface, g_Const.lightBufferParams.environmentLightParams.lightIndex, uv, pdf);
    }
    RTXDI_LightBufferRegion distant = g_Const.lightBufferParams.infiniteLightBufferRegion;
    if (distant.numLights > 0)
    {
        uint index = min(uint(RTXDI_GetNextRandom(rng) * distant.numLights), distant.numLights - 1);
        float2 uv = float2(RTXDI_GetNextRandom(rng), RTXDI_GetNextRandom(rng));
        result += PathLightSample(surface, distant.firstLightIndex + index, uv, 1.0 / distant.numLights);
    }
    return result;
}

float3 PathReference(RAB_Surface surface, inout RTXDI_RandomSamplerState rng, uint maxScattering)
{
    float3 result = 0, throughput = 1;
    for (uint scattering = 0; scattering < maxScattering; ++scattering)
    {
        result += throughput * PathNee(surface, rng);
        // Historical opaque DI excludes delta reflection and uses only the
        // indexed-light domains. Its emission/background/glass are composited.
        if (maxScattering == 1) break;

        float3 direction;
        RTXDI_BrdfRaySampleProperties properties = RTXDI_DefaultBrdfRaySampleProperties();
        if (!RAB_SurfaceImportanceSampleBsdf(surface, rng, direction, properties) ||
            dot(direction, surface.geoNormal) <= 0) break;
        if (properties.IsDelta())
        {
            // This native helper already includes the discrete lobe probability.
            throughput *= RAB_SurfaceEvaluateDeltaReflectionThroughput(surface, direction);
        }
        else
        {
            float pdf = RAB_SurfaceEvaluateBsdfPdf(surface, direction, properties);
            if (pdf <= 0) break;
            throughput *= RAB_SurfaceEvaluateBsdfTimesNoL(surface, direction, false) / pdf;
        }
        // No Russian roulette, throughput cutoff, radiance clamp or extra bounces.
        RayDesc ray = setupContinuationRay(surface.geoNormal, surface.worldPos, direction);
        RAB_RayPayload hit = TraceNextBounce(ray);
        throughput *= hit.throughput;
        if (!RAB_IsValidHit(hit))
        {
            if (properties.IsDelta() && g_Const.sceneConstants.enableEnvironmentMap)
                result += throughput * RAB_GetEnvironmentRadiance(direction);
            break; // Continuous environment paths were accounted for by NEE.
        }
        PSRData unusedPsr = (PSRData)0;
        RAB_Surface next = LoadSurfaceFromRayPayload(hit, ray, surface, unusedPsr);
        uint emitter = GetLightIndex(hit.instanceID, hit.geometryIndex, hit.primitiveIndex);
        if ((properties.IsDelta() || emitter == RTXDI_InvalidLightIndex) && RAB_RayPayloadIsFrontFace(hit))
            result += throughput * next.material.emissiveColor;
        surface = next;
        // A terminal emission hit is an endpoint, not another scattering event.
    }
    return result;
}

#if USE_RAY_QUERY
[numthreads(RTXDI_SCREEN_SPACE_GROUP_SIZE, RTXDI_SCREEN_SPACE_GROUP_SIZE, 1)]
void main(uint2 pixel : SV_DispatchThreadID)
#else
[shader("raygeneration")]
void RayGen()
#endif
{
#if !USE_RAY_QUERY
    uint2 pixel = DispatchRaysIndex().xy;
#endif
    if (any(pixel >= uint2(g_Const.view.viewportSize))) return;
    RAB_Surface surface = RAB_GetGBufferSurface(pixel, false);
    float3 value = 0;
    RTXDI_RandomSamplerState rng = RTXDI_InitRandomSampler(pixel, g_Const.runtimeParams.frameIndex, 0x50545246u);
    if (RAB_IsSurfaceValid(surface))
        value = PathReference(surface, rng, g_Const.restirDI.spatialResamplingParams.pad1);
    // Carry total radiance through the existing compositing contract. Its specular
    // remodulation uses the identical nonzero floor; emission/background add once.
    u_DiffuseLighting[pixel] = 0;
    u_SpecularLighting[pixel] = float4(DemodulateSpecular(surface.material.specularF0, value), 0);
}
