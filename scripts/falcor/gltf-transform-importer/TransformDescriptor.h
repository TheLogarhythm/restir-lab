#pragma once
#include <algorithm>
#include <array>
#include <cctype>
#include <cmath>
#include <filesystem>
#include <istream>
#include <stdexcept>
#include <string>

namespace LabGltfTransform {
struct Descriptor { std::string source; std::array<float, 16> matrix; };
inline Descriptor parseDescriptor(std::istream& input) {
    Descriptor d;
    if (!std::getline(input, d.source)) throw std::runtime_error("Missing glTF source");
    if (!d.source.empty() && d.source.back() == '\r') d.source.pop_back();
    if (d.source.empty() || d.source.find('\0') != std::string::npos) throw std::runtime_error("Invalid glTF source");
    auto ext = std::filesystem::u8path(d.source).extension().string();
    std::transform(ext.begin(), ext.end(), ext.begin(), [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    if (ext != ".gltf" && ext != ".glb") throw std::runtime_error("Expected .gltf or .glb source");
    for (auto& value : d.matrix)
        if (!(input >> value) || !std::isfinite(value)) throw std::runtime_error("Expected 16 finite matrix values");
    std::string extra;
    if (input >> extra) throw std::runtime_error("Unexpected descriptor content");
    if (d.matrix[12] != 0 || d.matrix[13] != 0 || d.matrix[14] != 0 || d.matrix[15] != 1)
        throw std::runtime_error("Expected an affine matrix, row-major");
    const auto& m = d.matrix;
    const double det = double(m[0])*(double(m[5])*m[10]-double(m[6])*m[9])
                     - double(m[1])*(double(m[4])*m[10]-double(m[6])*m[8])
                     + double(m[2])*(double(m[4])*m[9]-double(m[5])*m[8]);
    if (std::abs(det) <= 1e-12) throw std::runtime_error("Singular or near-singular transform");
    return d;
}
}
