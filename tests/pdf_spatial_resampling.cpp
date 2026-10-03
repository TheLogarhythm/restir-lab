// Execute the actual adapted RTXDI spatial function with one deterministic neighbor.
#include <cmath>
#include <cassert>
#include <algorithm>
using uint = unsigned;
using std::min; using std::max;
uint min(uint a, int b) { return std::min(a, uint(b)); }
struct int2;
struct float2 { float x, y; float2(float a, float b): x(a), y(b) {} };
float2 operator*(float2 a, float b) { return {a.x*b, a.y*b}; }
struct uint2 { uint x, y; uint2(uint a=0, uint b=0): x(a), y(b) {} uint2(int2); };
struct int2 {
    int x, y; int2(int a=0, int b=0): x(a), y(b) {}
    int2(uint2 v): x(v.x), y(v.y) {} int2(float2 v): x(v.x), y(v.y) {}
    int2& operator+=(int2 v) { x+=v.x; y+=v.y; return *this; }
};
uint2::uint2(int2 v): x(v.x), y(v.y) {}
int2 operator+(int2 a, int2 b) { return {a.x+b.x, a.y+b.y}; }
struct RTXDI_DIReservoir {
    uint lightData=0, uvData=0; float weightSum=0, targetPdf=0, M=0;
    uint packedVisibility=0; int2 spatialDistance; uint age=0;
};
struct RAB_Surface { int id; };
struct RAB_LightInfo { uint id; };
struct RAB_LightSample { uint id; };
struct RTXDI_RandomSamplerState { int calls=0; };
struct RTXDI_RuntimeParameters { uint neighborOffsetMask=0, activeCheckerboardField=0; };
struct RTXDI_ReservoirBufferParameters {};
struct RTXDI_DISpatialResamplingParameters {
    int biasCorrectionMode=2; uint numSamples=1, numDisocclusionBoostSamples=0;
    float targetHistoryLength=0, samplingRadius=1, normalThreshold=0, depthThreshold=0;
    bool enableMaterialSimilarityTest=false, discountNaiveSamples=false;
};
#define RTXDI_DEFAULT(value) = value
#define RTXDI_BIAS_CORRECTION_BASIC 1
#define RTXDI_BIAS_CORRECTION_RAY_TRACED 2
#define RTXDI_BIAS_CORRECTION_PAIRWISE 3
#define RTXDI_ALLOWED_BIAS_CORRECTION 2
#define RTXDI_NAIVE_SAMPLING_M_THRESHOLD 1
struct Offset { float2 xy; } RTXDI_NEIGHBOR_OFFSETS_BUFFER[] = {{{1, 0}}};
RTXDI_DIReservoir neighbor;
float similarity, choice;
bool enabled, visible;
int scaleCalls;
RTXDI_DIReservoir RTXDI_EmptyDIReservoir() { return {}; }
bool RTXDI_IsValidDIReservoir(RTXDI_DIReservoir r) { return r.lightData != 0; }
uint RTXDI_GetDIReservoirLightIndex(RTXDI_DIReservoir r) { return r.lightData; }
float2 RTXDI_GetDIReservoirSampleUV(RTXDI_DIReservoir) { return {0, 0}; }
RAB_LightInfo RAB_EmptyLightInfo() { return {0}; }
RAB_LightSample RAB_EmptyLightSample() { return {0}; }
RAB_LightInfo RAB_LoadLightInfo(uint id, bool) { return {id}; }
RAB_LightSample RAB_SamplePolymorphicLight(RAB_LightInfo light, RAB_Surface, float2) { return {light.id}; }
float RAB_GetLightSampleTargetPdfForSurface(RAB_LightSample sample, RAB_Surface surface) {
    // At center: light 1 -> 2, light 2 -> 3. At neighbor: light 1 -> 4, light 2 -> 5.
    return float(sample.id + 1 + 2*surface.id);
}
float RTXDI_GetNextRandom(RTXDI_RandomSamplerState& rng) { return rng.calls++ == 0 ? 0.f : choice; }
int2 RAB_ClampSamplePositionIntoView(int2 p, bool) { return p; }
void RTXDI_ActivateCheckerboardPixel(int2&, bool, uint) {}
RAB_Surface RAB_GetGBufferSurface(int2 p, bool) { return {p.x}; }
bool RAB_IsSurfaceValid(RAB_Surface) { return true; }
float RAB_GetSurfaceNormal(RAB_Surface) { return 0; }
float RAB_GetSurfaceLinearDepth(RAB_Surface) { return 0; }
bool RTXDI_IsValidNeighbor(float, float, float, float, float, float) { return true; }
int RAB_GetMaterial(RAB_Surface) { return 0; }
bool RAB_AreMaterialsSimilar(int, int) { return true; }
uint2 RTXDI_PixelPosToReservoirPos(int2 p, uint) { return uint2(p); }
RTXDI_DIReservoir RTXDI_LoadDIReservoir(RTXDI_ReservoirBufferParameters, uint2, uint) { return neighbor; }
bool RAB_GetConservativeVisibility(RAB_Surface, RAB_LightSample) { return visible; }
bool LabPdfEnabled() { return enabled; }
float LabSpatialWeight(uint2, uint2, RAB_Surface, RAB_Surface) { ++scaleCalls; return enabled ? similarity : 1.f; }
RTXDI_DIReservoir RTXDI_DISpatialResamplingWithPairwiseMIS(uint2, RAB_Surface, RTXDI_DIReservoir,
    RTXDI_RandomSamplerState&, RTXDI_RuntimeParameters, RTXDI_ReservoirBufferParameters,
    uint, RTXDI_DISpatialResamplingParameters, RAB_LightSample&) { assert(false); return {}; }
#include "spatial_under_test.h"

int main() {
    RTXDI_DIReservoir center;
    center.lightData=1; center.targetPdf=2; center.M=1; center.weightSum=1.5f;
    neighbor.lightData=2; neighbor.targetPdf=5; neighbor.M=4; neighbor.weightSum=.5f;
    for (bool on : {false, true}) for (float h : {0.f, .125f, .375f, 1.f})
        for (float random : {0.f, .95f}) for (bool seen : {false, true}) {
        enabled=on; similarity=h; choice=random; visible=seen; scaleCalls=0;
        RTXDI_RandomSamplerState rng;
        RAB_LightSample selected{};
        auto r = RTXDI_DISpatialResampling({}, {0}, center, rng, {}, {}, 0, {}, selected);
        float m = 4*(on ? h : 1);
        float sum = 3 + 1.5f*m;
        bool picked = random*sum < 1.5f*m;
        float target = picked ? 3.f : 2.f;
        float atNeighbor = seen ? (picked ? 5.f : 4.f) : 0.f;
        float pi = picked ? atNeighbor : target;
        float expected = sum*pi/(target*(target + atNeighbor*m));
        assert(r.lightData == (picked ? 2u : 1u));
        assert(std::abs(r.M-(1+m)) < 1e-6f);
        assert(std::abs(r.targetPdf-target) < 1e-6f);
        assert(std::abs(r.weightSum-expected) < 1e-6f);
        assert(scaleCalls == 2); // Selection and normalization both visited the neighbor.
    }
}
