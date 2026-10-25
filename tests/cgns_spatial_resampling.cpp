// CPU harness for the actual RTXDI functions, with deterministic samples and G-buffer taps.
#include <algorithm>
#include <cassert>
#include <cmath>
#include <vector>
using uint = unsigned;
using std::min; using std::max;
uint min(uint a, int b) { return std::min(a, uint(b)); }
struct int2;
struct float2 { float x, y; float2(float a=0, float b=0): x(a), y(b) {} };
float2 operator*(float2 a, float b) { return {a.x*b, a.y*b}; }
struct uint2 { uint x, y; uint2(uint a=0, uint b=0): x(a), y(b) {} uint2(int2); };
struct int2 {
    int x, y; int2(int a=0, int b=0): x(a), y(b) {}
    int2(uint2 v): x(v.x), y(v.y) {} int2(float2 v): x(int(v.x)), y(int(v.y)) {}
    int2& operator+=(int2 v) { x+=v.x; y+=v.y; return *this; }
};
uint2::uint2(int2 v): x(v.x), y(v.y) {}
int2 operator+(int2 a, int2 b) { return {a.x+b.x, a.y+b.y}; }
int2 operator-(int2 a, int2 b) { return {a.x-b.x, a.y-b.y}; }
struct RTXDI_DIReservoir {
    uint lightData=0, uvData=0; float weightSum=0, targetPdf=0, M=0;
    uint packedVisibility=0; int2 spatialDistance; uint age=0;
};
struct RAB_Surface { int id; };
struct RAB_LightInfo { uint id; };
struct RAB_LightSample { uint id; };
struct RTXDI_RandomSamplerState { uint calls=0; };
struct RTXDI_RuntimeParameters { uint neighborOffsetMask=3, activeCheckerboardField=0; };
struct RTXDI_ReservoirBufferParameters {};
struct RTXDI_DISpatialResamplingParameters {
    int biasCorrectionMode=2; uint numSamples=4, numDisocclusionBoostSamples=0;
    float targetHistoryLength=0, samplingRadius=1, normalThreshold=0, depthThreshold=0;
    bool enableMaterialSimilarityTest=true, discountNaiveSamples=false;
};
#define RTXDI_DEFAULT(value) = value
#define RTXDI_BIAS_CORRECTION_BASIC 1
#define RTXDI_BIAS_CORRECTION_RAY_TRACED 2
#define RTXDI_BIAS_CORRECTION_PAIRWISE 3
#define RTXDI_ALLOWED_BIAS_CORRECTION 2
#define RTXDI_NAIVE_SAMPLING_M_THRESHOLD 1
struct Offset { float2 xy; } RTXDI_NEIGHBOR_OFFSETS_BUFFER[] = {{{1,0}},{{2,0}},{{3,0}},{{4,0}}};
RTXDI_DIReservoir reservoirs[5];
float randomValues[5] = {0, .99f, .99f, .99f, .99f};
bool enabled, geometryAccepted, materialAccepted, hiddenThird;
int picks[4] = {4,-1,3,-1};
std::vector<int> surfaceLoads, reservoirLoads;
uint neighborCallbacks;
RTXDI_DIReservoir RTXDI_EmptyDIReservoir() { return {}; }
bool RTXDI_IsValidDIReservoir(RTXDI_DIReservoir r) { return r.lightData != 0; }
uint RTXDI_GetDIReservoirLightIndex(RTXDI_DIReservoir r) { return r.lightData; }
float2 RTXDI_GetDIReservoirSampleUV(RTXDI_DIReservoir) { return {}; }
RAB_LightInfo RAB_EmptyLightInfo() { return {0}; }
RAB_LightSample RAB_EmptyLightSample() { return {0}; }
RAB_LightInfo RAB_LoadLightInfo(uint id, bool) { return {id}; }
RAB_LightSample RAB_SamplePolymorphicLight(RAB_LightInfo light, RAB_Surface, float2) { return {light.id}; }
float RAB_GetLightSampleTargetPdfForSurface(RAB_LightSample light, RAB_Surface surface) {
    const float pdf[5][3] = {{2,3,5},{3,5,7},{5,9,13},{4,7,11},{6,13,17}};
    assert(light.id >= 1 && light.id <= 3 && surface.id >= 0 && surface.id <= 4);
    return pdf[surface.id][light.id-1];
}
float RTXDI_GetNextRandom(RTXDI_RandomSamplerState& rng) {
    assert(rng.calls < 5); return randomValues[rng.calls++];
}
int2 RAB_ClampSamplePositionIntoView(int2 p, bool) { return p; }
void RTXDI_ActivateCheckerboardPixel(int2&, bool, uint) {}
RAB_Surface RAB_GetGBufferSurface(int2 p, bool) { surfaceLoads.push_back(p.x); return {p.x}; }
bool RAB_IsSurfaceValid(RAB_Surface s) { return s.id >= 0 && s.id <= 4; }
float RAB_GetSurfaceNormal(RAB_Surface) { return 0; }
float RAB_GetSurfaceLinearDepth(RAB_Surface) { return 0; }
bool RTXDI_IsValidNeighbor(float, float, float, float, float, float) { return geometryAccepted; }
int RAB_GetMaterial(RAB_Surface) { return 0; }
bool RAB_AreMaterialsSimilar(int, int) { return materialAccepted; }
uint2 RTXDI_PixelPosToReservoirPos(int2 p, uint) { return uint2(p); }
RTXDI_DIReservoir RTXDI_LoadDIReservoir(RTXDI_ReservoirBufferParameters, uint2 p, uint) {
    assert(p.x < 5); reservoirLoads.push_back(p.x); return reservoirs[p.x];
}
bool RAB_GetConservativeVisibility(RAB_Surface s, RAB_LightSample) { return !(hiddenThird && s.id == 3); }
bool LabCgnsEnabled() { return enabled; }
bool LabCgnsNeighbor(uint2, uint index, int2& position) {
    assert(index < 4); ++neighborCallbacks;
    position = {picks[index], 0}; return picks[index] >= 0;
}
RTXDI_DIReservoir RTXDI_DISpatialResamplingWithPairwiseMIS(uint2, RAB_Surface, RTXDI_DIReservoir,
    RTXDI_RandomSamplerState&, RTXDI_RuntimeParameters, RTXDI_ReservoirBufferParameters,
    uint, RTXDI_DISpatialResamplingParameters, RAB_LightSample&) { assert(false); return {}; }
