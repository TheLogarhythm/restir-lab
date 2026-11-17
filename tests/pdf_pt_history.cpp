// Production shader functions are included below; only texture, hit, ray and
// vector operations are CPU stubs. Reservoir addresses use a small linear grid.
#include <algorithm>
#include <array>
#include <cassert>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <functional>
#include <iostream>
#include <limits>
#include <string>
#include "../scripts/run/rtxdi_experiments/PdfSimilarityMath.h"
#include "../scripts/falcor/pdf_pt_direction.h"
#ifdef NDEBUG
#error History regression assertions must be enabled.
#endif

using uint = std::uint32_t;
using float4x4 = std::array<std::array<float,4>,4>;
using std::isfinite;
using std::max;

struct uint2 { uint x, y; };
struct bool2 { bool x, y; };
struct bool4 { bool x, y, z, w; };
bool all(bool2 v) { return v.x && v.y; }
bool all(bool4 v) { return v.x && v.y && v.z && v.w; }
bool any(bool2 v) { return v.x || v.y; }
struct float2 {
    float x, y;
    float2(float x=0, float y=0) : x(x), y(y) {}
    explicit float2(uint2 v) : x(float(v.x)), y(float(v.y)) {}
    float2 operator+(float2 v) const { return {x+v.x,y+v.y}; }
    float2 operator+(float v) const { return {x+v,y+v}; }
    float2 operator*(float2 v) const { return {x*v.x,y*v.y}; }
    bool2 operator<(float v) const { return {x<v,y<v}; }
    bool2 operator>=(float2 v) const { return {x>=v.x,y>=v.y}; }
};
struct int2 {
    int x, y;
    explicit int2(float2 v) : x(int(v.x)), y(int(v.y)) {}
};
struct float3 {
    float x, y, z;
    float3 operator-(float3 v) const { return {x-v.x,y-v.y,z-v.z}; }
};
struct float4 { float x, y, z, w; };
float2 floor(float2 v) { return {std::floor(v.x),std::floor(v.y)}; }
bool2 isfinite(float2 v) { return {isfinite(v.x),isfinite(v.y)}; }
bool4 isfinite(float4 v) { return {isfinite(v.x),isfinite(v.y),isfinite(v.z),isfinite(v.w)}; }
float dot(float3 a, float3 b) { return a.x*b.x+a.y*b.y+a.z*b.z; }
float length(float3 v) { return std::sqrt(dot(v,v)); }
uint asuint(float value) {
    uint bits;
    static_assert(sizeof(bits)==sizeof(value));
    std::memcpy(&bits,&value,sizeof(bits));
    return bits;
}
// Slang's float4 arithmetic is componentwise. Each component executes the same
// production scalar helper, rather than a second implementation of the update.
float4 labPdfSum(float4 current, float4 previous, float retention) {
    return {labPdfSum(current.x,previous.x,retention),labPdfSum(current.y,previous.y,retention),
            labPdfSum(current.z,previous.z,retention),labPdfSum(current.w,previous.w,retention)};
}

struct HitInfo {
    bool valid=true;
    uint type=1, instance=3, primitive=9;
    bool isValid() const { return valid; }
    uint getType() const { return type; }
    struct InstanceID { uint index; };
    InstanceID getInstanceID() const { return {instance}; }
    uint getPrimitiveIndex() const { return primitive; }
};
struct ShadingData {
    uint materialID=2;
    bool frontFacing=true;
    float3 faceN={0,0,1}, posW={0,0,10};
};
struct PathReservoir {
    float4 labMoment={1,2,0,4};
    float labCount=1;
    uint labCamera=0;
    float M=7, weight=11; // Lighting fields must remain unchanged.
};
struct Params {
    uint frameCount=5;
    uint2 frameDim={4,4};
    uint getReservoirOffset(int2 pixel) const { return uint(pixel.y)*frameDim.x+uint(pixel.x); }
} params;
struct Scene {
    struct Camera {
        struct Data {
            float3 posW={0,0,0};
            float4x4 viewProjMatNoJitter={};
            float4x4 prevViewProjMatNoJitter={};
        } data;
    } camera;
} gScene;
HitInfo currentHit, previousHit;
ShadingData currentShading, previousShading;
float2 motion;
int motionReads=0, priorReads=0, shadingReads=0;
uint lastPrior=0;
int2 lastPrevious(float2(0,0));
struct MotionBuffer {
    float2 operator[](uint2) const { ++motionReads; return motion; }
} motionVectors;
struct HitBuffer { HitInfo operator[](uint2) const { return currentHit; } } vbuffer;
int temporalVbuffer=0;
struct ReservoirBuffer {
    std::array<PathReservoir,64> values;
    PathReservoir operator[](uint index) const {
        ++priorReads;
        lastPrior=index;
        assert(index<values.size());
        return values[index];
    }
} prevReservoirs;
struct Ray { float3 origin, dir; };
Ray computeRayPredefinedThinLens(uint2, uint2, uint) { return {{0,0,0},{0,0,1}}; }
ShadingData loadShadingData(HitInfo, float3, float3, bool) { ++shadingReads; return currentShading; }
ShadingData getPixelTemporalShadingData(const Params&, int, int2 pixel, HitInfo& hit) {
    lastPrevious=pixel;
    hit=previousHit;
    return previousShading;
}
float kLabPdfDecay=.5f, kLabPdfHistoryLimit=20.f;
#include "pdf_pt_history_under_test.inl"

