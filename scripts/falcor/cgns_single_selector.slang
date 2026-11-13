// LAB_CGNS_SINGLE_SELECTOR_V1: independent one-neighbor, point-reservoir CGNS.
// Configuration supplies the LAB_CGNS_* compile-time definitions.
#if !defined(LAB_CGNS_CANDIDATE_COUNT) || !defined(LAB_CGNS_POSITION_SCALE) || !defined(LAB_CGNS_NORMAL_EXPONENT) || !defined(LAB_CGNS_EARLY_STOP_SCORE) || !defined(LAB_CGNS_EARLY_STOP_COUNT)
#error CGNS shader parameters must be specified by the experiment configuration.
#endif
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
    float scale=camDistance * sqrt(LAB_CGNS_POSITION_SCALE / 3.14159265358979323846f);
    if (scale <= 0.f || isnan(scale) || isinf(scale)) return result;
    uint seed=params.seed ^ (uint(roundId) * 0x9e3779b9u) ^ 0x43474e53u;
    var cgnsSg=TinyUniformSampleGenerator(pixel, seed);
    uint start=uint(sampleNext1D(cgnsSg) * kNeighborOffsetCount);
    int2 seen[LAB_CGNS_CANDIDATE_COUNT];
    uint seenCount=0;
    uint good=0;
    LabCgnsSingleWrs reservoir=LabCgnsSingleCreate();
    [loop] for (uint k=0; k<LAB_CGNS_CANDIDATE_COUNT; ++k)
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
        float score=exp(-d/scale)*pow(cosine,LAB_CGNS_NORMAL_EXPONENT);
        if (isnan(score) || isinf(score) || score<=0.f) continue;
        LabCgnsSingleInsert(reservoir,candidateIndex,score,sampleNext1D(cgnsSg));
        if (score>=LAB_CGNS_EARLY_STOP_SCORE && ++good >= LAB_CGNS_EARLY_STOP_COUNT) break;
    }
    if (reservoir.valid)
    {
        result.pixels[0]=seen[reservoir.selected];
        result.count=1;
    }
    return result;
}
