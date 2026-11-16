// Production shader methods are compiled from the overlay by the Python test.
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdio>
#include <limits>
#include <vector>
using uint=unsigned;
using std::isnan; using std::isinf; using std::max; using std::min;
#define USE_AREA_RESERVOIRS 0
#define USE_RESERVOIR_COMPRESSION 0
#define USE_DECOUPLED_SHADING 0
#define EXTRA_SHIFT_ARGS
#define var auto
struct float2 { float x=0,y=0; float2(float v=0):x(v),y(v){} };
struct float3 {
    float x=0,y=0,z=0;
    float3(float v=0):x(v),y(v),z(v){}
    float3(float a,float b,float c):x(a),y(b),z(c){}
};
float3 operator*(float3 a,float b){return {a.x*b,a.y*b,a.z*b};}
float3 operator*(float a,float3 b){return b*a;}
float3 operator+(float3 a,float3 b){return {a.x+b.x,a.y+b.y,a.z+b.z};}
bool operator||(float3 a,float3 b){return a.x||a.y||a.z||b.x||b.y||b.z;}
bool any(bool a){return a;}
float3 isnan(float3 a){return {float(std::isnan(a.x)),float(std::isnan(a.y)),float(std::isnan(a.z))};}
float3 isinf(float3 a){return {float(std::isinf(a.x)),float(std::isinf(a.y)),float(std::isinf(a.z))};}
struct int2 { int x=0,y=0; int2(int v=0):x(v),y(v){} int2(int a,int b):x(a),y(b){} };
using uint2=int2;
int2 operator+(int2 a,int2 b){return {a.x+b.x,a.y+b.y};}
int2 operator+(int2 a,int b){return {a.x+b,a.y+b};}
struct float4 {float x=0,y=0,z=1,w=0; float2 xy={};};
template<class T> struct Buffer {
    std::array<T,8> data{};
    T& operator[](int i){return data.at(i);}
    const T& operator[](int i)const{return data.at(i);}
    T& operator[](int2 p){return data.at(p.x);}
    const T& operator[](int2 p)const{return data.at(p.x);}
};
struct SampleGenerator { uint step=0; };
SampleGenerator TinyUniformSampleGenerator(int2,uint){return {};}
std::vector<float> gRandom={0,.2f,.8f};
float sampleNext1D(SampleGenerator& sg){return gRandom.at(sg.step++);}
struct PackedHitInfo {uint data=0;};
struct HitInfo {
    uint data=0;
    HitInfo(PackedHitInfo p={}):data(p.data){}
    bool isValid()const{return true;}
};
struct PathFlags {uint flags=0;};
struct PathRISState { static float toScalar(float3 a){return a.x;} };
#include "pdf_pt_mis_under_test.h"
float seenCenter=0,seenNeighbor=0;
struct PathReservoir {
    float M=0,weight=0;
    float3 integrand={};
    PathFlags pathFlags;
    uint initRandomSeed=0,rcNextVertexBounceSeed=0;
    float lightPdf=0;
    HitInfo reconnectionHit;
    float reconnectionJacobian=1;
    float3 reconnectionIncidentRadiance={},reconnectionWi={};
    void init(){*this=PathReservoir();}
    void setLensSample(float2){}
    #include "pdf_pt_reservoir_methods.h"
};
struct ReSTIRPathTracingParams {uint seed=0;uint2 frameDim={2,1};uint getReservoirOffset(int2 p)const{return p.x;} };
struct ReSTIRPT {
    bool kUseAreaReservoirs=false,useDoFReconnectionShift=false;
    bool deriveDoFReconnectionShiftProbabilityFromCoC=false,useReservoirSplatting=false;
    float doFReconnectionShiftProbability=0;int numSpatialRounds=1;
    uint sgCount()const{return 1;}uint spatialSgOffset(int)const{return 0;}
};
struct PairwiseFactor {float c_sum,c_c;};
struct ReconnectionData {};
struct PrecomputedShiftData {};
float gH=1,gForward=1,gForwardJ=1,gReverse=1,gReverseJ=1,gSeenM=-1;
int kLabPdfProfile=0;
float labPdfPairWeight(PathReservoir,PathReservoir){return gH;}
Buffer<NeighborValidMask> gMasks;
#include "pdf_pt_workload.h"
float3 shiftPath(const ReSTIRPT,const ReSTIRPathTracingParams,float& j,PathReservoir& r,ReconnectionData,float,bool){j=gForwardJ;gSeenM=r.M;return gForward;}
float3 shiftPathWithPrecomputedInfo(float& j,PathReservoir& r,PrecomputedShiftData){j=gForwardJ;gSeenM=r.M;return gForward;}
#include "pdf_pt_shift.h"
struct PairedNeighborTransform { PairedNeighborTransform(SampleGenerator&,int,int){} void readTransformedDelta(int,int,int,int& x,int& y){x=1;y=0;} };
HitInfo LoadPixelCenterPrimaryHit(ReSTIRPathTracingParams,ReSTIRPT,Buffer<PackedHitInfo>,int2,float3&,float&,float3&){return {};}
HitInfo LoadShiftedPrimaryHit(ReSTIRPathTracingParams,ReSTIRPT,Buffer<PackedHitInfo>,Buffer<PackedHitInfo>,Buffer<float4>,bool,int2,uint,PathReservoir,float3&,float&){return {};}
HitInfo LoadShiftedPrimaryHitAssumeAreaReSTIRAndLoadedLensSample(ReSTIRPathTracingParams,ReSTIRPT,Buffer<PackedHitInfo>,int2,uint,PathReservoir,float3&,float&){return {};}
float computeConfidenceWeightForTwoShifts(int2,float3,bool){return 1;}
int2 getNextNeighborPixel(uint,Buffer<float2>,int2,int,float){return {1,0};}
ReconnectionData loadReconnectionData(Buffer<ReconnectionData>,Buffer<uint>,uint,PathReservoir,HitInfo,float3){return {};}
float3 computeShiftedIntegrand(ReSTIRPT,ReSTIRPathTracingParams,float& j,PathReservoir,ReconnectionData,float){j=gReverseJ;return gReverse;}
float3 computeShiftedIntegrandWithPrecomputedInfo(float& j,PathReservoir,PrecomputedShiftData){j=gReverseJ;return gReverse;}
struct CpuSpatial {
    static const uint kNeighborOffsetCount=32;
    ReSTIRPathTracingParams params;ReSTIRPT restirpt;
    Buffer<PackedHitInfo> vbuffer,shiftedPrimaryHitBuffer,sampleVBuffer;
    Buffer<float2> neighborOffsets;Buffer<float4> doFReconnectionShiftBuffer;
    Buffer<PathReservoir> prevReservoirs,reservoirs;
    Buffer<ReconnectionData> reconnectionDataBuffer;Buffer<uint> reconnectionDataOffsets,sampleSurvivedFrames;
    Buffer<PrecomputedShiftData> precomputedShiftBuffer;
    Buffer<NeighborValidMask> neighborValidMask;
    int gSpatialRoundId=0,gNeighborCount=1;float gGatherRadius=30;bool gUsePairedNeighbors=false;
    int getNeighborCount(){return gNeighborCount;}
    #include "pdf_pt_spatial.h"
};
bool require(bool ok,const char* message){if(!ok)std::fprintf(stderr,"%s\n",message);return ok;}
bool close(float a,float b){return std::isfinite(a)&&std::abs(a-b)<2e-5f*max(1.f,std::abs(b));}
PathReservoir reservoir(float m,float p,float w,uint id){PathReservoir r;r.M=m;r.integrand=p;r.weight=w;r.initRandomSeed=id;return r;}
bool fixture(float h,float mc,float mi,float pc,float pi,float fc,float jf,float rc,float jr,float wc,float wi,float wantM,float wantEnergy,int profile=0){
    kLabPdfProfile=profile;gH=h;gForward=fc;gForwardJ=jf;gReverse=rc;gReverseJ=jr;gSeenM=-1;
    CpuSpatial s;s.prevReservoirs[0]=reservoir(mc,pc,wc,11);s.prevReservoirs[1]=reservoir(mi,pi,wi,22);
    NeighborValidMask mask{};workload(mask,s.prevReservoirs[0],s.prevReservoirs[1]);s.neighborValidMask[0]=mask;
    if(profile==3){ // A center oracle must ignore poisoned mask/confidence data.
        s.neighborValidMask[0].cSum=std::numeric_limits<float>::quiet_NaN();
        s.neighborValidMask[0].labPdfNeighborM=98765;s.neighborValidMask[0].data=1;
    }
    double average=0;
    // Analytically integrate the reservoir decision's single U(0,1) dimension.
    // The first merge has no competitor; the second selects the center iff U
    // is below its exact normalized contribution. A stratified sweep checks
    // both stored final weights and output confidence, not a formula replica.
    for(int q=0;q<4096;q++){
        gRandom={0,.5f,(q+.5f)/4096};
        s.DoPass({0,0});auto r=s.reservoirs[0];
        if(!require(close(r.M,wantM),"Output M did not preserve effective confidence"))return false;
        if(!require(std::isfinite(r.weight)&&r.weight>=0,"Nonfinite/negative reservoir weight"))return false;
        average+=double(r.weight)*r.integrand.x/4096;
    }
    if(!require(close(float(average),wantEnergy),"Merged energy violates the hand-derived two-sided MIS fixture")){
        std::fprintf(stderr,"h=%g Mc=%g Mi=%g energy=%g want=%g\n",h,mc,mi,average,wantEnergy);return false;
    }
    if(profile!=3&&h>0&&mi>0){
        if(!require(close(mask.cSum,mc+h*mi),"Workload cSum kept raw/repeatedly-scaled neighbor M"))return false;
        if(!require(close(gSeenM,h*mi),"Forward shift did not receive effective neighbor M"))return false;
    }
    if(profile!=3&&h==0){
        if(!require(!mask.isValid(0)&&close(mask.cSum,mc),"Zero h scheduled a neighbor or changed cSum"))return false;
    }
    return true;
}
int main(){
    bool ok=true;
    // Mc=2, Mi=4, h=.25 => effective Mi=1. Pc=3, reverse p=2,
    // Pi=5, forward p=6, Jf=.5. Canonical MIS=2/3+1/3*(1-2/8)=11/12;
    // neighbor MIS=1/3*5/(5+3*2)=5/33. Energy=3*2*11/12+3*3*5/33=151/22.
    ok=fixture(.25f,2,4,3,5,6,.5f,4,.5f,2,3,3,151.f/22)&&ok;
    // Both source target shapes and J differ; changing only the candidate
    // contribution by h fails this independently normalized unequal-M case.
    // Mc=.5, effective Mi=.5: canonical MIS=.5+.5*(1-6/(6+2))=.625;
    // neighbor MIS=.5*5/(5+3)=5/16; energy=4*.625+6*5/16=35/8.
    ok=fixture(.125f,.5f,4,2,10,3,2,2,3,2,1,1,35.f/8)&&ok;
    seenNeighbor=0;
    ok=fixture(0,2,4,3,5,6,.5f,4,.5f,2,3,2,6)&&ok;
    ok=require(close(seenCenter,1.f)&&seenNeighbor==0.f,"h=0 must merge only center")&&ok;
    // B=2, C=4. Reverse m_c=.5+.5*(1-4/(4+6))=.8.
    // Forward m_i=.5*10/(10+6)=5/16. Energy=6*.8+9*5/16=609/80.
    ok=fixture(.5f,2,4,3,5,6,.5f,4,.5f,2,3,4,609.f/80)&&ok;
    ok=require(close(seenCenter,4.f/5)&&close(seenNeighbor,5.f/16),"h=.5 MIS terms")&&ok;
    ok=fixture(1,2,4,3,5,6,.5f,4,.5f,2,3,6,758.f/91)&&ok;
    ok=require(close(seenCenter,13.f/21)&&close(seenNeighbor,20.f/39),"h=1 MIS terms")&&ok;
    ok=fixture(.5f,2,4,3,0,0,1,0,1,2,0,4,6)&&ok;
    ok=require(seenNeighbor==0.f,"Zero/zero forward target must have finite zero MIS")&&ok;
    // Zero-weight neighbor still contributes confidence, with exactly zero
    // candidate energy; no reciprocal/weight test may discard its M.
    ok=fixture(.25f,2,4,3,5,0,1,0,1,2,0,3,6)&&ok;
    // Forward failure retains effective M. Reverse failure returns canonical
    // confidence completely; the failed candidate contributes no energy.
    ok=fixture(.25f,2,4,3,5,0,1,0,1,2,3,3,6)&&ok;
    ok=fixture(.25f,2,4,3,5,6,0,0,1,2,3,3,6)&&ok;
    ok=fixture(.25f,2,4,3,5,6,std::numeric_limits<float>::quiet_NaN(),0,1,2,3,3,6)&&ok;
    ok=fixture(.25f,0,4,0,5,6,.5f,0,1,0,3,1,9)&&ok;
    ok=fixture(0,0,4,0,5,6,.5f,0,1,0,3,0,0)&&ok;
    ok=fixture(1,2,0,3,5,6,.5f,4,.5f,2,3,2,6)&&ok;
    // Independent center oracle ignores both mask/cSum corruption and h.
    ok=fixture(.75f,2,4,3,5,6,.5f,4,.5f,2,3,2,6,3)&&ok;
    // h=1 must match the pristine native spatial pass at every RNG sample.
    kLabPdfProfile=1;gH=1;gForward=6;gForwardJ=.5f;gReverse=4;gReverseJ=.5f;
    CpuSpatial a;a.prevReservoirs[0]=reservoir(2,3,2,11);a.prevReservoirs[1]=reservoir(4,5,3,22);
    NeighborValidMask mask{};workload(mask,a.prevReservoirs[0],a.prevReservoirs[1]);a.neighborValidMask[0]=mask;
    for(int q=0;q<17;q++){
        auto b=a;gRandom={0,.5f,(q+.5f)/17};a.DoPass({0,0});b.BaselinePass({0,0});
        auto x=a.reservoirs[0],y=b.reservoirs[0];
        ok=require(x.M==y.M&&x.weight==y.weight&&x.integrand.x==y.integrand.x&&x.initRandomSeed==y.initRandomSeed,"h=1 differs from pristine native spatial pass")&&ok;
    }
    ok=require(labPdfEffectiveNeighborM(4,.25f)==1,"Fractional h was rounded")&&ok;
    ok=require(labPdfEffectiveNeighborM(4,0)==0,"Zero h retained neighbor confidence")&&ok;
    ok=require(labPdfEffectiveNeighborM(4,-1)==0,"Negative h retained neighbor confidence")&&ok;
    ok=require(labPdfEffectiveNeighborM(4,2)==4,"h above one increased neighbor confidence")&&ok;
    ok=require(labPdfEffectiveNeighborM(-1,1)==0,"Negative raw M escaped sanitization")&&ok;
    ok=require(labPdfEffectiveNeighborM(4,std::numeric_limits<float>::quiet_NaN())==0,"NaN h escaped sanitization")&&ok;
    ok=require(labPdfEffectiveNeighborM(std::numeric_limits<float>::infinity(),1)==0,"Infinite raw M escaped sanitization")&&ok;
    return ok?0:1;
}
