// A marker for glTF multiplicative texture factors. Paired shader patch required.
#include "Core/Plugin.h"
#include "GlobalState.h"
#include "Scene/SceneBuilder.h"
#include "Scene/Material/StandardMaterial.h"
#include "Utils/Scripting/ScriptBindings.h"

namespace Falcor {
static_assert(BasicMaterialData::kTotalFlagsBits == 20, "Review glTF material flag reservation for this Falcor version");
constexpr uint32_t kGltfFactorFlag = 1u << 20;

class GltfFactorMaterial : public StandardMaterial
{
public:
    GltfFactorMaterial(ref<Device> device, const std::string& name, ShadingModel model)
        : StandardMaterial(device, name, model)
    {
        mData.flags |= kGltfFactorFlag;
    }
    // A constant texture cannot replace its multiplicative material factor.
    void optimizeTexture(TextureSlot, const TextureAnalyzer::Result&, TextureOptimizationStats&) override {}
    bool hasGltfFactorMarker() const { return (mData.flags & kGltfFactorFlag) != 0; }
};

extern "C" FALCOR_API_EXPORT void registerPlugin(PluginRegistry&)
{
    ScriptBindings::registerBinding([](pybind11::module& m) {
        using namespace pybind11::literals;
        ScriptBindings::resolveDeferredBinding("StandardMaterial", m);
        pybind11::class_<GltfFactorMaterial, StandardMaterial, ref<GltfFactorMaterial>> cls(m, "GltfFactorMaterial");
        cls.def(pybind11::init([](const std::string& name, ShadingModel model) {
            return make_ref<GltfFactorMaterial>(accessActivePythonSceneBuilder().getDevice(), name, model);
        }), "name"_a = "", "model"_a = ShadingModel::MetalRough);
        cls.def_property_readonly("gltfFactorMarker", &GltfFactorMaterial::hasGltfFactorMarker);
    });
}
} // namespace Falcor
