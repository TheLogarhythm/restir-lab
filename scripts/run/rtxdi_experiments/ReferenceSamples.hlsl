// Conventional direct lighting: every sample is shaded; no reservoir or RIS pool.
// Uses pinned RTXDI's scene/BSDF/light/visibility conventions for a matched target.
#pragma pack_matrix(row_major)
#include "../RtxdiApplicationBridge/RtxdiApplicationBridge.hlsli"
#include <Rtxdi/LightSampling/PresamplingFunctions.hlsli>
#include "../ShadingHelpers.hlsli"

void AddSample(RAB_Surface surface, uint index, float2 uv, float sourcePdf,
               uint count, inout float3 diffuse, inout float3 specular)
{
    if (sourcePdf <= 0 || count == 0) return;
    RAB_LightSample sample = RAB_SamplePolymorphicLight(RAB_LoadLightInfo(index, false), surface, uv);
    if (sample.solidAnglePdf <= 0) return;
    SplitBrdf brdf = EvaluateBrdf(surface, sample.position);
    if (brdf.demodulatedDiffuse == 0 && !any(brdf.specular > 0)) return;
    float3 radiance = sample.radiance * GetFinalVisibility(SceneBVH, surface, sample.position)
        / (sourcePdf * sample.solidAnglePdf * count);
    diffuse += brdf.demodulatedDiffuse * radiance;
    specular += brdf.specular * radiance;
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
    RAB_Surface surface = RAB_GetGBufferSurface(pixel, false);
    float3 diffuse = 0, specular = 0;
    RTXDI_RandomSamplerState rng = RTXDI_InitRandomSampler(pixel, g_Const.runtimeParams.frameIndex, 0x7351u);
    if (RAB_IsSurfaceValid(surface))
    {
        RTXDI_LightBufferRegion local = g_Const.lightBufferParams.localLightBufferRegion;
        uint count = g_Const.restirDI.initialSamplingParams.numLocalLightSamples;
        for (uint i = 0; i < count && local.numLights > 0; ++i)
        {
            uint index;
            float pdf;
            if (g_Const.restirDI.initialSamplingParams.localLightSamplingMode == 0)
            {
                index = min(uint(RTXDI_GetNextRandom(rng) * local.numLights), local.numLights - 1);
                pdf = 1.0 / local.numLights;
            }
            else
            {
                uint2 texel;
                RTXDI_SamplePdfMipmap(rng, t_LocalLightPdfTexture, g_Const.localLightPdfTextureSize, texel, pdf);
                index = RTXDI_ZCurveToLinearIndex(texel);
            }
            float2 uv = float2(RTXDI_GetNextRandom(rng), RTXDI_GetNextRandom(rng));
            if (index < local.numLights)
                AddSample(surface, local.firstLightIndex + index, uv, pdf, count, diffuse, specular);
        }
        count = g_Const.restirDI.initialSamplingParams.numEnvironmentSamples;
        for (uint j = 0; j < count && g_Const.lightBufferParams.environmentLightParams.lightPresent; ++j)
        {
            uint2 texel;
            float pdf;
            RTXDI_SamplePdfMipmap(rng, t_EnvironmentPdfTexture, g_Const.environmentPdfTextureSize, texel, pdf);
            float2 uv = (float2(texel) + float2(RTXDI_GetNextRandom(rng), RTXDI_GetNextRandom(rng)))
                / float2(g_Const.environmentPdfTextureSize);
            AddSample(surface, g_Const.lightBufferParams.environmentLightParams.lightIndex, uv, pdf, count, diffuse, specular);
        }
        RTXDI_LightBufferRegion distant = g_Const.lightBufferParams.infiniteLightBufferRegion;
        count = g_Const.restirDI.initialSamplingParams.numInfiniteLightSamples;
        // Select a distant light uniformly; sample its finite angular extent too.
        for (uint k = 0; k < count && distant.numLights > 0; ++k)
        {
            uint index = min(uint(RTXDI_GetNextRandom(rng) * distant.numLights), distant.numLights - 1);
            float2 uv = float2(RTXDI_GetNextRandom(rng), RTXDI_GetNextRandom(rng));
            AddSample(surface, distant.firstLightIndex + index, uv, 1.0 / distant.numLights, count, diffuse, specular);
        }
    }
    u_DiffuseLighting[pixel] = float4(diffuse, 0);
    u_SpecularLighting[pixel] = float4(DemodulateSpecular(surface.material.specularF0, specular), 0);
}