const uint2 pixel={1,1};
PathReservoir sample;

void reset() {
    params=Params{};
    gScene=Scene{};
    for (int i=0;i<4;++i) {
        gScene.camera.data.viewProjMatNoJitter[i][i]=1.f;
        gScene.camera.data.prevViewProjMatNoJitter[i][i]=1.f;
    }
    currentHit=HitInfo{};
    previousHit=HitInfo{};
    currentShading=ShadingData{};
    previousShading=ShadingData{};
    motion={0,0};
    motionReads=priorReads=shadingReads=0;
    kLabPdfDecay=.5f;
    kLabPdfHistoryLimit=20.f;
    sample=PathReservoir{};
    sample.labCamera=restirpt.labCameraStamp(params.frameDim);
    PathReservoir prior;
    prior.labMoment={2,0,4,8};
    prior.labCount=6;
    prior.labCamera=sample.labCamera;
    prevReservoirs.values.fill(prior);
}
bool same(float4 a, float4 b) { return a.x==b.x && a.y==b.y && a.z==b.z && a.w==b.w; }
void unchanged(PathReservoir before) {
    assert(same(sample.labMoment,before.labMoment));
    assert(sample.labCount==before.labCount && sample.labCamera==before.labCamera);
    assert(sample.M==before.M && sample.weight==before.weight);
}
void check(float4 moment, float count, float3 mean) {
    assert(same(sample.labMoment,moment) && sample.labCount==count);
    assert(sample.labMoment.x/sample.labMoment.w==mean.x);
    assert(sample.labMoment.y/sample.labMoment.w==mean.y);
    assert(sample.labMoment.z/sample.labMoment.w==mean.z);
    assert(sample.M==7 && sample.weight==11);
    assert(sample.labCamera==restirpt.labCameraStamp(params.frameDim));
}
void printStatistics(const char* label) {
    const float4 m=sample.labMoment;
    std::cout << label << ": A=(" << m.x << ',' << m.y << ',' << m.z
        << "), B=" << m.w << ", count=" << sample.labCount << ", A/B=("
        << m.x/m.w << ',' << m.y/m.w << ',' << m.z/m.w << ")\n";
}
void updates() {
    reset();
    labCombineHistory(pixel,sample);
    check({2,2,2,8},4,{.25f,.25f,.25f});
    assert(lastPrior==5 && lastPrevious.x==1 && lastPrevious.y==1);
    assert(same(prevReservoirs.values[5].labMoment,{2,0,4,8}));
    printStatistics("half");

    reset(); kLabPdfDecay=.95f;
    labCombineHistory(pixel,sample);
    check({2.9f,2.f,3.8f,11.6f},6.7f,{2.9f/11.6f,2.f/11.6f,3.8f/11.6f});
    printStatistics("default");

    reset(); sample.labMoment={0,0,0,0}; sample.labCount=0;
    labCombineHistory(pixel,sample);
    check({1,0,2,4},3,{.25f,0.f,.5f});
    printStatistics("empty");

    reset(); kLabPdfHistoryLimit=3.f;
    labCombineHistory(pixel,sample);
    check({2,2,2,8},3,{.25f,.25f,.25f}); // Count cap must not rescale A or B.

    reset(); motion={.25f,-.25f};
    prevReservoirs.values[5].labCount=0; // Wrong source address cannot pass.
    labCombineHistory(pixel,sample);
    check({2,2,2,8},4,{.25f,.25f,.25f});
    assert(lastPrior==2 && lastPrevious.x==2 && lastPrevious.y==0);
    std::cout << "updates=5\n";
}
// Production compares the source frame to the camera that generated it.
// A current-camera comparison incorrectly drops every moving-frame update.
void continuousCamera() {
    reset();
    const uint originalStamp=sample.labCamera;
    gScene.camera.data.viewProjMatNoJitter[0][3]=.125f;
    gScene.camera.data.posW.x=.125f;
    sample.labCamera=restirpt.labCameraStamp(params.frameDim);
    assert(sample.labCamera!=originalStamp);
    motion={.25f,-.25f};
    prevReservoirs.values[5].labCount=0;
    labCombineHistory(pixel,sample);
    check({2,2,2,8},4,{.25f,.25f,.25f});
    assert(lastPrior==2 && lastPrevious.x==2 && lastPrevious.y==0);
    printStatistics("moving");

    // Use the moving frame as the source of the next frame. Camera projection
    // may evolve continuously too; validity is based on its previous matrix.
    prevReservoirs.values.fill(sample);
    gScene.camera.data.prevViewProjMatNoJitter=gScene.camera.data.viewProjMatNoJitter;
    gScene.camera.data.viewProjMatNoJitter[0][3]=.25f;
    gScene.camera.data.viewProjMatNoJitter[1][1]=1.01f;
    gScene.camera.data.posW.x=.25f;
    sample=PathReservoir{};
    sample.labCamera=restirpt.labCameraStamp(params.frameDim);
    labCombineHistory(pixel,sample);
    check({2,3,1,8},3,{.25f,.375f,.125f});
    printStatistics("moving_again");

    // Stopping at the last pose preserves the accumulated direction evidence.
    prevReservoirs.values.fill(sample);
    gScene.camera.data.prevViewProjMatNoJitter=gScene.camera.data.viewProjMatNoJitter;
    motion={0,0};
    sample=PathReservoir{};
    sample.labCamera=restirpt.labCameraStamp(params.frameDim);
    labCombineHistory(pixel,sample);
    check({2,3.5f,.5f,8},2.5f,{.25f,.4375f,.0625f});
    printStatistics("stopped");
    std::cout << "continuous_updates=3\n";
}
int rejected=0;
void rejects(const char* name, const std::function<void()>& edit) {
    reset(); edit();
    PathReservoir before=sample;
    labCombineHistory(pixel,sample);
    unchanged(before);
    ++rejected;
    std::cout << name << "\n";
}
void rejections() {
    const float nan=std::numeric_limits<float>::quiet_NaN();
    const float inf=std::numeric_limits<float>::infinity();
    rejects("initial_frame",[]{params.frameCount=0;});
    assert(motionReads==0 && priorReads==0);
    rejects("history_disabled",[]{kLabPdfDecay=0;});
    assert(motionReads==0 && priorReads==0);
    rejects("invalid_current_hit",[]{currentHit.valid=false;});
    rejects("invalid_previous_hit",[]{previousHit.valid=false;});
    rejects("different_hit_type",[]{previousHit.type=2;});
    rejects("different_instance",[]{previousHit.instance=4;});
    rejects("different_primitive",[]{previousHit.primitive=10;});
    rejects("different_material",[]{previousShading.materialID=3;});
    rejects("different_front_face",[]{previousShading.frontFacing=false;});
    rejects("normal_disagreement",[]{previousShading.faceN={.6f,0,.8f};});
    rejects("wrong_depth",[]{previousShading.posW.z=10.2f;});
    rejects("near_camera_wrong_depth",[]{
        currentShading.posW={0,0,0}; previousShading.posW={0,0,.00002f};
    });
    rejects("previous_camera_stamp_mismatch",[]{
        // Prior matches current, but not the camera that should have produced it.
        gScene.camera.data.prevViewProjMatNoJitter[0][3]=1.f;
    });
    rejects("previous_projection_stamp_mismatch",[]{
        gScene.camera.data.prevViewProjMatNoJitter[1][1]=1.01f;
    });
    rejects("explicit_cut_reset",[]{
        gScene.camera.data.viewProjMatNoJitter[0][3]=10.f;
        sample.labCamera=restirpt.labCameraStamp(params.frameDim);
        params.frameCount=0;
    });
    assert(motionReads==0 && priorReads==0);
    rejects("resolution_stamp_changed",[]{
        params.frameDim={8,4}; uint old=sample.labCamera;
        sample.labCamera=restirpt.labCameraStamp(params.frameDim); assert(sample.labCamera!=old);
    });
    rejects("negative_reprojection",[]{motion.x=-1.f;}); assert(priorReads==0);
    rejects("outside_reprojection",[]{motion.y=1.f;}); assert(priorReads==0);
    rejects("nan_reprojection",[&]{motion.x=nan;}); assert(priorReads==0);
    rejects("infinite_reprojection",[&]{motion.y=inf;}); assert(priorReads==0);
    rejects("empty_history_count",[]{prevReservoirs.values[5].labCount=0;});
    rejects("negative_history_count",[]{prevReservoirs.values[5].labCount=-1;});
    rejects("nan_history_count",[&]{prevReservoirs.values[5].labCount=nan;});
    rejects("infinite_history_count",[&]{prevReservoirs.values[5].labCount=inf;});
    rejects("empty_history_energy",[]{prevReservoirs.values[5].labMoment.w=0;});
    rejects("negative_history_energy",[]{prevReservoirs.values[5].labMoment.w=-1;});
    rejects("nan_history_moment",[&]{prevReservoirs.values[5].labMoment.x=nan;});
    rejects("infinite_history_energy",[&]{prevReservoirs.values[5].labMoment.w=inf;});
    rejects("nonfinite_total",[]{
        const float largest=std::numeric_limits<float>::max();
        sample.labMoment={largest,0,0,largest};
        prevReservoirs.values[5].labMoment=sample.labMoment;
        kLabPdfDecay=1.f;
    });
    std::cout << "rejections=" << rejected << "\n";
}
int main(int argc, char** argv) {
    assert(argc==2);
    if (std::string(argv[1])=="continuous_camera") continuousCamera();
    else if (std::string(argv[1])=="updates") updates();
    else if (std::string(argv[1])=="rejections") rejections();
    else return 2;
}
