// Extracted production callbacks; only scene/light lookups are deterministic stubs.
#include <cmath>
#include <cstdio>
#include <initializer_list>
using uint=unsigned;
struct float2 { float x,y; float2(float a=0):x(a),y(a){} float2(float a,float b):x(a),y(b){} };
struct float3 { float x,y,z; float3(float a=0):x(a),y(a),z(a){} };
struct Props { bool delta=false; bool IsDelta() const { return delta; } };
struct RTXDI_BrdfRaySample { float outPdf; Props properties; };
struct RAB_RayPayload { uint instanceID=0,geometryIndex=0,primitiveIndex=0; float2 barycentrics={.2f,.3f}; };
struct RAB_Surface {};
struct RAB_LightInfo {};
struct RAB_LightSample { int lightType=0; bool analytic=false; };
struct RTXDI_DIInitialSamplingParameters { uint numLocalLightSamples=2,numEnvironmentSamples=1; int localLightSamplingMode=0; };
struct Constants {
    struct Pt { int lightSamplingMode=2; struct Nee { RTXDI_DIInitialSamplingParameters initialSamplingParams; } nee; } pt;
    struct Lights { struct Region { uint numLights=1; } localLightBufferRegion;
                    struct Env { int lightIndex=0; } environmentLightParams; } lightBufferParams;
} g_Const;
constexpr int PT_INITIAL_SAMPLING_LIGHT_SAMPLING_MODE_MIS=2;
constexpr int ReSTIRDI_LocalLightSamplingMode_UNIFORM=0;
constexpr uint RTXDI_InvalidLightIndex=~0u;
namespace PolymorphicLightType { constexpr int kEnvironment=1; }
float scenePdf=1;
uint sceneLightIndex=0;
bool RAB_IsAnalyticLightSample(RAB_LightSample s) { return s.analytic; }
float RAB_EvaluateEnvironmentMapSamplingPdf(float3) { return 1; }
float RAB_EvaluateLocalLightSourcePdf(uint) { return 1; }
uint GetLightIndex(uint,uint,uint) { return sceneLightIndex; }
RAB_LightInfo RAB_LoadLightInfo(uint,bool) { return {}; }
RAB_LightSample RAB_SamplePolymorphicLight(RAB_LightInfo,RAB_Surface,float2) { return {}; }
float RAB_LightSampleSolidAnglePdf(RAB_LightSample) { return scenePdf; }
float2 RAB_GetEnvironmentMapRandXYFromDir(float3) { return {}; }
#include "mis_under_test.h"
bool require(bool ok,const char* text) { if(!ok) std::fprintf(stderr,"%s\n",text); return ok; }
int main() {
    bool ok=true;
    for(uint count : {1u,2u}) {
        g_Const.pt.nee.initialSamplingParams.numLocalLightSamples=count;
        g_Const.pt.nee.initialSamplingParams.numEnvironmentSamples=count;
        for(bool env : {false,true}) {
            scenePdf=.8f/count;
            float donor=env?GetMISWeightForEnvironmentMap({}, {}, {.2f,{}}):GetMISWeightForEmissiveSurface({}, {}, {.2f,{}});
            scenePdf=.6f/count;
            RAB_LightSample sample; sample.lightType=env?1:0;
            float shiftedNee=RAB_GetMISWeightForNEE(0,sample,{},scenePdf,.4f);
            ok=require(std::abs(donor+shiftedNee-1)<1e-6,"Cached BSDF and shifted NEE endpoint weights do not partition unity")&&ok;
            float delta=env?GetMISWeightForEnvironmentMap({}, {}, {.2f,{true}}):GetMISWeightForEmissiveSurface({}, {}, {.2f,{true}});
            ok=require(delta==1,"Delta endpoint must retain full weight")&&ok;
        }
    }
    sceneLightIndex=RTXDI_InvalidLightIndex;
    ok=require(GetMISWeightForEmissiveSurface({}, {}, {.2f,{}})==1,"Unindexed emission loses energy")&&ok;
    RAB_LightSample analytic; analytic.analytic=true;
    ok=require(RAB_GetMISWeightForNEE(0,analytic,{},.6f,.4f)==1,"Analytic NEE loses energy")&&ok;
    g_Const.pt.nee.initialSamplingParams.numEnvironmentSamples=0;
    ok=require(GetMISWeightForEnvironmentMap({}, {}, {.2f,{}})==1,"No-NEE environment must have BSDF weight1")&&ok;
    return ok?0:1;
}
