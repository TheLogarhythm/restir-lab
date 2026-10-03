#pragma once
#include <cstdint>

// GUI state changes restart both history and the sampling sequence.
struct PdfViewerState
{
    bool enabled = true;
    uint32_t frame = 0;
    static bool Supported(bool directReSTIR, bool spatial, bool initialVisibility,
                          bool raytracedCorrection, bool checkerboard)
    {
        return directReSTIR && spatial && initialVisibility && raytracedCorrection && !checkerboard;
    }
    void Update(bool requestedEnabled, bool reset, bool supported = true)
    {
        requestedEnabled &= supported;
        if (requestedEnabled != enabled || reset) frame = 0;
        enabled = requestedEnabled;
    }
    void Advance() { ++frame; }
};
