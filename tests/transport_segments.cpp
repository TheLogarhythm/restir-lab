// Production shader functions; only scene lookup and DXR candidate enumeration are faked.
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <vector>
using uint = unsigned;
struct float2 { float x=0,y=0; };
struct float3 { float x,y,z; float3(float a=0):x(a),y(a),z(a){} float3(float a,float b,float c):x(a),y(b),z(c){} };
struct bool3 { bool x,y,z; };
float3 operator*(float3 a,float3 b) { return {a.x*b.x,a.y*b.y,a.z*b.z}; }
float3 operator*(float a,float3 b) { return float3(a)*b; }
float3& operator*=(float3& a,float3 b) { a=a*b; return a; }
bool3 operator==(float3 a,float b) { return {a.x==b,a.y==b,a.z==b}; }
bool3 operator!=(float3 a,float b) { return {a.x!=b,a.y!=b,a.z!=b}; }
bool all(bool3 b) { return b.x&&b.y&&b.z; }
bool any(bool3 b) { return b.x||b.y||b.z; }
#include "payload_under_test.h"
static_assert(sizeof(RAB_RayPayload)==44,"The isolated DXR pipeline must allow the complete payload");
struct RayDesc { float3 Origin,Direction; float TMin=0,TMax=100; };
constexpr int MaterialDomain_AlphaTested=1,MaterialDomain_AlphaBlended=2,MaterialDomain_Transmissive=3,
    MaterialDomain_TransmissiveAlphaTested=4,MaterialDomain_TransmissiveAlphaBlended=5;
