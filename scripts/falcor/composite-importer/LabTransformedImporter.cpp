// Lab-owned feasibility prototype; requires Falcor 9.0 matching the pinned ABI.
#include "Scene/Importer.h"
#include "Utils/Math/MatrixMath.h"
#include <cmath>
#include <fstream>
#include <iostream>
#include <stdexcept>

namespace Falcor {
class LabTransformedImporter final : public Importer {
public:
    FALCOR_PLUGIN_CLASS(LabTransformedImporter, "LabTransformedImporter", PluginInfo({"Lab FBX importer with explicit root transform", {"labfbx"}}));
    static std::unique_ptr<Importer> create() { return std::make_unique<LabTransformedImporter>(); }
    void importScene(const std::filesystem::path& path, SceneBuilder& builder, const std::map<std::string,std::string>&) override {
        std::ifstream input(path);
        std::string source;
        float scale, x, y, z;
        if (!std::getline(input, source) || !(input >> scale >> x >> y >> z))
            throw std::runtime_error("Invalid labfbx: expected path and scale, x, y, z");
        if (!source.empty() && source.back() == '\r') source.pop_back();
        auto sourcePath = std::filesystem::path(source);
        if (sourcePath.is_relative()) sourcePath = path.parent_path() / sourcePath;
        sourcePath = std::filesystem::weakly_canonical(sourcePath);
        if (sourcePath.extension() != ".fbx" || !std::filesystem::is_regular_file(sourcePath))
            throw std::runtime_error("labfbx source must be an existing .fbx path");
        if (!(scale > 0.f) || !std::isfinite(scale) || !std::isfinite(x) || !std::isfinite(y) || !std::isfinite(z))
            throw std::runtime_error("Invalid labfbx transform");
        const auto start = builder.getNodeCount();
        builder.import(sourcePath);
        const auto end = builder.getNodeCount();
        const float4x4 transform = mul(math::matrixFromTranslation(float3(x,y,z)), math::matrixFromScaling(float3(scale)));
        uint32_t transformed = 0;
        for (uint32_t i = start; i < end; ++i) {
            auto& node = builder.getNode(NodeID{i});
            if (node.parent == NodeID::Invalid()) {
                node.transform = mul(transform, node.transform);
                ++transformed;
            }
        }
        if (!transformed) throw std::runtime_error("No new root nodes in labfbx");
        std::cout << "LabTransformedImporter: imported nodes=" << (end-start) << ", transformed roots=" << transformed << std::endl;
    }
};
extern "C" FALCOR_API_EXPORT void registerPlugin(Falcor::PluginRegistry& registry) {
    registry.registerClass<Importer, LabTransformedImporter>();
}
}
