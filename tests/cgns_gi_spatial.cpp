// Real SDK GI reservoir math and spatial loops; deterministic application callbacks.
#include <cassert>
#include <cmath>
#include <vector>
#include <algorithm>
using std::min;
using uint = unsigned;
struct int2; struct uint2;
struct float2 { float x,y; float2(float a=0,float b=0):x(a),y(b){} float2(uint2); };
struct uint2 { uint x, y; uint2(uint a=0,uint b=0):x(a),y(b){} uint2(int2); };
struct int2 { int x,y; int2(int a=0,int b=0):x(a),y(b){} int2(uint2 p):x(p.x),y(p.y){} int2(float2 p):x(int(p.x)),y(int(p.y)){} };
float2::float2(uint2 p):x(float(p.x)),y(float(p.y)){}
uint2::uint2(int2 p):x(p.x),y(p.y){}
int2 operator+(int2 a,int2 b){return {a.x+b.x,a.y+b.y};}
int2 operator*(int2 a,int2 b){return {a.x*b.x,a.y*b.y};}
int2 operator*(int2 a,int b){return {a.x*b,a.y*b};}
float2 operator+(float2 a,float2 b){return {a.x+b.x,a.y+b.y};}
float2 round(float2 a){return {std::round(a.x),std::round(a.y)};}
struct RAB_Surface { int id; };
struct float3 { float x,y,z; float2 xy; float3(float a=0,float b=0,float c=0):x(a),y(b),z(c),xy(a,b){} };
void LabObserveFinite(float value){assert(std::isfinite(value));}
void LabObserveFinite(float3 value){assert(std::isfinite(value.x)&&std::isfinite(value.y)&&std::isfinite(value.z));}
struct RTXDI_GIReservoir { float position=0,normal=0,radiance=0,weightSum=0; uint M=0,age=0; };
struct RTXDI_RandomSamplerState { uint calls=0; };
struct RTXDI_RuntimeParameters { uint neighborOffsetMask=3,activeCheckerboardField=0; };
struct RTXDI_ReservoirBufferParameters {};
struct RTXDI_GISpatialResamplingParameters {
 uint numSamples=4; float samplingRadius=1,normalThreshold=0,depthThreshold=0; int biasCorrectionMode=2;
};
struct RTXDI_GITemporalResamplingParameters { bool enableFallbackSampling=false,enablePermutationSampling=false;
 uint uniformRandomNumber=0,maxHistoryLength=20,maxReservoirAge=20; float normalThreshold=0,depthThreshold=0; int biasCorrectionMode=2; };
