#include <cmath>
#include <cassert>
#include "../scripts/run/rtxdi_experiments/PdfSimilarityMath.h"
#include "../scripts/falcor/pdf_pt_direction.h"

struct float3 {
    float x, y, z;
    float3(float x = 0) : x(x), y(x), z(x) {}
    float3(float x, float y, float z) : x(x), y(y), z(z) {}
    float3 operator*(float f) const { return {x*f,y*f,z*f}; }
};
struct float4 {
    float3 a;
    float b;
    float4(float3 a = 0, float b = 0) : a(a), b(b) {}
    float4 operator*(float w) const { return {a*w, b*w}; }
    void operator+=(float4 other) {
        a.x += other.a.x; a.y += other.a.y; a.z += other.a.z; b += other.b;
    }
};
float dot(float3 a, float3 b) {return a.x*b.x + a.y*b.y + a.z*b.z;}
float rsqrt(float x) {return 1.f / std::sqrt(x);}
using std::isfinite;
using std::isnan;
float3 labPdfCandidateComponent(bool primary, float3 light, float3 scatter) {
    return {labPdfCandidateComponent(primary, light.x, scatter.x),
            labPdfCandidateComponent(primary, light.y, scatter.y),
            labPdfCandidateComponent(primary, light.z, scatter.z)};
}
struct PathRISState {
    float weight = 0;
    float3 labFirstScatter = {0,-1,0};
    float4 labMoment;
    #include "pdf_pt_candidate.inl"
};

int main() {
    PathRISState ris;
    // Different weights, deliberately different light and scatter directions.
    // The second and third candidates lose their lotteries but both contribute.
    assert(ris.addNEECandidate(0.f,0,{2,0,0},{1,1,1}));
    assert(!ris.addNEECandidate(.99f,2,{0,0,1},{2,2,2}));
    assert(!ris.addBSDFHitCandidate(.99f,0,{1,0,0},{3,3,3}));
    assert(std::abs(ris.labMoment.a.x - 1.f) < 1e-6f);
    assert(std::abs(ris.labMoment.a.y + 5.f) < 1e-6f && ris.labMoment.a.z == 0);
    assert(std::abs(ris.labMoment.b - 6.f) < 1e-6f);
    ris.addNEECandidate(0,0,{-1,0,0},0);
    assert(std::abs(ris.labMoment.b - 6.f) < 1e-6f);
    PathRISState uniform;
    uniform.addNEECandidate(0,0,{1,0,0},1);
    uniform.addNEECandidate(0,0,{-1,0,0},1);
    assert(uniform.labMoment.b > 0.f && dot(uniform.labMoment.a,uniform.labMoment.a)==0.f);
    float a = labPdfSum(1.f, 6.f, .5f), b = labPdfSum(2.f, 8.f, .5f);
    assert(a == 4.f && b == 6.f);
    assert(labPdfSum(1.f, 6.f, 0.f) == 1.f);
    assert(labPdfCount(1.f, 10.f, .5f, 20.f) == 6.f);
    assert(labPdfCount(0.f, 10.f, .5f, 20.f) == 5.f);
    assert(labPdfConfidence(1.f, 20.f, 20.f) == 0.f);
    assert(labPdfConfidence(20.f, 20.f, 20.f) == 1.f);
    assert(labPdfBlend(0.f, 20.f, 20.f, 0.f, 20.f) == 1.f);
    assert(labPdfBlend(1.f, 20.f, 20.f, LabPdfSimilarity(0,1,0),20.f) == 0.f);
    assert(LabPdfSimilarity(0,0,0)==1.f && LabPdfSimilarity(1,1,1)==1.f);
    assert(LabPdfSimilarity(1,1,-1)<1e-8f);
}
