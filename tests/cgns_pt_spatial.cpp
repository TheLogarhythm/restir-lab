#include <cassert>
#include <cmath>
#include <vector>
using uint=unsigned;
using std::isnan; using std::isinf;
struct int2;
struct float2 { float x,y; float2(float a=0,float b=0):x(a),y(b){} };
struct uint2 { uint x,y; uint2(uint a=0,uint b=0):x(a),y(b){} uint2(int2); };
struct int2 { int x,y; int2(int a=0,int b=0):x(a),y(b){} int2(uint2 p):x(p.x),y(p.y){} int2(float2 p):x(int(p.x)),y(int(p.y)){} };
uint2::uint2(int2 p):x(p.x),y(p.y){}
int2 operator+(int2 a,int2 b){return {a.x+b.x,a.y+b.y};}
float2 operator*(float2 a,float b){return {a.x*b,a.y*b};}
struct float3 { float x; float3(float a=0,float=0,float=0):x(a){} };
#define TARGET_FUNCTION_TYPE float3
struct RAB_Surface { int id; };
struct RTXDI_PTReservoir { float3 translatedWorldPosition,radiance,worldNormal,targetFunction;
 float weightSum=0,M=0,partialJacobian=0,rcWiPdf=0; uint age=0,randomSeed=0,randomIndex=0,rcVertexLength=2,pathLength=3; };