#define RTXDI_BIAS_CORRECTION_BASIC 1
#define RTXDI_BIAS_CORRECTION_RAY_TRACED 2
#define RTXDI_GI_ALLOWED_BIAS_CORRECTION 2
RTXDI_GIReservoir reservoirs[5];
bool enabled=true, rejectGeometry=false, rejectMaterial=false, rejectJacobian=false, hiddenThird=false;
int rejectedPixel=-1;
int picks[4]={4,-1,3,-1};
float randoms[5]={0,.99f,.99f,.99f,.99f};
uint merged=999,callbacks=0;
std::vector<int> reads;
RTXDI_GIReservoir RTXDI_EmptyGIReservoir(){return {};}
bool RTXDI_IsValidGIReservoir(RTXDI_GIReservoir r){return r.M!=0;}
bool any(bool value){return value;}
float RTXDI_GetNextRandom(RTXDI_RandomSamplerState& r){assert(r.calls<5);return randoms[r.calls++];}
int2 RTXDI_CalculateSpatialResamplingOffset(int i,float,uint){return {1+i,0};}
int2 RAB_ClampSamplePositionIntoView(int2 p,bool){return p;}
void RTXDI_ActivateCheckerboardPixel(int2&,bool,uint){}
RAB_Surface RAB_GetGBufferSurface(int2 p,bool){assert(p.x>=0&&p.x<5);reads.push_back(p.x);return {p.x};}
RAB_Surface RAB_EmptySurface(){return {-1};}
bool RAB_IsSurfaceValid(RAB_Surface s){return s.id>=0;}
void RTXDI_ApplyPermutationSampling(int2&,uint){}
bool RAB_GetTemporalConservativeVisibility(RAB_Surface,RAB_Surface,float){return true;}
float RAB_GetSurfaceNormal(RAB_Surface s){return float(s.id);}
float RAB_GetSurfaceLinearDepth(RAB_Surface){return 0;}
float RAB_GetSurfaceWorldPos(RAB_Surface s){return float(s.id);}
bool RTXDI_IsValidNeighbor(float,float n,float,float,float,float){return !rejectGeometry&&int(n)!=rejectedPixel;}
int RAB_GetMaterial(RAB_Surface s){return s.id;}
bool RAB_AreMaterialsSimilar(int,int){return !rejectMaterial;}
uint2 RTXDI_PixelPosToReservoirPos(int2 p,uint){return uint2(p);}
RTXDI_GIReservoir RTXDI_LoadGIReservoir(RTXDI_ReservoirBufferParameters,uint2 p,uint){assert(p.x<5);return reservoirs[p.x];}
float RTXDI_CalculateJacobian(float,float donor,float,float){return donor==4?2.f:(donor==3?.5f:1.f);}
bool RAB_ValidateGISampleWithJacobian(float& j){return !(rejectJacobian&&j==2.f);}
float RAB_GetGISampleTargetPdfForSurface(float sample,float radiance,RAB_Surface s){
 const float pdf[5][3]={{2,3,5},{3,5,7},{5,9,13},{4,7,11},{6,13,17}};
 assert(sample>=1&&sample<=3);return pdf[s.id][int(sample)-1]*radiance;
}
bool RAB_GetConservativeVisibility(RAB_Surface s,float){return !(hiddenThird&&s.id==3);}
bool LabTransportCgnsEnabled(){return enabled;}
bool LabCgnsNeighbor(uint2,uint i,int2& p){assert(i<4);++callbacks;p={picks[i],0};return picks[i]>=0;}
void LabRecordSpatialNeighbors(uint2,uint n){merged=n;}
#include "gi_under_test.h"
void close(float a,float b){assert(std::abs(a-b)<2e-6f);}
RTXDI_GIReservoir run(bool original=false){
 RTXDI_RandomSamplerState r;
 return original?OriginalSpatialResampling({}, {0},0,reservoirs[0],r,{},{},{}):
                 RTXDI_GISpatialResampling({}, {0},0,reservoirs[0],r,{},{},{});
}
void equal(RTXDI_GIReservoir a,RTXDI_GIReservoir b){
 assert(a.M==b.M&&a.age==b.age&&a.position==b.position&&a.normal==b.normal&&a.radiance==b.radiance&&a.weightSum==b.weightSum);
}
int main(){
#ifdef LAB_NULL_TEST
 {
  reservoirs[0]={0,0,0,0,9,0};
  RTXDI_GIReservoir positive={1,0,1,2,1,0}; RTXDI_RandomSamplerState rng;
  auto r=RTXDI_GITemporalResampling({}, {0}, {},0,positive,rng,{},{},{});
  assert(r.M==10&&r.position==1); close(r.weightSum,.2f);
  reservoirs[0]=positive; reservoirs[0].M=9; rng={};
  r=RTXDI_GITemporalResampling({}, {0}, {},0,{0,0,0,0,1,0},rng,{},{},{});
  assert(r.M==10&&r.position==1); close(r.weightSum,1.8f);
  reservoirs[0]={0,0,0,0,9,0}; rng={};
  r=RTXDI_GITemporalResampling({}, {0}, {},0,{0,0,0,0,1,0},rng,{},{},{});
  assert(r.M==10&&r.weightSum==0&&r.position==0);
 }
#endif
 reads.clear();
 reservoirs[0]={1,0,1,1.5f,2,0};
 reservoirs[1]={2,0,1,.5f,7,0};
 reservoirs[2]={3,0,1,.25f,11,0};
 reservoirs[3]={2,0,1,.5f,3,0};
 reservoirs[4]={3,0,1,.25f,5,0};
 auto result=run();assert(result.M==10&&result.position==1&&merged==2);
 close(result.weightSum,20.75f/46.f);
 assert((reads==std::vector<int>{4,3,4,3}));
 randoms[1]=0;result=run();assert(result.position==3);
 close(result.weightSum,20.75f*17.f/(5.f*128.f));randoms[1]=.99f;
 hiddenThird=true;result=run();close(result.weightSum,20.75f/34.f);hiddenThird=false;
 rejectedPixel=4;reads.clear();result=run();assert(result.M==5&&merged==1);
 close(result.weightSum,8.25f/16.f);assert((reads==std::vector<int>{4,3,3}));rejectedPixel=-1;
 rejectJacobian=true;result=run();assert(result.M==5&&merged==1);close(result.weightSum,8.25f/16.f);rejectJacobian=false;
 rejectGeometry=true;equal(run(),reservoirs[0]);assert(merged==0);rejectGeometry=false;
 rejectMaterial=true;equal(run(),reservoirs[0]);assert(merged==0);rejectMaterial=false;
 for(auto& p:picks)p=-1;reads.clear();equal(run(),reservoirs[0]);assert(merged==0&&reads.empty());
 picks[0]=4;picks[2]=3;
 auto saved=reservoirs[4];reservoirs[4].M=0;result=run();assert(result.M==5&&merged==1);reservoirs[4]=saved;
 // Off branch has exactly the native math, candidate stream and acceptance.
 enabled=false;callbacks=0;
 for(int mask=0;mask<8;++mask){rejectGeometry=mask&1;rejectMaterial=mask&2;hiddenThird=mask&4;
   equal(run(true),run());assert(callbacks==0);}
 rejectGeometry=false;rejectMaterial=false;hiddenThird=false;enabled=true;
 for(auto& r:reservoirs)r={};result=run();assert(result.M==0&&result.weightSum==0&&merged==0);
#ifdef LAB_NULL_TEST
 // Positive center + null proposal: the receiver contributes to MIS denominator
 // even when the null donor's undefined position cannot have a valid Jacobian.
 picks[0]=4;picks[1]=picks[2]=picks[3]=-1;
 reservoirs[0]={1,0,1,1,1,0}; reservoirs[4]={0,0,0,0,1,0};
 rejectJacobian=true;randoms[1]=0;result=run();
 assert(result.M==2&&result.position==1&&merged==1);close(result.weightSum,.25f);
 // A pre-canonicalized zero-radiance proposal also cannot change selection.
 reservoirs[4].weightSum=7;result=run();assert(result.M==2&&result.position==1);close(result.weightSum,.25f);
 reservoirs[0]={0,0,0,0,1,0};result=run();assert(result.M==2&&result.weightSum==0&&merged==1);
 RTXDI_GIReservoir empty={},null={0,0,0,0,1,0};
 assert(!RTXDI_CombineGIReservoirs(empty,null,0,0));assert(empty.M==1&&empty.weightSum==0);
#endif
}
