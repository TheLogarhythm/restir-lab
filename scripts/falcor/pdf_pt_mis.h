// Independent weighted-GRIS confidence adaptation for one unpaired PT neighbor.
// Shared verbatim by the injected Slang and CPU shader execution tests.
#ifndef LAB_PDF_PT_EFFECTIVE_M_CORE_V1
#define LAB_PDF_PT_EFFECTIVE_M_CORE_V1
float labPdfEffectiveNeighborM(float rawM, float h)
{
    if (isnan(rawM) || isinf(rawM) || rawM <= 0.f || isnan(h) || isinf(h)) return 0.f;
    return rawM * min(1.f, max(0.f, h));
}
#endif