#include "spatial_under_test.h"

void close(float a, float b) { assert(std::abs(a-b) < 2e-6f); }
void clearReads() { surfaceLoads.clear(); reservoirLoads.clear(); neighborCallbacks=0; }
void equal(const RTXDI_DIReservoir& a, const RTXDI_DIReservoir& b) {
    assert(a.lightData==b.lightData && a.uvData==b.uvData && a.packedVisibility==b.packedVisibility);
    assert(a.age==b.age && a.spatialDistance.x==b.spatialDistance.x && a.spatialDistance.y==b.spatialDistance.y);
    assert(a.M==b.M && a.targetPdf==b.targetPdf && a.weightSum==b.weightSum);
}

int main() {
    auto& center = reservoirs[0];
    center.lightData=1; center.targetPdf=2; center.M=2; center.weightSum=1.5f;
    reservoirs[1].lightData=2; reservoirs[1].targetPdf=5; reservoirs[1].M=7; reservoirs[1].weightSum=.5f;
    reservoirs[2].lightData=3; reservoirs[2].targetPdf=13; reservoirs[2].M=11; reservoirs[2].weightSum=.25f;
    reservoirs[3].lightData=2; reservoirs[3].targetPdf=7; reservoirs[3].M=3; reservoirs[3].weightSum=.5f;
    reservoirs[4].lightData=3; reservoirs[4].targetPdf=17; reservoirs[4].M=5; reservoirs[4].weightSum=.25f;

    // Center and selected neighbors have translated weights 6, 6.25, 4.5 (sum 16.75).
    // Literal expected normalizations use the selected light evaluated at pixels 0,4,3.
    struct Case { float first, second; uint light; float target, full, occluded; int source; };
    const Case cases[] = {
        {.99f,.99f,1,2,16.75f/46.f,16.75f/34.f,0},
        {0,.99f,3,5,284.75f/640.f,284.75f/475.f,4},
        {.99f,0,2,3,117.25f/276.f,0,3}
    };
    enabled=true; geometryAccepted=false; materialAccepted=false;
    for (const auto& c : cases) for (bool hidden : {false,true}) {
        hiddenThird=hidden; randomValues[1]=c.first; randomValues[2]=c.second;
        clearReads(); RTXDI_RandomSamplerState rng; RAB_LightSample light{};
        auto r=RTXDI_DISpatialResampling({}, {0}, center, rng, {}, {}, 0, {}, light);
        assert(r.lightData==c.light && r.spatialDistance.x==c.source);
        close(r.M,10); close(r.targetPdf,c.target); close(r.weightSum,hidden ? c.occluded : c.full);
        assert(surfaceLoads==std::vector<int>({4,3,4,3}));
        assert(reservoirLoads==std::vector<int>({4,3,4,3}));
        assert(rng.calls==3); // One start index, then only the two actual neighbors.
    }

    // No valid selected neighbor retains the center exactly, including its M and weight.
    for (auto& pick : picks) pick=-1;
    clearReads(); RTXDI_RandomSamplerState emptyRng; RAB_LightSample emptyLight{};
    auto empty=RTXDI_DISpatialResampling({}, {0}, center, emptyRng, {}, {}, 0, {}, emptyLight);
    equal(empty,center); assert(surfaceLoads.empty() && reservoirLoads.empty());
    assert(emptyRng.calls==1);

    // Disabled integration must execute the original coordinates, rejection and random stream.
    enabled=false;
    for (bool geometry : {false,true}) for (bool material : {false,true})
        for (bool hidden : {false,true}) for (float random : {0.f,.99f}) {
        geometryAccepted=geometry; materialAccepted=material; hiddenThird=hidden;
        for (uint i=1; i<5; ++i) randomValues[i]=random;
        clearReads(); RTXDI_RandomSamplerState originalRng; RAB_LightSample originalLight{};
        auto original=OriginalSpatialResampling({}, {0}, center, originalRng, {}, {}, 0, {}, originalLight);
        auto originalSurfaces=surfaceLoads, originalReservoirs=reservoirLoads;
        clearReads(); RTXDI_RandomSamplerState adaptedRng; RAB_LightSample adaptedLight{};
        auto adapted=RTXDI_DISpatialResampling({}, {0}, center, adaptedRng, {}, {}, 0, {}, adaptedLight);
        equal(original,adapted); assert(originalLight.id==adaptedLight.id);
        assert(originalRng.calls==adaptedRng.calls && neighborCallbacks==0);
        assert(surfaceLoads==originalSurfaces && reservoirLoads==originalReservoirs);
    }
}
