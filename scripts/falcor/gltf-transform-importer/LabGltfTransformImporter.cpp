// Scene-local transform wrapper. The nested glTF importer retains ownership of its normal material behavior.
#include "Scene/Importer.h"
#include "TransformDescriptor.h"
#include <fstream>
#include <iostream>
#include <stdexcept>

namespace Falcor {
class LabGltfTransformImporter final : public Importer {
public:
    FALCOR_PLUGIN_CLASS(LabGltfTransformImporter, "LabGltfTransformImporter", PluginInfo({"glTF importer with explicit affine root transform", {"labgltf"}}));
    static std::unique_ptr<Importer> create() { return std::make_unique<LabGltfTransformImporter>(); }
    void importScene(const std::filesystem::path& path, SceneBuilder& builder, const std::map<std::string,std::string>& materialNames) override {
        if (!materialNames.empty()) throw std::runtime_error("labgltf does not support material name remapping");
        std::ifstream input(path);
        auto descriptor = LabGltfTransform::parseDescriptor(input);
        auto source = std::filesystem::u8path(descriptor.source);
        if (source.is_relative()) source = path.parent_path() / source;
        source = std::filesystem::weakly_canonical(source);
        if (!std::filesystem::is_regular_file(source)) throw std::runtime_error("labgltf source does not exist");
        const auto start = builder.getNodeCount();
        builder.import(source);
        const auto end = builder.getNodeCount();
        float4x4 transform;
        for (int r=0; r<4; ++r) for (int c=0; c<4; ++c) transform[r][c] = descriptor.matrix[4*r+c];
        uint32_t count = 0;
        for (uint32_t i=start; i<end; ++i) {
            auto& node = builder.getNode(NodeID{i});
            if (node.parent == NodeID::Invalid()) { node.transform = mul(transform, node.transform); ++count; }
        }
        if (!count) throw std::runtime_error("labgltf did not import any root nodes");
        std::cout << "LabGltfTransformImporter: nodes=" << (end-start) << ", transformed roots=" << count << std::endl;
    }
};
extern "C" FALCOR_API_EXPORT void registerPlugin(Falcor::PluginRegistry& registry) {
    registry.registerClass<Importer, LabGltfTransformImporter>();
}
}
