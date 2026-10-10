// Execute the exact ConfigurePdf emitted by the adapter with the pinned JSON parser.
#include <cassert>
#include <stdexcept>
#include "jsoncpp.cpp"
#include "PdfViewerState.h"

enum class ReSTIRDI_SpatialBiasCorrectionMode { Raytraced };
namespace rtxdi {
enum class ReSTIRDI_ResamplingMode { Spatial, TemporalAndSpatial };
enum class CheckerboardMode { Off };
struct Spatial {
    ReSTIRDI_SpatialBiasCorrectionMode biasCorrectionMode = ReSTIRDI_SpatialBiasCorrectionMode::Raytraced;
    unsigned pad1 = 99, pad2 = 99;
};
struct ReSTIRDIContext {
    Spatial spatial;
    ReSTIRDI_ResamplingMode GetResamplingMode() const { return ReSTIRDI_ResamplingMode::TemporalAndSpatial; }
    Spatial GetSpatialResamplingParameters() const { return spatial; }
    struct Initial { bool enableInitialVisibility = true; };
    Initial GetInitialSamplingParameters() const { return {}; }
    struct Static { CheckerboardMode CheckerboardSamplingMode = CheckerboardMode::Off; };
    Static GetStaticParameters() const { return {}; }
    void SetSpatialResamplingParameters(Spatial value) { spatial = value; }
};
}
struct Experiment {
    Json::Value config;
    PdfViewerState m_pdfViewer;
    bool viewer = false;
    bool IsViewer() const { return viewer; }
#include "pdf_config_under_test.h"
};

static bool configure(const char* mode, bool enabled, unsigned expected)
{
    Experiment lab;
    Json::Reader reader;
    assert(reader.parse(std::string("{\"definition\":{\"pdf_similarity\":") +
        (enabled ? "true" : "false") + (mode ? ",\"pdf_history_mode\":" + std::string(mode) : "") + "}}", lab.config));
    rtxdi::ReSTIRDIContext di;
    try { lab.ConfigurePdf(di); }
    catch (const std::exception&) { return false; }
    assert(di.spatial.pad1 == unsigned(enabled));
    assert(di.spatial.pad2 == expected);
    return true;
}
int main()
{
    assert(configure(nullptr, true, 0));
    assert(configure(nullptr, false, 0));
    assert(configure("0", true, 0));
    assert(configure("1", true, 1));
    assert(configure("2", true, 2));
    for (const char* invalid : {"null", "true", "false", "2.0", "2.9", "-0.5", "-1", "3", "4294967295", "\"2\"", "[]", "{}"})
        assert(!configure(invalid, true, 99));
    assert(!configure("1", false, 99));
    assert(!configure("2", false, 99));
}