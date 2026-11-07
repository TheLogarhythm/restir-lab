#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cassert>
using std::pow;
using std::sqrt;
using std::abs;
constexpr float M_PI = 3.14159265358979323846f;
constexpr float kMinRoughness = .03f;
float max(float a,float b) { return std::max(a,b); }
float saturate(float a) { return std::clamp(a,0.f,1.f); }
float square(float a) { return a*a; }
float lerp(float a,float b,float t) { return a+(b-a)*t; }
struct float2 { float x,y; float2(float a=0):x(a),y(a){} float2(float a,float b):x(a),y(b){} };
struct float3 { float x,y,z; float3(float a=0):x(a),y(a),z(a){} float3(float a,float b,float c):x(a),y(b),z(c){} };
float3 operator+(float3 a,float3 b) { return {a.x+b.x,a.y+b.y,a.z+b.z}; }
float3 operator-(float3 a,float3 b) { return {a.x-b.x,a.y-b.y,a.z-b.z}; }
float3 operator-(float3 a) { return {-a.x,-a.y,-a.z}; }
float3 operator*(float3 a,float3 b) { return {a.x*b.x,a.y*b.y,a.z*b.z}; }
float3 operator*(float a,float3 b) { return {a*b.x,a*b.y,a*b.z}; }
float3 operator*(float3 b,float a) { return a*b; }
float3 operator/(float3 b,float a) { return (1.f/a)*b; }
float3& operator*=(float3& a,float3 b) { a=a*b; return a; }
float3& operator+=(float3& a,float3 b) { a=a+b; return a; }
float3& operator/=(float3& a,float b) { a=a/b; return a; }
struct bool3 { bool x,y,z; };
bool3 operator>(float3 a,float b) { return {a.x>b,a.y>b,a.z>b}; }
bool3 operator!=(float3 a,float b) { return {a.x!=b,a.y!=b,a.z!=b}; }
bool any(bool3 a) { return a.x||a.y||a.z; }
float dot(float3 a,float3 b) { return a.x*b.x+a.y*b.y+a.z*b.z; }
float3 normalize(float3 a) { return a/sqrt(dot(a,a)); }
float length(float3 a) { return sqrt(dot(a,a)); }
float3 cross(float3 a,float3 b) { return {a.y*b.z-a.z*b.y,a.z*b.x-a.x*b.z,a.x*b.y-a.y*b.x}; }
float3 reflect(float3 a,float3 n) { return a-2*dot(a,n)*n; }
struct Material { float roughness; float3 specularF0,diffuseAlbedo; };
struct RAB_Surface { float3 normal,geoNormal,viewDir; Material material; float diffuseProbability; float3 worldPos; };
struct RTXDI_BrdfRaySampleProperties { bool delta; bool IsDelta() const { return delta; } void SetContinuous() { delta=false; } };
RTXDI_BrdfRaySampleProperties RTXDI_DefaultBrdfRaySampleProperties() { return {false}; }
struct RAB_RayPayload { float3 throughput; bool hit=false,front=true; float3 emission=0; };
struct FixtureState { RAB_RayPayload traceResult; float3 pathThroughput,rcPathThroughput; int bounceDepth,rcVertexLength; };
struct RTXDI_PTHybridShiftPerFrameParameters {};
struct RTXDI_PTReservoir { float3 translatedWorldPosition,radiance,worldNormal; int rcVertexLength,pathLength; float rcWiPdf; };
constexpr int RTXDI_RESTIRPT_RECONNECTION_MODE_FIXED_THRESHOLD=0, RTXDI_RESTIRPT_RECONNECTION_MODE_FOOTPRINT=1;
struct RTXDI_HybridShiftPathTracerContext {};
template<typename T> struct RTXDI_PathTracerContext {
    int GetReconnectionMode() const { return 1; }
    float GetDistanceThreshold() const { return 1; }
    float GetRoughnessThreshold() const { return .1f; }
    float GetFootprintThreshold() const { return 1; }
    float GetCheckPreRcInverseGeoTerm() const { return 0; }
    float GetPdfThreshold() const { return 1000; }
};
float3 RAB_GetSurfaceWorldPos(RAB_Surface s) { return s.worldPos; }
float3 RAB_GetSurfaceNormal(RAB_Surface s) { return s.normal; }
float RAB_GetSurfaceRoughness(RAB_Surface s) { return s.material.roughness; }
bool isinf(float x) { return std::isinf(x); }
float3 fixtureBsdf,fixtureVisibility;
const int SceneBVH=0;
float3 RAB_GetPTSampleTargetPdfForSurface(float3,float3 radiance,RAB_Surface) { return fixtureBsdf*radiance; }
float3 GetFinalVisibility(int,RAB_Surface,float3) { return fixtureVisibility; }
struct { struct { bool enableEnvironmentMap=true; } sceneConstants;
         struct { struct { bool enableFinalVisibility=true,enableFinalMIS=true; } finalShadingParams; } restirGI; } g_Const;
