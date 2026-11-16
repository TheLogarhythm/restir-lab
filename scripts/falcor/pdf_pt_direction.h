// Shared scalar operations for Slang and the deterministic C++ reference checks.
// PdfSimilarityMath.h supplies Tokuyoshi's smoothed vMF and overlap functions.
#ifndef LAB_PDF_PT_DIRECTION_H
#define LAB_PDF_PT_DIRECTION_H
#ifdef __cplusplus
#define LAB_PT_DIRECTION inline
#define LAB_PT_VECTOR float
#define LAB_PT_MOMENT float
#else
#define LAB_PT_DIRECTION
#define LAB_PT_VECTOR float3
#define LAB_PT_MOMENT float4
#endif

LAB_PT_DIRECTION LAB_PT_VECTOR labPdfCandidateComponent(bool primaryNEE, LAB_PT_VECTOR lightDir, LAB_PT_VECTOR firstScatter)
{
    return primaryNEE ? lightDir : firstScatter;
}

LAB_PT_DIRECTION LAB_PT_MOMENT labPdfSum(LAB_PT_MOMENT current, LAB_PT_MOMENT previous, float retention)
{
    return current + retention * previous;
}

LAB_PT_DIRECTION float labPdfCount(float hasEnergy, float previous, float retention, float limit)
{
    float count = hasEnergy + retention * previous;
    return count < limit ? count : limit;
}

LAB_PT_DIRECTION float labPdfConfidence(float count0, float count1, float limit)
{
    float joint = count0 < count1 ? count0 : count1;
    return limit > 1.f ? LabClamp01((joint - 1.f) / (limit - 1.f)) : 0.f;
}

LAB_PT_DIRECTION float labPdfBlend(float minimumEnergy, float count0, float count1, float similarity, float limit)
{
    if (!(minimumEnergy > 0.f)) return 1.f;
    float confidence = labPdfConfidence(count0, count1, limit);
    return (1.f - confidence) + confidence * similarity;
}

#undef LAB_PT_MOMENT
#undef LAB_PT_VECTOR
#undef LAB_PT_DIRECTION
#endif
