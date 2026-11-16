// Diagnostic-only oracle. Read the current V-buffer directly, using the
// original selector, and compare every ID including the invalid sentinel.
import ResamplingCommon;
import ReSTIRPathTracingParams;
import Scene.ShadingData;
import Scene.Scene;
import Utils.Sampling.TinyUniformSampleGenerator;

cbuffer CB
{
    ReSTIRPathTracingParams params;
    Texture2D<PackedHitInfo> vbuffer;
    Texture1D<float2> neighborOffsets;
    Texture2D<uint> selected;
    RWByteAddressBuffer counts;
    float radius;
    uint roundId;
};

__LAB_SELECTOR__

[numthreads(8, 8, 1)]
void main(uint2 pixel : SV_DispatchThreadID)
{
    if (any(pixel >= params.frameDim)) return;
    var choice = labCgnsSelectPointNeighbors(params, vbuffer, neighborOffsets, pixel, roundId, radius, 1);
    int2 neighbor = choice.pixels[0];
    uint expected = neighbor.x < 0 ? 0xffffffffu : uint(neighbor.y) * params.frameDim.x + uint(neighbor.x);
    if (expected != 0xffffffffu) counts.InterlockedAdd(0, 1);
    if (selected[pixel] != expected) counts.InterlockedAdd(4, 1);
}
