// LAB_CGNS_POINT_SELECTOR_V1: experimental Falcor 9 point-reservoir CGNS.
// K=32 geometry proposals; A-ES selects four distinct neighbors without replacement.
// Falcor's existing RG8Snorm disk offsets use a different R2 disk construction.
struct LabCgnsPointSelection
{
    int2 pixels[4];
    float priorities[4];
    uint count;
};

LabCgnsPointSelection labCgnsSelectPointNeighbors(
    ReSTIRPathTracingParams params, Texture2D<PackedHitInfo> vbuffer,
    Texture1D<float2> neighborOffsets, uint2 pixel, int roundId,
    float radius, int capacity)
{
    LabCgnsPointSelection result;
    result.count = 0;
    [unroll] for (int i = 0; i < 4; ++i)
    {
        result.pixels[i] = int2(-1, -1);
        result.priorities[i] = -3.402823466e38f;
    }
    // Unsupported capacities and invalid centers fail closed, not native fallback.
    if (capacity != 4 || radius <= 0.f) return result;
    HitInfo centerHit;
    ShadingData center = getPixelShadingData(params, vbuffer, int2(pixel), centerHit);
    if (!centerHit.isValid()) return result;
    float camDistance = distance(center.posW, gScene.camera.data.posW);
    float scale = camDistance * sqrt(0.05f / 3.14159265358979323846f);
    if (scale <= 0.f || isnan(scale) || isinf(scale)) return result;

    // Dedicated stream: identical pixel/frame/round inputs in every consuming pass.
    uint seed = params.seed ^ (uint(roundId) * 0x9e3779b9u) ^ 0x43474e53u;
    var cgnsSg = TinyUniformSampleGenerator(pixel, seed);
    uint start = uint(sampleNext1D(cgnsSg) * kNeighborOffsetCount);
    int2 seen[32];
    uint seenCount = 0;
    uint good = 0;
    [loop] for (uint k = 0; k < 32; ++k)
    {
        float2 delta = neighborOffsets[(start + k) & kNeighborOffsetMask] * radius;
        int2 candidate = int2(round(float2(pixel) + delta));
        if (!isValidScreenRegion(params, candidate) || all(candidate == int2(pixel))) continue;
        bool duplicate = false;
        [loop] for (uint j = 0; j < seenCount; ++j) duplicate |= all(seen[j] == candidate);
        if (duplicate) continue;
        seen[seenCount++] = candidate;
        HitInfo candidateHit;
        ShadingData neighbor = getPixelShadingData(params, vbuffer, candidate, candidateHit);
        if (!candidateHit.isValid()) continue;
        float d = distance(center.posW, neighbor.posW);
        float cosine = clamp(dot(center.frame.N, neighbor.frame.N), 0.f, 1.f);
        float score = exp(-d / scale) * pow(cosine, 8.f);
        if (isnan(score) || isinf(score) || score <= 0.f) continue;
        float u = max(sampleNext1D(cgnsSg), 1e-8f);
        float key = log(score) - log(-log(u));
        uint slot = result.count;
        if (slot == 4)
        {
            slot = 0;
            [unroll] for (uint i = 1; i < 4; ++i)
                if (result.priorities[i] < result.priorities[slot]) slot = i;
            if (key <= result.priorities[slot])
            {
                if (score >= 0.5f && ++good >= 4) break;
                continue;
            }
        }
        else result.count++;
        result.pixels[slot] = candidate;
        result.priorities[slot] = key;
        if (score >= 0.5f && ++good >= 4) break;
    }
    return result;
}