struct RTXDI_PTSpatialResamplingParameters { bool enableSpatialHeuristicMode=true; float samplingRadius=1,normalThreshold=0,depthThreshold=0; };
struct RTXDI_RuntimeParameters { uint neighborOffsetMask=3,activeCheckerboardField=0; };
struct RTXDI_PTSpatialResamplingRuntimeParameters { uint2 pixelPosition,reservoirPosition,viewportSize={5,1}; };
struct RTXDI_PTHybridShiftPerFrameParameters {};
struct RTXDI_PTReconnectionParameters {};
struct RTXDI_ReservoirBufferParameters {};
struct RTXDI_PTBufferIndices { uint spatialResamplingInputBufferIndex=0; };
struct RTXDI_RandomSamplerState {};
struct RAB_PathTracerUserData {};
constexpr int RTXDI_PTPathTraceInvocationType_Spatial=0,RTXDI_PTPathTraceInvocationType_SpatialInverse=1;
int picks[4]={1,2,-1,-1}; uint merged=99; bool rejectGeometry=false,rejectMaterial=false;
std::vector<int> reads;
struct { struct { struct { uint numSpatialSamples=4; } spatialResampling; } restirPT; } g_Const;
struct NeighborBuffer { uint Load(uint address) { int p=picks[address/4];return p<0?~0u:uint(p); } } buffer;
#define RTXDI_SPATIAL_NEIGHBOR_SELECTION_BUFFER buffer
#define SPATIAL_HEURISTIC_MAX_NEIGHBORS 4
#define SPATIAL_HEURISTIC_INVALID_NEIGHBOR 0xFFFFFFFFu
struct Offset { float2 xy; } offsets[4]={{{1,0}},{{2,0}},{{3,0}},{{4,0}}};
#define RTXDI_NEIGHBOR_OFFSETS_BUFFER offsets
RTXDI_PTReservoir reservoirs[5];
int2 RAB_ClampSamplePositionIntoView(int2 p,bool){return p;}
void RTXDI_ActivateCheckerboardPixel(int2&,bool,uint){}
RAB_Surface RAB_GetGBufferSurface(uint2 p,bool){reads.push_back(int(p.x));return {p.x<5?int(p.x):-1};}
bool RAB_IsSurfaceValid(RAB_Surface s){return s.id>=0;}
float RAB_GetSurfaceNormal(RAB_Surface s){return float(s.id);}
float RAB_GetSurfaceLinearDepth(RAB_Surface){return 0;}
float RAB_GetSurfaceWorldPos(RAB_Surface s){return float(s.id);}
int RAB_GetMaterial(RAB_Surface s){return s.id;}
bool RAB_AreMaterialsSimilar(int,int n){return !(rejectMaterial&&n==1);}
bool RTXDI_IsValidNeighbor(float,float n,float,float,float,float){return !(rejectGeometry&&n==1);}
uint2 RTXDI_PixelPosToReservoirPos(uint2 p,uint){return p;}
RTXDI_PTReservoir RTXDI_LoadPTReservoir(RTXDI_ReservoirBufferParameters,uint2 p,uint){assert(p.x<5);return reservoirs[p.x];}
RTXDI_PTReservoir RTXDI_EmptyPTReservoir(){return {};}
bool RTXDI_IsValidPTReservoir(RTXDI_PTReservoir r){return r.M>0;}
float RTXDI_Luminance(float3 f){return f.x;}
float RTXDI_GetNextRandom(RTXDI_RandomSamplerState&){return .99f;}
float RTXDI_CalculateJacobian(float,float,float3,float3){return 1;}
bool ShouldEvaluateSpatialReconnection(RTXDI_PTReservoir){return false;}
void EvaluateReconnection(RTXDI_PTHybridShiftPerFrameParameters,float3&,RAB_Surface,RTXDI_PTReservoir){assert(false);}
void RAB_PathTracerUserDataSetPathType(RAB_PathTracerUserData&,int){}
int BuildHSParams(RTXDI_PTSpatialResamplingRuntimeParameters){return 0;}
uint CalculateNumSamples(RTXDI_PTSpatialResamplingParameters,RTXDI_PTReservoir,RTXDI_PTReservoir){return 4;}
void RTXDI_ComputeHybridShift(RAB_Surface& surface,RTXDI_PTReservoir& r,RTXDI_PTHybridShiftPerFrameParameters,int,RTXDI_PTReconnectionParameters,float3& f,float& j,RAB_PathTracerUserData&){
 int sample=int(r.translatedWorldPosition.x);
 if(!r.M){f=0;j=1;return;}
 const float targets[5][4]={{0,2,5,7},{0,3,5,7},{0,4,5,7},{0,2,5,7},{0,2,5,7}};
 f=targets[surface.id][sample]; j=surface.id==0?(sample==2?2.f:sample==3?.5f:1.f):surface.id==1?.5f:surface.id==2?2.f:1.f;
 r.partialJacobian=999; // inverse must restore the selected sample's cache.
}
uint countbits(uint n){uint c=0;for(;n;n>>=1)c+=n&1;return c;}
void LabRecordSpatialNeighbors(uint2,uint n){merged=n;}
#include "pt_under_test.h"
void close(float a,float b){assert(std::abs(a-b)<2e-6f);}
RTXDI_PTReservoir run(bool original=false,bool cgns=true){
 bool resampled=false;RAB_PathTracerUserData data;RTXDI_PTSpatialResamplingParameters p;p.enableSpatialHeuristicMode=cgns;
 return original?OriginalSpatialResampling({},p,{},{},{},{},{},{},resampled,data):RTXDI_PTSpatialResampling({},p,{},{},{},{},{},{},resampled,data);
}
int main(){
 reservoirs[0].translatedWorldPosition=1;reservoirs[0].targetFunction=2;reservoirs[0].M=2;reservoirs[0].weightSum=1.5f;reservoirs[0].partialJacobian=17;
 reservoirs[1].translatedWorldPosition=2;reservoirs[1].M=3;reservoirs[1].weightSum=.5f;
 reservoirs[2].translatedWorldPosition=3;reservoirs[2].M=5;reservoirs[2].weightSum=.25f;
 auto r=run();assert(r.M==10&&merged==2&&r.translatedWorldPosition.x==1&&r.partialJacobian==17);close(r.weightSum,25.375f/48.5f);
 assert((reads==std::vector<int>{0,1,2,65535,65535,1,2}));
 rejectGeometry=true;r=run();assert(r.M==7&&merged==1);close(r.weightSum,10.375f/44.f);
 rejectGeometry=false;rejectMaterial=true;r=run();assert(r.M==7&&merged==1);close(r.weightSum,10.375f/44.f);
 rejectMaterial=false;reservoirs[1]={};r=run();assert(r.M==7);close(r.weightSum,10.375f/44.f);
 for(auto& p:picks)p=-1;r=run();assert(r.M==2&&merged==0);close(r.weightSum,1.5f);
 reservoirs[0]={};r=run();assert(r.M==0&&r.weightSum==0);
 reservoirs[0].M=2;reservoirs[0].weightSum=1.5f;reservoirs[0].targetFunction=2;reservoirs[0].translatedWorldPosition=1;
 auto off=run(false,false),control=run(true,false);
 assert(off.M==control.M&&off.weightSum==control.weightSum&&off.targetFunction.x==control.targetFunction.x);
 return 0;
}
