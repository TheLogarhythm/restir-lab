// Independent implementation of Tokuyoshi 2023, Eqs. 9, 12--16.
// Scalar HLSL/C++ subset: numerical tests execute these exact shader functions.
#ifndef LAB_PDF_SIMILARITY_MATH_H
#define LAB_PDF_SIMILARITY_MATH_H
#ifdef __cplusplus
// C++ callers include <cmath> first; ShaderMake scans even conditional includes.
using std::sqrt; using std::exp; using std::pow;
#define LAB_INLINE inline
#else
#define LAB_INLINE
#endif

LAB_INLINE float LabClamp01(float x) { return x < 0.f ? 0.f : (x > 1.f ? 1.f : x); }
LAB_INLINE float LabSmoothedKappa(float r)
{
    r = LabClamp01(r);
    // Algebraically combine Eqs. 9 and 13, avoiding infinity at r=1.
    float numerator = r * (3.f - r*r);
    return 100.f * numerator / (numerator + 100.f * (1.f - r*r));
}
LAB_INLINE float LabPdfSimilarity(float r0, float r1, float cosine)
{
    float a = LabSmoothedKappa(r0), b = LabSmoothedKappa(r1);
    // Eq. 14 is singular for two uniform lobes; their similarity is one.
    if (a + b <= 1e-12f) return 1.f;
    if (a * b <= 0.f) return 0.f;
    cosine = cosine < -1.f ? -1.f : (cosine > 1.f ? 1.f : cosine);
    float amplitude = LabClamp01(2.f * sqrt(a*b) / (a+b));
    return LabClamp01(pow(amplitude, 10.f) * exp(10.f * a*b/(a+b) * (cosine-1.f)));
}
LAB_INLINE float LabPdfConfidence(float m0, float m1)
{
    // RTXDI normalizes initial reservoir M to one; Mmax=20M.
    return LabClamp01(((m0 < m1 ? m0 : m1) - 1.f) / 20.f);
}
LAB_INLINE float LabDirectionHistory(float count, float cosine)
{
    cosine = cosine < -1.f ? -1.f : (cosine > 1.f ? 1.f : cosine);
    return (count < 20.f ? count : 20.f) * exp(1000.f * (cosine - 1.f));
}
#undef LAB_INLINE
#endif
