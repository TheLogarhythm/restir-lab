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

// The second half of the diagnostic buffer is written only by spatial reuse.
// 0 = background; 128 + count = valid center and reservoirs reaching the merge call.
// Separate words preserve historical CGNS counters and introduce no RNG reads.
void LabClearSpatialNeighbors(uint2 pixel)
{
    uint2 extent = uint2(g_Const.view.viewportSize);
    if (any(pixel >= extent)) return;
    u_CgnsStatistics[extent.x * extent.y + pixel.y * extent.x + pixel.x] = 0;
}

void LabRecordSpatialNeighbors(uint2 pixel, uint count)
{
    uint2 extent = uint2(g_Const.view.viewportSize);
    if (any(pixel >= extent)) return;
    u_CgnsStatistics[extent.x * extent.y + pixel.y * extent.x + pixel.x] = 128u + count;
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
