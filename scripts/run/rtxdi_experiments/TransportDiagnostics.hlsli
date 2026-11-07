#ifndef LAB_TRANSPORT_DIAGNOSTICS
#define LAB_TRANSPORT_DIAGNOSTICS
RWStructuredBuffer<uint> u_CgnsStatistics : register(u31);
// Sticky across all frames, reset when the run initializes its resources. The
// two existing pixel arrays keep selection/merge counts; one extra word detects
// invalid contributions before SDK RIS guards can turn them into finite zero.
void LabObserveFinite(float3 value)
{
    if (!all(isfinite(value)))
    {
        uint ignored;
        InterlockedAdd(u_CgnsStatistics[2 * uint(g_Const.view.viewportSize.x) * uint(g_Const.view.viewportSize.y)], 1, ignored);
    }
}
#endif
