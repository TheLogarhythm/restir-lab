#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>
float max(float a, float b) { return std::max(a,b); }
using std::pow;
using std::sqrt;
using uint = unsigned int;
constexpr float M_PI = 3.14159265358979323846f;
constexpr float kMinRoughness = 0.03f;
struct float2 { float x, y; };
struct bool3 { bool x, y, z; };
struct float3 { float x, y, z; float3(float a=0.f):x(a),y(a),z(a){} float3(float a,float b,float c):x(a),y(b),z(c){} };
float3 operator+(float3 a, float3 b) { return {a.x+b.x,a.y+b.y,a.z+b.z}; }
float3 operator-(float3 a, float3 b) { return {a.x-b.x,a.y-b.y,a.z-b.z}; }
float3 operator-(float3 a) { return {-a.x,-a.y,-a.z}; }
float3 operator-(float a, float3 b) { return {a-b.x,a-b.y,a-b.z}; }
float3 operator+(float3 a, float b) { return {a.x+b,a.y+b,a.z+b}; }
float3 operator*(float3 a, float3 b) { return {a.x*b.x,a.y*b.y,a.z*b.z}; }
float3 operator*(float3 a, float b) { return {a.x*b,a.y*b,a.z*b}; }
float3 operator*(float a, float3 b) { return b*a; }
float3 operator/(float3 a, float b) { return {a.x/b,a.y/b,a.z/b}; }
float3& operator+=(float3& a, float3 b) { a=a+b; return a; }
bool3 operator>(float3 a, float b) { return {a.x>b,a.y>b,a.z>b}; }
bool any(bool3 a) { return a.x || a.y || a.z; }
float dot(float3 a, float3 b) { return a.x*b.x+a.y*b.y+a.z*b.z; }
float3 normalize(float3 a) { return a/sqrt(dot(a,a)); }
float saturate(float x) { return max(0.f,std::min(1.f,x)); }
float square(float x) { return x*x; }
struct Material { float roughness; float3 specularF0; };
struct RAB_Surface { float3 worldPos, normal, geoNormal, viewDir; Material material; };
struct RAB_LightSample { float3 position, radiance; float solidAnglePdf; };
struct SplitBrdf { float demodulatedDiffuse; float3 specular; };
const int SceneBVH = 0;
RAB_LightSample fixtureLight;
int samplingCalls = 0, visibilityCalls = 0;
uint RAB_LoadLightInfo(uint index, bool) { return index; }
RAB_LightSample RAB_SamplePolymorphicLight(uint, RAB_Surface, float2) {
    ++samplingCalls;
    return fixtureLight;
}
float3 GetFinalVisibility(int, RAB_Surface, float3) {
    ++visibilityCalls;
    return {1.f,.5f,.25f};
}
#include "reference_under_test.h"

bool near(float actual, float expected) { return std::abs(actual-expected)<2e-6f; }
bool same(float3 actual, float3 expected) {
    return near(actual.x,expected.x) && near(actual.y,expected.y) && near(actual.z,expected.z);
}
bool require(bool condition, const char* message) {
    if (!condition) std::fprintf(stderr,"%s\n",message);
    return condition;
}

int main(int argc, char** argv) {
    if (argc != 2) return 2;
    const float3 originalDiffuse={.1f,.2f,.3f}, originalSpecular={.4f,.5f,.6f};
    float3 diffuse=originalDiffuse, specular=originalSpecular;
    RAB_Surface surface={{2.f,-3.f,5.f},{0.f,0.f,1.f},{0.f,0.f,1.f},
                         {0.f,0.f,1.f},{.5f,{.04f,.08f,.16f}}};
    fixtureLight={surface.worldPos+float3{0.f,0.f,.005f},{8.f,4.f,2.f},2.f};
    const bool front=std::strcmp(argv[1],"front")==0;
    if (!front) {
        surface.normal={.8f,0.f,.6f};
        surface.viewDir=surface.normal;
        const float z=std::strcmp(argv[1],"below")==0 ? -.25f : 0.f;
        fixtureLight.position=surface.worldPos+float3{1.f,0.f,z};
        // The actual production BRDF is positive in this tilted shading hemisphere.
        const auto brdf=EvaluateBrdf(surface,fixtureLight.position);
        if (!require(brdf.demodulatedDiffuse>0.f && any(brdf.specular>0.f),
                     "Fixture must retain both BRDF lobes before the geometric gate")) return 1;
    }
    AddSample(surface,7,{.2f,.7f},.5f,4,diffuse,specular);
    bool ok=require(samplingCalls==1,"Sample generation changed");
    if (!front) {
        ok=require(same(diffuse,originalDiffuse),"Below/tangent geometry sample changed diffuse") && ok;
        ok=require(same(specular,originalSpecular),"Below/tangent geometry sample changed specular") && ok;
        ok=require(visibilityCalls==0,"Rejected sample traced final visibility") && ok;
    } else {
        // N=V=L, roughness=.5: Lambert=1/pi, GGX_times_NoL=4*F0/pi.
        // radiance*visibility/(selectionPDF*solidAnglePDF*count)=(2,.5,.125).
        const float3 wantDiffuse=originalDiffuse+float3{2.f/M_PI,.5f/M_PI,.125f/M_PI};
        const float3 wantSpecular=originalSpecular+float3{.32f/M_PI,.16f/M_PI,.08f/M_PI};
        ok=require(same(diffuse,wantDiffuse),"Front diffuse or PDF/count weighting changed") && ok;
        ok=require(same(specular,wantSpecular),"Front specular or RGB visibility changed") && ok;
        ok=require(visibilityCalls==1,"Front near-field sample was suppressed") && ok;
    }
    return ok ? 0 : 1;
}

