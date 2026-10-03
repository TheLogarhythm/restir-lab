// Algorithm 2 direction update; shared by the shader and deterministic CPU tests.
#ifndef LAB_PDF_RESERVOIR_MATH_H
#define LAB_PDF_RESERVOIR_MATH_H
#ifdef __cplusplus
using LabUint = unsigned;
struct LabMoment { float x, y, z; };
using std::isfinite;
#define LAB_INLINE inline
#else
#define LabUint uint
#define LabMoment float3
#define LAB_INLINE
#endif

// Full precision, 32 bytes/pixel/bank; no spatial reuse of this state.
struct LabDirectionReservoir
{
    LabUint lightData;
    LabUint uvData;
    float W;
    float M;
    LabMoment moment;
    float padding;
};

LAB_INLINE LabDirectionReservoir LabMergeDirection(LabDirectionReservoir current,
    LabDirectionReservoir history, float pCurrent, float pCurrentAtHistory,
    float pHistoryHere, float pHistoryOld, float historyM, float random)
{
    if (history.W <= 0.f || history.M <= 0.f || history.lightData == 0 || historyM <= 0.f)
        return current;
    // Appendix A balance weights in RTXDI's light/UV measure (Eqs. 17--18).
    float denominator0 = pCurrent + historyM * pCurrentAtHistory;
    float denominator1 = pHistoryHere + historyM * pHistoryOld;
    float w0 = denominator0 > 0.f ? pCurrent / denominator0 * pCurrent * current.W : 0.f;
    float w1 = denominator1 > 0.f ? historyM * pHistoryOld / denominator1 * pHistoryHere * history.W : 0.f;
    float sum = w0 + w1;
    current.M += historyM;
    if (sum > 0.f && isfinite(sum)) {
        current.moment.x = (current.moment.x * w0 + history.moment.x * w1) / sum;
        current.moment.y = (current.moment.y * w0 + history.moment.y * w1) / sum;
        current.moment.z = (current.moment.z * w0 + history.moment.z * w1) / sum;
        if (random * sum < w1) {
            current.lightData = history.lightData;
            current.uvData = history.uvData;
            pCurrent = pHistoryHere;
        }
        current.W = pCurrent > 0.f ? sum / pCurrent : 0.f;
    } else {
        current.W = 0.f;
        current.moment.x = current.moment.y = current.moment.z = 0.f;
    }
    return current;
}

#ifndef __cplusplus
#undef LabUint
#undef LabMoment
#endif
#undef LAB_INLINE
#endif