struct RayDesc {};
RayDesc setupContinuationRay(float3,float3,float3) { return {}; }
RAB_RayPayload endpoint; int endpointQueries=0;
RAB_RayPayload TraceNextBounce(RayDesc) { ++endpointQueries; return endpoint; }
bool RAB_IsValidHit(RAB_RayPayload p) { return p.hit; }
bool RAB_RayPayloadIsFrontFace(RAB_RayPayload p) { return p.front; }
float3 RAB_RayPayloadGetEmittedRadiance(RAB_RayPayload p) { return p.emission; }
float3 RAB_GetEnvironmentRadiance(float3) { return {2,3,4}; }
constexpr float kMISRoughness=.5f;
struct RTXDI_GIReservoir { float3 position,radiance; float weightSum; int M; };
RTXDI_GIReservoir initialGi;
RTXDI_GIReservoir LoadInitialSampleReservoir(int,RAB_Surface) { return initialGi; }
struct SplitBrdf { float3 demodulatedDiffuse,specular; };
SplitBrdf EvaluateBrdf(RAB_Surface,float3 p) { assert(std::isfinite(p.x)); return {1,2}; }
float GetMISWeight(SplitBrdf,SplitBrdf,float3) { return .25f; }
float3 DemodulateSpecular(float3,float3 value) { return value; }
void LabObserveFinite(float3 v) { assert(std::isfinite(v.x)&&std::isfinite(v.y)&&std::isfinite(v.z)); }
#include "transport_under_test.h"
bool close(float a,float b) { return std::abs(a-b)<2e-6f; }
bool require(bool condition,const char* why) { if(!condition) std::fprintf(stderr,"%s\n",why); return condition; }
bool same(float3 a,float3 b) { return close(a.x,b.x)&&close(a.y,b.y)&&close(a.z,b.z); }
int main() {
    bool ok=true;
    {
        RAB_Surface s={{0,0,1},{0,0,1},{0,0,1},{0,{.2f,.3f,.4f},.5f},.7f};
        endpoint={{.5f,.25f,1},true,true,{4,8,2}};
        auto value=LabSecondaryDeltaEndpoint(s);
        ok=require(same(value,{.4f,.6f,.8f})&&endpointQueries==1,"Terminal mirror must trace one endpoint and apply F and RGB visibility once")&&ok;
        endpoint.front=false;
        ok=require(same(LabSecondaryDeltaEndpoint(s),0),"Back-facing terminal emission must be excluded")&&ok;
        endpoint.hit=false;
        ok=require(same(LabSecondaryDeltaEndpoint(s),{.2f,.225f,1.6f}),"Terminal mirror environment throughput differs")&&ok;
        s.material.roughness=.1f; endpointQueries=0;
        ok=require(same(LabSecondaryDeltaEndpoint(s),0)&&endpointQueries==0,"Terminal delta query must not add a glossy bounce")&&ok;
        RTXDI_GIReservoir positive={1,3,2,1},null={float3{NAN},0,0,1};
        fixtureVisibility={.5f};
        float3 diffuse=0,specular=0;
        initialGi=null; FinalGiFixture(s,positive,diffuse,specular);
        ok=require(same(diffuse,2.25f)&&same(specular,4.5f),"Null initial GI sample must not change the resampled MIS weight")&&ok;
        diffuse=0; specular=0; initialGi=positive; FinalGiFixture(s,null,diffuse,specular);
        ok=require(same(diffuse,1.5f)&&same(specular,3.f),"Null final GI reservoir must not discard the initial MIS term")&&ok;
        diffuse=0; specular=0; initialGi=null; FinalGiFixture(s,null,diffuse,specular);
        ok=require(same(diffuse,0)&&same(specular,0),"All-null final GI must remain finite zero")&&ok;
    }
    // Actual production VNDF samples against an analytic constant-radiance
    // hemisphere integral. Includes rejected below-horizon attempts as zeros.
    // At V=N, alpha=1, F=1: integral of GGX is 1-ln(2).
    for(float q : {0.f,.25f,.75f,1.f}) {
        RAB_Surface s={{0,0,1},{0,0,1},{0,0,1},{1,1,.2f},q};
        double estimate=0;
        const int count=65536;
        for(int i=0;i<count;++i) {
            float u=(i+.5f)/count;
            float3 h=normalize(ImportanceSampleGGX_VNDF({u,.371f},1,s.viewDir,1));
            float3 glossy=reflect(-s.viewDir,h);
            float3 diffuse={sqrt(u),0,sqrt(1-u)};
            for(int lobe=0;lobe<2;++lobe) {
                auto L=lobe?diffuse:glossy;
                float probability=lobe?q:1-q;
                if(probability==0 || L.z<=0) continue;
                float pdf=RAB_SurfaceEvaluateBsdfPdf(s,L,{false});
                estimate+=probability*RAB_SurfaceEvaluateBsdfTimesNoL(s,L,false).x/pdf/count;
            }
        }
        ok=require(std::abs(estimate-(.2+1-std::log(2.)))<3e-5,
                   "Glossy/mixed sampling disagrees with analytic unit-radiance integral")&&ok;
    }
    for(float diffuseProbability : {0.f,.2f,.5f,.9f}) {
        RAB_Surface s={{0,0,1},{0,0,1},{0,0,1},{0,{.04f,.1f,.2f},{.3f,.4f,.5f}},diffuseProbability};
        auto numerator=RAB_SurfaceEvaluateBsdfTimesNoL(s,{0,0,1},true);
        auto discrete=RAB_SurfaceEvaluateBsdfPdf(s,{0,0,1},{true});
        ok=require(close(discrete,1-diffuseProbability),"Delta PDF must be a probability mass")&&ok;
        ok=require(close(numerator.x/discrete*(1-diffuseProbability),.04f),"Mixed delta expectation must equal F, not F divided twice")&&ok;
        auto continuous=RAB_SurfaceEvaluateBsdfPdf(s,{0,0,1},{false});
        ok=require(close(continuous,diffuseProbability/M_PI),"Continuous PDF must exclude delta mass")&&ok;
        auto diffuse=RAB_SurfaceEvaluateBsdfTimesNoL(s,{0,0,1},false);
        ok=require(close(diffuse.x,.3f/M_PI),"Diffuse contribution disappeared below mirror roughness")&&ok;
        ok=require(RAB_SurfaceEvaluateBsdfTimesNoL(s,{0,0,-1},true).x==0,"Below-geometry delta must be rejected")&&ok;
        ok=require(close(GiSpecularProbability(s),1-diffuseProbability),"GI mixture probability must be fixed by surface/view")&&ok;
        if(diffuseProbability>0) {
            RTXDI_PTReservoir r={}; r.translatedWorldPosition={0,0,1}; r.worldNormal={0,0,-1};
            r.rcVertexLength=r.pathLength=2;
            float jacobian=1;
            ValidateInvertibilityCondition({},r,s,jacobian);
            ok=require(jacobian==1,"Identity continuous shift rejected by mismatched low-roughness PDF")&&ok;
        }
    }
    for(float2 b : {float2{0,0},float2{1,0},float2{0,1},float2{.2f,.7f},float2{.6f,.1f}}) {
        float3 recovered=SampleTriangle(LabTriangleRandomFromBarycentrics(b));
        ok=require(close(recovered.y,b.x)&&close(recovered.z,b.y),"MIS resampled another triangle point")&&ok;
        // Triangle (0,0,2),(10,0,2),(0,10,2), area50; viewer at origin.
        float r2=100*b.x*b.x+100*b.y*b.y+4;
        float pdf=r2*sqrt(r2)/100;
        float actualR2=100*recovered.y*recovered.y+100*recovered.z*recovered.z+4;
        float actualPdf=actualR2*sqrt(actualR2)/100;
        float scatter=.2f, nee=2*pdf;
        float sum=nee/(nee+scatter)+scatter/(2*actualPdf+scatter);
        ok=require(close(sum,1),"NEE and actual-hit MIS weights must partition unity")&&ok;
    }
    const float3 B1={2,3,4},B2={.2f,.4f,.6f},T1={.5f,.25f,.125f},T2={.1f,.5f,1},Le={10,20,30};
    InitialSamplingPathTracerContext initial;
    initial.ptState={}; initial.ptState.pathThroughput=B1; initial.ptState.rcPathThroughput=1;
    initial.ptState.bounceDepth=2; initial.ptState.rcVertexLength=2;
    initial.SetTraceResult({T1});
    ok=require(same(initial.ptState.rcPathThroughput,1),"Donor connection leaked into suffix")&&ok;
    initial.ptState.pathThroughput*=B2; initial.ptState.rcPathThroughput*=B2;
    initial.ptState.bounceDepth=3; initial.SetTraceResult({T2});
    ok=require(same(initial.ptState.pathThroughput*Le,{.2f,3,9}),"Initial colored contribution incorrect")&&ok;
    ok=require(same(initial.ptState.rcPathThroughput*Le,{.2f,4,18}),"Cached suffix lost downstream attenuation")&&ok;
    RAB_Surface surface={}; RTXDI_PTReservoir reservoir={{},initial.ptState.rcPathThroughput*Le};
    fixtureBsdf=B1; fixtureVisibility={.8f,.2f,.4f}; float3 target=1;
    SpatialResamplingEvaluateReconnection({},target,surface,reservoir);
    ok=require(same(target,{.32f,2.4f,28.8f}),"Spatial new connection uses donor attenuation or attenuates twice")&&ok;
    target=1; fixtureVisibility=T1;
    TemporalResamplingEvaluateReconnection({},target,surface,reservoir,true);
    ok=require(same(target,{.2f,3,9}),"Inverse temporal target must recover donor contribution")&&ok;
    HybridShiftPathTracerContext replay; replay.ptState={}; replay.ptState.pathThroughput=B1;
    replay.ptState.rcVertexLength=4; replay.ptState.bounceDepth=2; replay.SetTraceResult({T1});
    replay.ptState.pathThroughput*=B2; replay.ptState.bounceDepth=3; replay.SetTraceResult({T2});
    ok=require(same(replay.ptState.pathThroughput*Le,{.2f,3,9}),"Full random replay lost colored visibility")&&ok;
    for(float3 visibility : {float3{1},float3{0},float3{0,.5f,1}}) {
        fixtureVisibility=visibility; target=1;
        SpatialResamplingEvaluateReconnection({},target,surface,reservoir);
        ok=require(same(target,B1*reservoir.radiance*visibility),"Zero-channel reconnection must stay finite without donor division")&&ok;
    }
    return ok?0:1;
}
