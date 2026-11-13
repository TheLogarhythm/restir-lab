// LAB_CGNS_SINGLE_SELECTOR_V1: independent one-neighbor, point-reservoir CGNS.
// K=32, A-Chao, scale 0.05, normal exponent 8, early stop after 1 score >=0.5.
struct LabCgnsPointSelection
{
    int2 pixels[4];
    uint count;
};
LabCgnsPointSelection labCgnsSelectPointNeighbors(
    ReSTIRPathTracingParams params, Texture2D<PackedHitInfo> vbuffer,
    Texture1D<float2> neighborOffsets, uint2 pixel, int roundId,
    float radius, int capacity)
{
    LabCgnsPointSelection result;
    result.count=0;
    [unroll] for (int i=0; i<4; ++i) result.pixels[i]=int2(-1, -1);
    if (capacity != 1 || !(radius > 0.f)) return result;
    HitInfo centerHit;
    ShadingData center=getPixelShadingData(params, vbuffer, int2(pixel), centerHit);
    if (!centerHit.isValid()) return result;
    float camDistance=distance(center.posW, gScene.camera.data.posW);
    float scale=camDistance * sqrt(0.05f / 3.14159265358979323846f);
    if (scale <= 0.f || isnan(scale) || isinf(scale)) return result;
    uint seed=params.seed ^ (uint(roundId) * 0x9e3779b9u) ^ 0x43474e53u;
    var cgnsSg=TinyUniformSampleGenerator(pixel, seed);
    uint start=uint(sampleNext1D(cgnsSg) * kNeighborOffsetCount);
    int2 seen[32];
    uint seenCount=0;
    uint good=0;
    LabCgnsSingleWrs reservoir=LabCgnsSingleCreate();
    [loop] for (uint k=0; k<32; ++k)
    {
        float2 delta=neighborOffsets[(start+k) & kNeighborOffsetMask]*radius;
        int2 candidate=int2(round(float2(pixel)+delta));
        if (!isValidScreenRegion(params,candidate) || all(candidate==int2(pixel))) continue;
        bool duplicate=false;
        [loop] for (uint j=0; j<seenCount; ++j) duplicate |= all(seen[j]==candidate);
        if (duplicate) continue;
        uint candidateIndex=seenCount;
        seen[seenCount++]=candidate;
        HitInfo candidateHit;
        ShadingData neighbor=getPixelShadingData(params,vbuffer,candidate,candidateHit);
        if (!candidateHit.isValid()) continue;
        float d=distance(center.posW,neighbor.posW);
        float cosine=clamp(dot(center.frame.N,neighbor.frame.N),0.f,1.f);
        float score=exp(-d/scale)*pow(cosine,8.f);
        if (isnan(score) || isinf(score) || score<=0.f) continue;
        LabCgnsSingleInsert(reservoir,candidateIndex,score,sampleNext1D(cgnsSg));
        if (score>=0.5f && ++good >= 1) break;
    }
    if (reservoir.valid)
    {
        result.pixels[0]=seen[reservoir.selected];
        result.count=1;
    }
    return result;
}
