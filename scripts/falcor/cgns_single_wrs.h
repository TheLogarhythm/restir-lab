// Shared C++/Slang scalar A-Chao weighted reservoir for one neighbor.
#ifndef LAB_CGNS_SINGLE_WRS_H
#define LAB_CGNS_SINGLE_WRS_H
#ifdef __cplusplus
using uint = unsigned;
#define LAB_SINGLE_INLINE inline
#define LAB_SINGLE_INOUT(T) T&
#else
#define LAB_SINGLE_INLINE
#define LAB_SINGLE_INOUT(T) inout T
#endif
struct LabCgnsSingleWrs { uint selected; float weightSum; bool valid; };
LAB_SINGLE_INLINE LabCgnsSingleWrs LabCgnsSingleCreate()
{
    LabCgnsSingleWrs r;
    r.selected=0xffffffffu; r.weightSum=0.f; r.valid=false;
    return r;
}
LAB_SINGLE_INLINE bool LabCgnsSingleInsert(LAB_SINGLE_INOUT(LabCgnsSingleWrs) r, uint candidate, float weight, float u)
{
    // Comparison guards also reject NaNs. A uniform draw is in [0,1).
    if (!(weight > 0.f) || !(weight < 3.402823466e38f) || !(u >= 0.f) || !(u < 1.f) || candidate==0xffffffffu) return false;
    float sum=r.weightSum+weight;
    if (!(sum > 0.f) || !(sum < 3.402823466e38f)) return false;
    r.weightSum=sum;
    if (!r.valid || u < weight/sum)
    {
        r.selected=candidate; r.valid=true; return true;
    }
    return false;
}
#undef LAB_SINGLE_INLINE
#undef LAB_SINGLE_INOUT
#endif
