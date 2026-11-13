#include "../../scripts/falcor/gltf-transform-importer/TransformDescriptor.h"
#include <cassert>
#include <cmath>
#include <sstream>
#include <stdexcept>
#include <string>

using LabGltfTransform::parseDescriptor;

static bool rejects(const std::string& text) {
    try { std::istringstream stream(text); (void)parseDescriptor(stream); return false; }
    catch (const std::exception&) { return true; }
}

int main() {
    std::istringstream valid("folder with spaces/model.gltf\n0 -2 0 3  2 0 0 4  0 0 -2 5  0 0 0 1\n");
    auto d = parseDescriptor(valid);
    assert(d.source == "folder with spaces/model.gltf");
    assert(d.matrix[0] == 0 && d.matrix[1] == -2 && d.matrix[3] == 3);
    assert(d.matrix[4] == 2 && d.matrix[7] == 4 && d.matrix[10] == -2 && d.matrix[11] == 5);
    assert(!rejects("model.GLB\n1 0 0 0  0 1 0 0  0 0 1 0  0 0 0 1\n"));
    assert(rejects("model.fbx\n1 0 0 0  0 1 0 0  0 0 1 0  0 0 0 1\n"));
    assert(rejects("model.gltf\n1 0 0 0  0 1 0 0  0 0 0 0  0 0 0 1\n"));
    assert(rejects("model.gltf\n1 0 0 0  0 1 0 0  0 0 1 0  0 0 1 1\n"));
    assert(rejects("model.gltf\n1 0 0 0  0 1 0 0  0 0 1 0  0 0 0 1 extra\n"));
    assert(rejects("model.gltf\n1 0 0 0  0 1 0 0  0 0 1 0\n"));
    assert(rejects("model.gltf\n1 0 0 0  0 1 0 0  0 0 nan 0  0 0 0 1\n"));
}