constexpr uint INSTANCE_MASK_OPAQUE=1,INSTANCE_MASK_ALPHA_TESTED=2,INSTANCE_MASK_TRANSPARENT=4;
constexpr uint RAY_FLAG_NONE=0,RAY_FLAG_SKIP_PROCEDURAL_PRIMITIVES=1,RAY_FLAG_CULL_OPAQUE=2;
constexpr int CANDIDATE_NON_OPAQUE_TRIANGLE=1,COMMITTED_TRIANGLE_HIT=1,COMMITTED_NOTHING=0;
constexpr int SceneBVH=0,GeomAttr_TexCoord=1,MatAttr_BaseColor=1,MatAttr_Transmission=2;
constexpr int t_InstanceData=0,t_GeometryData=0,t_MaterialConstants=0,s_MaterialSampler=0;
struct MaterialConstants { int domain=0; float alphaCutoff=.5f; };
struct MaterialSample { float opacity=1,transmission=1,metalness=0; bool hasMetalRoughParams=true; float3 baseColor=1; };
struct GeometrySample { MaterialConstants material; uint id; };
struct Hit { float t; bool opaque; MaterialConstants material; MaterialSample sample; uint mask=7; };
std::vector<Hit> hits;
GeometrySample getGeometryFromHit(uint id,uint,uint,float2,int,int,int,int) { return {hits[id].material,id}; }
MaterialSample sampleGeometryMaterial(GeometrySample g,int,int,int,int,int) { return hits[g.id].sample; }
struct { struct { bool enableAlphaTestedGeometry=true,enableTransparentGeometry=true; } sceneConstants; } g_Const;
int traceCount=0;
struct RayAttributes { float2 uv; };
uint callbackHit=0; bool ignored=false;
void IgnoreHit() { ignored=true; }
uint InstanceID() { return callbackHit; } uint GeometryIndex() { return 0; } uint PrimitiveIndex() { return 0; }
float RayTCurrent() { return hits[callbackHit].t; }
constexpr uint HIT_KIND_TRIANGLE_FRONT_FACE=1;
uint HitKind() { return HIT_KIND_TRIANGLE_FRONT_FACE; }
void TraceRay(int,uint,uint,int,int,int,RayDesc,RAB_RayPayload&);
template<uint flags> struct RayQuery {
    uint next=0,current=0,committed=~0u,mask=0,dynamicFlags=0; RayDesc ray;
    void TraceRayInline(int,uint f,uint m,RayDesc r) { ++traceCount; ray=r; mask=m; dynamicFlags=f; }
    bool Proceed() {
        while(next<hits.size()) {
            current=next++; const auto& h=hits[current];
            if(!(h.mask&mask)||h.t<=ray.TMin||h.t>=ray.TMax) continue;
            if(h.opaque) { if((flags|dynamicFlags)&RAY_FLAG_CULL_OPAQUE) continue; CommitNonOpaqueTriangleHit(); }
            else return true;
        }
        return false;
    }
    int CandidateType() { return CANDIDATE_NON_OPAQUE_TRIANGLE; }
    uint CandidateInstanceID() { return current; } uint CandidateGeometryIndex() { return 0; } uint CandidatePrimitiveIndex() { return 0; }
    float2 CandidateTriangleBarycentrics() { return {}; }
    void CommitNonOpaqueTriangleHit() { committed=current; ray.TMax=hits[current].t; }
    int CommittedStatus() { return committed==~0u?COMMITTED_NOTHING:COMMITTED_TRIANGLE_HIT; }
    uint CommittedInstanceID() { return committed; } uint CommittedGeometryIndex() { return 0; } uint CommittedPrimitiveIndex() { return 0; }
    float2 CommittedTriangleBarycentrics() { return {}; } float CommittedRayT() { return ray.TMax; } bool CommittedTriangleFrontFace() { return true; }
};
#include "segments_under_test.h"
void TraceRay(int,uint flags,uint mask,int,int,int,RayDesc ray,RAB_RayPayload& payload) {
    ++traceCount; uint committed=~0u;
    for(uint i=0;i<hits.size();++i) {
        const auto& h=hits[i];
        if(!(h.mask&mask)||h.t<=ray.TMin||h.t>=ray.TMax) continue;
        if(h.opaque&&bool(flags&RAY_FLAG_CULL_OPAQUE)) continue;
        ignored=false; callbackHit=i;
        if(!h.opaque) AnyHit(payload,{});
        if(!ignored) { committed=i; ray.TMax=h.t; }
    }
    if(committed!=~0u) { callbackHit=committed; ClosestHit(payload,{}); }
}
bool close(float3 a,float3 b) { return std::abs(a.x-b.x)<1e-6&&std::abs(a.y-b.y)<1e-6&&std::abs(a.z-b.z)<1e-6; }
bool check(float3 wanted,float hitT,const char* message) {
    for(auto trace:{TraceNextBounce,TraceGiFixture}) {
        const auto result=trace({});
        if(!close(result.throughput,wanted)||result.committedRayT!=hitT||result.labTraceFlags!=0) {
            std::fprintf(stderr,"%s: hit=%g transmittance=(%g,%g,%g)\n",message,result.committedRayT,result.throughput.x,result.throughput.y,result.throughput.z); return false;
        }
    }
    return true;
}
int main() {
    const Hit opaque={5,true,{},{}},behind={10,false,{MaterialDomain_Transmissive,.5f},{1,1,0,true,{.3f,.6f,.9f}}},
        front={3,false,{MaterialDomain_Transmissive,.5f},{1,1,0,true,{.5f,.25f,1}}};
    bool ok=true;
    hits={behind,opaque}; ok=check(1,5,"Transparent candidate behind final opaque hit must not attenuate")&&ok;
    hits={opaque,behind}; ok=check(1,5,"Opaque-first order must give the same endpoint")&&ok;
    hits={behind,front,opaque}; ok=check({.5f,.25f,1},5,"Only transmission before endpoint belongs to the segment")&&ok;
    Hit cutout=opaque; cutout.opaque=false; cutout.material.domain=MaterialDomain_AlphaTested;
    hits={behind,cutout}; ok=check(1,5,"Accepted alpha-test hit bounds transmission")&&ok;
    cutout.sample.opacity=.25f;
    hits={cutout,behind}; ok=check({.3f,.6f,.9f},0,"Rejected cutout leaves a miss and transmission to original TMax")&&ok;
    Hit zero=front; zero.sample.baseColor=0;
    hits={zero,opaque}; ok=check(0,5,"Black transmission must not replace the opaque scattering endpoint")&&ok;
    Hit zeroBehind=behind; zeroBehind.sample.baseColor=0;
    hits={zeroBehind,front,opaque}; ok=check({.5f,.25f,1},5,"Behind-hit zero must not turn front transparent layer into opaque hit")&&ok;
    Hit alphaBlend=front; alphaBlend.material.domain=MaterialDomain_AlphaBlended; alphaBlend.sample.opacity=.25f;
    hits={alphaBlend,opaque}; ok=check(.75f,5,"Alpha blend attenuation remains one minus opacity")&&ok;
    Hit transmissionBlend=front; transmissionBlend.material.domain=MaterialDomain_TransmissiveAlphaBlended;
    transmissionBlend.sample={.25f,.8f,.5f,true,{.2f,.4f,.8f}};
    hits={transmissionBlend,opaque}; ok=check({.06f,.12f,.24f},5,"Transmission/metalness/color/opacity factors are each applied once")&&ok;
    Hit transmissionMask=front; transmissionMask.material.domain=MaterialDomain_TransmissiveAlphaTested;
    transmissionMask.sample.opacity=.25f;
    hits={transmissionMask,opaque}; ok=check(1,5,"Masked-out transmissive geometry contributes no attenuation")&&ok;
    hits={opaque}; traceCount=0; ok=check(1,5,"Opaque-only segment remains unchanged")&&ok;
    if(traceCount!=2) { std::fprintf(stderr,"Opaque-only segment must not pay for a second trace\n"); ok=false; }
    hits={behind,opaque}; traceCount=0; ok=check(1,5,"Behind transparency requests bounded retrace")&&ok;
    if(traceCount!=4) { std::fprintf(stderr,"Tint encountered during search must cause exactly one bounded retrace\n"); ok=false; }
    Hit masked=front; masked.mask=INSTANCE_MASK_TRANSPARENT;
    g_Const.sceneConstants.enableTransparentGeometry=false;
    hits={masked,opaque}; ok=check(1,5,"Original instance mask must stay in effect in both traces")&&ok;
    return ok?0:1;
}
