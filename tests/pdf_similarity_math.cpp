#include <cassert>
#include <cmath>
#include "PdfSimilarityMath.h"

int main()
{
    // Analytic limits and symmetry; these run the same scalar functions as HLSL.
    assert(LabSmoothedKappa(0.f) == 0.f);
    assert(std::abs(LabSmoothedKappa(1.f) - 100.f) < 1e-5f);
    assert(std::abs(LabSmoothedKappa(0.5f) - 137.5f / 76.375f) < 1e-5f);
    assert(LabPdfSimilarity(0.f, 0.f, 0.f) == 1.f);
    assert(LabPdfSimilarity(0.f, 1.f, 0.f) == 0.f);
    assert(std::abs(LabPdfSimilarity(1.f, 1.f, 1.f) - 1.f) < 1e-6f);
    // Equal delta lobes after smoothing: exp(10 * 50 * (cos - 1)).
    assert(std::abs(LabPdfSimilarity(1.f, 1.f, 0.99f) - std::exp(-5.f)) < 1e-6f);
    assert(LabPdfSimilarity(1.f, 1.f, -1.f) < 1e-20f);
    assert(LabPdfConfidence(1.f, 21.f) == 0.f);
    assert(LabPdfConfidence(11.f, 21.f) == 0.5f);
    assert(LabPdfConfidence(21.f, 21.f) == 1.f);
    assert(LabDirectionHistory(21.f, 1.f) == 20.f);
    assert(LabDirectionHistory(21.f, -1.f) == 0.f);
    for (int a = 0; a <= 100; ++a)
        for (int b = 0; b <= 100; ++b) {
            float x = LabPdfSimilarity(a / 100.f, b / 100.f, 0.93f);
            float y = LabPdfSimilarity(b / 100.f, a / 100.f, 0.93f);
            assert(std::isfinite(x) && x >= 0.f && x <= 1.f);
            assert(std::abs(x-y) < 1e-6f);
        }
}
