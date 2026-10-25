// CGNS coordinates are selected once, then reused by both DI resampling loops.
#ifndef LAB_CGNS_HLSLI
#define LAB_CGNS_HLSLI
#include "CgnsMath.h"

Buffer<float2> t_CgnsOffsets : register(t26);
RWStructuredBuffer<uint> u_CgnsStatistics : register(u31);

bool LabCgnsEnabled() { return g_Const.restirDI.spatialResamplingParams.pad1 != 0; }

bool LabCgnsNeighbor(uint2 pixel, uint index, out int2 position)
{
    uint pixelIndex = pixel.y * uint(g_Const.view.viewportSize.x) + pixel.x;
    uint packed = u_SpatialNeighborSelection.Load((pixelIndex * LAB_CGNS_MAX_NEIGHBORS + index) * 4);
    position = int2(packed & 0xffffu, packed >> 16);
    return packed != LAB_CGNS_INVALID_PIXEL;
}

// Only primary geometry enters the score: no light reservoir or radiance reads.
bool LabCgnsSurface(int2 pixel, out float3 position, out float3 normal)
{
    float depth = t_GBufferDepth[pixel];
    position = ViewDepthToWorldPos(g_Const.view, pixel, depth);
    normal = octToNdirUnorm32(t_GBufferNormals[pixel]);
    return depth != BACKGROUND_DEPTH && all(isfinite(position)) && all(isfinite(normal));
}
#endif
