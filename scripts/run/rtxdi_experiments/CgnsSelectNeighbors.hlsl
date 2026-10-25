// Geometry-only preselection for the unfused ReSTIR DI spatial pass.
#pragma pack_matrix(row_major)
#include "../RtxdiApplicationBridge/RtxdiApplicationBridge.hlsli"
#include "Cgns.hlsli"

[numthreads(RTXDI_SCREEN_SPACE_GROUP_SIZE, RTXDI_SCREEN_SPACE_GROUP_SIZE, 1)]
void main(uint2 pixel : SV_DispatchThreadID)
{
    uint2 extent = uint2(g_Const.view.viewportSize);
    if (any(pixel >= extent)) return;
    uint pixelIndex = pixel.y * extent.x + pixel.x;
    LabCgnsReservoir selection = LabCgnsCreateReservoir();
    uint tried = 0, scored = 0, good = 0;
    float3 center, centerNormal;
    if (LabCgnsSurface(int2(pixel), center, centerNormal))
    {
        float cameraDistance = distance(center, g_Const.view.cameraDirectionOrPosition.xyz);
        RTXDI_DISpatialResamplingParameters params = g_Const.restirDI.spatialResamplingParams;
        // Separate stream leaves all light-sampling RNG sequences unchanged.
        RTXDI_RandomSamplerState rng = RTXDI_InitRandomSampler(pixel, g_Const.runtimeParams.frameIndex, 0x43474e53u);
        uint start = uint(RTXDI_GetNextRandom(rng) * LAB_CGNS_DISK_SAMPLES);
        uint seen[32];
        uint seenCount = 0;
        for (uint k = 0; k < params.pad2; ++k)
        {
            ++tried;
            float2 offset = t_CgnsOffsets[(start + k) & (LAB_CGNS_DISK_SAMPLES - 1)];
            int2 candidate = int2(round(float2(pixel) + offset * params.samplingRadius));
            if (any(candidate < 0) || any(candidate >= int2(extent)) || all(candidate == int2(pixel))) continue;
            uint packed = uint(candidate.x) | (uint(candidate.y) << 16);
            bool duplicate = false;
            for (uint j = 0; j < seenCount; ++j) duplicate |= seen[j] == packed;
            if (duplicate) continue;
            seen[seenCount++] = packed;
            float3 position, normal;
            if (!LabCgnsSurface(candidate, position, normal)) continue;
            ++scored;
            float score = LabCgnsScore(distance(center, position), dot(centerNormal, normal), cameraDistance, 0.05f, 8.f);
            LabCgnsInsert(selection, packed, score, RTXDI_GetNextRandom(rng), params.numSamples);
            if (score >= 0.5f) ++good;
            // Match the author's code (>= M), which differs from the paper's prose (> M).
            if (params.pad3 != 0 && good >= params.numSamples) break;
        }
    }
    for (uint i = 0; i < LAB_CGNS_MAX_NEIGHBORS; ++i)
        u_SpatialNeighborSelection.Store((pixelIndex * LAB_CGNS_MAX_NEIGHBORS + i) * 4, selection.pixels[i]);
    // Capture diagnostics: tried, valid unique geometry taps, selected neighbors (one byte each).
    u_CgnsStatistics[pixelIndex] = tried | (scored << 8) | (selection.count << 16);
}
