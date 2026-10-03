// Independent RTXDI adaptation of Tokuyoshi 2023, Algorithm 2.
#ifndef LAB_PDF_SIMILARITY_HLSLI
#define LAB_PDF_SIMILARITY_HLSLI
#include "PdfSimilarityMath.h"
#include "PdfReservoirMath.h"
#include <Rtxdi/DI/Reservoir.hlsli>

RWStructuredBuffer<LabDirectionReservoir> u_LabDirections : register(u31);

bool LabPdfEnabled() { return g_Const.restirDI.spatialResamplingParams.pad1 != 0; }
uint LabDirectionAddress(uint2 pixel, uint bank)
{
    uint2 size = uint2(g_Const.view.viewportSize);
    return (bank * size.y + pixel.y) * size.x + pixel.x;
}
RAB_LightSample LabDirectionSample(uint data, uint uv, RAB_Surface surface, bool previous)
{
    RTXDI_DIReservoir r = RTXDI_EmptyDIReservoir();
    r.uvData = uv;
    return RAB_SamplePolymorphicLight(RAB_LoadLightInfo(data & RTXDI_DIReservoir_LightIndexMask, previous),
        surface, RTXDI_GetDIReservoirSampleUV(r));
}
float3 LabLightDirection(RAB_Surface surface, RAB_LightSample sample)
{
    float3 direction; float distance;
    RAB_GetLightDirDistance(surface, sample, direction, distance);
    return direction;
}

void LabUpdateDirection(uint2 pixel, RAB_Surface surface, RTXDI_DIReservoir initial, RAB_LightSample sample)
{
    uint bank = g_Const.runtimeParams.frameIndex & 1;
    LabDirectionReservoir result = (LabDirectionReservoir)0;
    if (!RAB_IsSurfaceValid(surface)) {
        u_LabDirections[LabDirectionAddress(pixel, bank)] = result;
        return;
    }
    result.lightData = initial.lightData;
    result.uvData = initial.uvData;
    result.W = initial.weightSum;
    result.M = 1.f;
    if (result.W > 0.f) result.moment = LabLightDirection(surface, sample);

    float3 motion = ConvertMotionVectorToPixelSpace(g_Const.view, g_Const.prevView, pixel, t_MotionVectors[pixel].xyz);
    int2 prevPixel = int2(round(float2(pixel) + motion.xy));
    // A nearest reprojected texel, with explicit bounds and geometry/material rejection.
    if (all(prevPixel >= 0) && all(prevPixel < int2(g_Const.prevView.viewportSize))) {
        RAB_Surface previous = RAB_GetGBufferSurface(prevPixel, true);
        RTXDI_DITemporalResamplingParameters tp = g_Const.restirDI.temporalResamplingParams;
        if (RAB_IsSurfaceValid(previous) && RTXDI_IsValidNeighbor(surface.normal, previous.normal,
            surface.viewDepth + motion.z, previous.viewDepth, tp.normalThreshold, tp.depthThreshold)
            && RAB_AreMaterialsSimilar(surface.material, previous.material)) {
            LabDirectionReservoir old = u_LabDirections[LabDirectionAddress(uint2(prevPixel), bank ^ 1)];
            if (old.W > 0.f && old.M > 0.f && old.lightData != 0) {
                int mapped = RAB_TranslateLightIndex(old.lightData & RTXDI_DIReservoir_LightIndexMask, false);
                if (mapped >= 0) {
                    RAB_LightSample oldAtOld = LabDirectionSample(old.lightData, old.uvData, previous, true);
                    RAB_LightSample oldAtHere = LabDirectionSample(uint(mapped), old.uvData, surface, false);
                    float cosine = dot(LabLightDirection(previous, oldAtOld), LabLightDirection(surface, oldAtHere));
                    float oldM = LabDirectionHistory(old.M, cosine);
                    float pOld = RAB_GetLightSampleTargetPdfForSurface(oldAtOld, previous);
                    float pHere = RAB_GetLightSampleTargetPdfForSurface(oldAtHere, surface);
                    float pInitial = result.W > 0.f ? initial.targetPdf : 0.f;
                    float pInitialOld = 0.f;
                    if (result.W > 0.f) {
                        int oldID = RAB_TranslateLightIndex(initial.lightData & RTXDI_DIReservoir_LightIndexMask, true);
                        if (oldID >= 0) pInitialOld = RAB_GetLightSampleTargetPdfForSurface(
                            LabDirectionSample(uint(oldID), initial.uvData, previous, true), previous);
                    }
                    old.lightData = uint(mapped) | RTXDI_DIReservoir_LightValidBit;
                    RTXDI_RandomSamplerState rng = RTXDI_InitRandomSampler(pixel, g_Const.runtimeParams.frameIndex, 719);
                    result = LabMergeDirection(result, old, pInitial, pInitialOld,
                        pHere, pOld, oldM, RTXDI_GetNextRandom(rng));
                }
            }
        }
    }
    if (!isfinite(result.W) || !all(isfinite(result.moment))) result = (LabDirectionReservoir)0;
    u_LabDirections[LabDirectionAddress(pixel, bank)] = result;
}

float LabSpatialWeight(uint2 pixel, uint2 neighbor, RAB_Surface center, RAB_Surface other)
{
    if (!LabPdfEnabled()) return 1.f;
    RTXDI_DISpatialResamplingParameters sp = g_Const.restirDI.spatialResamplingParams;
    float previous = RTXDI_IsValidNeighbor(center.normal, other.normal, center.viewDepth, other.viewDepth,
        sp.normalThreshold, sp.depthThreshold) && (!sp.enableMaterialSimilarityTest ||
        RAB_AreMaterialsSimilar(center.material, other.material)) ? 1.f : 0.f;
    uint bank = g_Const.runtimeParams.frameIndex & 1;
    LabDirectionReservoir a = u_LabDirections[LabDirectionAddress(pixel, bank)];
    LabDirectionReservoir b = u_LabDirections[LabDirectionAddress(neighbor, bank)];
    if (a.W <= 0.f || b.W <= 0.f) return previous;
    float ra = length(a.moment), rb = length(b.moment);
    float cosine = ra * rb > 1e-12f ? dot(a.moment, b.moment) / (ra*rb) : 0.f;
    return lerp(previous, LabPdfSimilarity(ra, rb, cosine), LabPdfConfidence(a.M, b.M));
}
#endif
