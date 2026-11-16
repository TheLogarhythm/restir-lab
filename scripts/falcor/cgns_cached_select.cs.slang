import ReSTIRPathTracingParams;
import Utils.Sampling.TinyUniformSampleGenerator;

cbuffer CB
{
    ReSTIRPathTracingParams params;
    Texture2D<float4> positions;
    Texture2D<float4> normals;
    Texture1D<float2> neighborOffsets;
    float radius;
    uint roundId;
    RWTexture2D<uint> selected;
};

static const uint kNeighborOffsetCount = NEIGHBOR_OFFSET_COUNT;
static const uint kNeighborOffsetMask = kNeighborOffsetCount - 1;

// The host proves when quantized offsets cannot round to the same pixel.
// Other radii retain the general selector with its exact duplicate checks.
__LAB_SELECTOR__

uint encodeNeighbor(int2 neighbor)
{
    return neighbor.x < 0 ? 0xffffffffu : uint(neighbor.y) * params.frameDim.x + uint(neighbor.x);
}

[numthreads(8, 8, 1)]
void main(uint2 pixel : SV_DispatchThreadID)
{
    if (any(pixel >= params.frameDim)) return;
    selected[pixel] = encodeNeighbor(labCgnsSelectPointNeighbors(params, positions, normals, neighborOffsets,
                                                                 pixel, roundId, radius, 1).pixels[0]);
}

[numthreads(8, 8, 1)]
void selectDistinct(uint2 pixel : SV_DispatchThreadID)
{
    if (any(pixel >= params.frameDim)) return;
    selected[pixel] = encodeNeighbor(labCgnsDistinctNeighbors(params, positions, normals, neighborOffsets,
                                                              pixel, roundId, radius, 1).pixels[0]);
}
