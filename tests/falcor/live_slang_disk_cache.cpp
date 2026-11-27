#include <slang.h>
#include <slang-com-ptr.h>
#include <slang-deprecated.h>

#include <filesystem>
#include <fstream>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <vector>

#include "../../scripts/falcor/live_demo/native/slang_disk_cache.inl"

namespace fs = std::filesystem;
using Slang::ComPtr;

void require(bool ok, const char* message)
{
    if (!ok)
        throw std::runtime_error(message);
}

void writeSource(const fs::path& path, const char* text)
{
    std::ofstream output(path, std::ios::binary);
    output << text;
    require(bool(output), "write shader fixture");
}

struct Run
{
    std::vector<char> code;
    size_t hits;
    size_t written;
    std::vector<std::string> bindings;
    size_t modules;
    bool publicationFailed;
};

Run compileProgram(slang::IGlobalSession* global, const fs::path& cacheDir,
                   const std::vector<std::string>& roots, slang::SessionDesc& desc, const char* entryName,
                   LiveSlangDiskMode mode, bool materialConformance = false, const fs::path& trusted = {})
{
    LiveSlangDiskCache cache(mode, cacheDir, trusted);
    auto session = cache.acquire(global, desc, roots, entryName);
    if (!session)
        require(SLANG_SUCCEEDED(global->createSession(desc, session.writeRef())), "create fallback session");

    SlangCompileRequest* raw = nullptr;
    require(SLANG_SUCCEEDED(session->createCompileRequest(&raw)), "create compile request");
    std::unique_ptr<SlangCompileRequest, decltype(&spDestroyCompileRequest)> request(raw, spDestroyCompileRequest);
    spSetCompileFlags(raw, SLANG_COMPILE_FLAG_NO_CODEGEN);
    int unit = 0;
    for (const auto& root : roots)
    {
        unit = spAddTranslationUnit(raw, SLANG_SOURCE_LANGUAGE_SLANG, nullptr);
        spAddTranslationUnitSourceFile(raw, unit, root.c_str());
    }
    spAddEntryPoint(raw, unit, entryName, SLANG_STAGE_COMPUTE);
    const auto compiled = spCompile(raw);
    require(SLANG_SUCCEEDED(compiled), spGetDiagnosticOutput(raw));

    ComPtr<slang::IComponentType> scope, entry, composite, linked;
    require(SLANG_SUCCEEDED(spCompileRequest_getProgram(raw, scope.writeRef())), "global scope");
    require(SLANG_SUCCEEDED(spCompileRequest_getEntryPoint(raw, 0, entry.writeRef())), "entry point");
    auto* layout = scope->getLayout();
    require(layout != nullptr, "global reflection");
    std::vector<std::string> bindings;
    for (unsigned i = 0; i < layout->getParameterCount(); ++i)
    {
        auto* parameter = layout->getParameterByIndex(i);
        bindings.push_back(std::string(parameter->getName()) + ":" + std::to_string(parameter->getBindingSpace()) +
            ":" + std::to_string(parameter->getBindingIndex()));
    }
    ComPtr<slang::ITypeConformance> conformance;
    std::vector<slang::IComponentType*> parts{scope.get(), entry.get()};
    if (materialConformance)
    {
        auto* impl = layout->findTypeByName("StandardMaterial");
        auto* type = layout->findTypeByName("IMaterial");
        require(impl && type, "material type reflection");
        require(SLANG_SUCCEEDED(session->createTypeConformanceComponentType(impl, type, conformance.writeRef(), 0, nullptr)),
                "material type conformance");
        parts.push_back(conformance.get());
    }
    const auto written = cache.record(session.get());
    require(SLANG_SUCCEEDED(session->createCompositeComponentType(parts.data(), parts.size(), composite.writeRef())), "compose");
    require(SLANG_SUCCEEDED(composite->link(linked.writeRef())), "link");
    ComPtr<ISlangBlob> code;
    require(SLANG_SUCCEEDED(linked->getEntryPointCode(0, 0, code.writeRef())), "generate code");
    auto data = static_cast<const char*>(code->getBufferPointer());
    return {{data, data + code->getBufferSize()}, cache.hitCount(), written, std::move(bindings),
            static_cast<size_t>(session->getLoadedModuleCount()), cache.publicationFailed()};
}

Run compileFixture(slang::IGlobalSession* global, const fs::path& cacheDir,
                   const fs::path& root, const fs::path& include, const char* value, LiveSlangDiskMode mode,
                   const fs::path& trusted = {}, const char* entryName = "run")
{
    const std::string searchPath = include.string();
    const char* paths[] = {searchPath.c_str()};
    const slang::PreprocessorMacroDesc defines[] = {{"VALUE", value}};
    slang::TargetDesc target;
    target.format = SLANG_SPIRV;
    slang::SessionDesc desc;
    desc.searchPaths = paths;
    desc.searchPathCount = 1;
    desc.preprocessorMacros = defines;
    desc.preprocessorMacroCount = 1;
    desc.targets = &target;
    desc.targetCount = 1;
    return compileProgram(global, cacheDir, {root.string()}, desc, entryName, mode, false, trusted);
}

void verifyFalcorMaterialCache(const fs::path& folder, const fs::path& runtime)
{
    const std::string shaderPath = (runtime / "shaders").string();
    const char* paths[] = {shaderPath.c_str()};
    const std::vector<std::string> roots = {
        (runtime / "shaders/Rendering/Materials/StandardMaterial.slang").string(),
        (runtime / "shaders/Scene/Lights/UpdateTriangleVertices.cs.slang").string(),
    };
    // A small indexed scene using the pinned material system's static ArrayMax descriptor bounds.
    constexpr slang::PreprocessorMacroDesc defines[] = {
        {"FALCOR_NVAPI_AVAILABLE", "0"}, {"FALCOR_COOP_VECTOR_AVAILABLE", "0"},
        {"FALCOR_D3D12", "1"}, {"__SM_6_6__", "1"}, {"FALCOR_USE_NVAPI", "0"},
        {"FALCOR_MATERIAL_INSTANCE_SIZE", "256"}, {"MATERIAL_COUNT", "1"},
        {"MATERIAL_TEXTURE_COUNT", "2"}, {"MATERIAL_BUFFER_COUNT", "1"}, {"MATERIAL_SAMPLER_COUNT", "1"},
        {"MATERIAL_SYSTEM_HAS_SPEC_GLOSS_MATERIALS", "0"}, {"MATERIAL_SYSTEM_SAMPLER_DESC_COUNT", "8"},
        {"MATERIAL_SYSTEM_TEXTURE_DESC_COUNT", "8"}, {"MATERIAL_SYSTEM_BUFFER_DESC_COUNT", "1"},
        {"MATERIAL_SYSTEM_TEXTURE_3D_DESC_COUNT", "1"}, {"MATERIAL_SYSTEM_UDIM_INDIRECTION_ENABLED", "0"},
        {"MATERIAL_SYSTEM_USE_LIGHT_PROFILE", "0"}, {"SCENE_GEOMETRY_TYPES", "2"}, {"SCENE_GRID_COUNT", "0"},
        {"SCENE_HAS_INDEXED_VERTICES", "1"}, {"SCENE_HAS_16BIT_INDICES", "0"}, {"SCENE_HAS_32BIT_INDICES", "1"},
        {"SCENE_DIFFUSE_ALBEDO_MULTIPLIER", "1.0"}, {"SCENE_SDF_GRID_COUNT", "0"},
        {"HIT_INFO_DEFINES", "1"}, {"HIT_INFO_USE_COMPRESSION", "0"}, {"HIT_INFO_TYPE_BITS", "3"},
        {"HIT_INFO_INSTANCE_ID_BITS", "22"}, {"HIT_INFO_PRIMITIVE_INDEX_BITS", "16"},
    };
    slang::CompilerOptionEntry options[] = {
        {slang::CompilerOptionName::DisableShortCircuit, {slang::CompilerOptionValueKind::Int, 1, 0, nullptr, nullptr}},
        {slang::CompilerOptionName::DisableWarning, {slang::CompilerOptionValueKind::String, 0, 0, "15602", nullptr}},
        {slang::CompilerOptionName::DisableWarning, {slang::CompilerOptionValueKind::String, 0, 0, "30056", nullptr}},
        {slang::CompilerOptionName::DisableWarning, {slang::CompilerOptionValueKind::String, 0, 0, "30081", nullptr}},
        {slang::CompilerOptionName::DisableWarning, {slang::CompilerOptionValueKind::String, 0, 0, "41203", nullptr}},
    };
    const auto compile = [&](LiveSlangDiskMode mode) {
        ComPtr<slang::IGlobalSession> global;
        require(SLANG_SUCCEEDED(slang::createGlobalSession(global.writeRef())), "create Falcor material global session");
        global->setDownstreamCompilerPath(SLANG_PASS_THROUGH_DXC, runtime.string().c_str());
        slang::TargetDesc target;
        target.format = SLANG_DXIL;
        target.profile = global->findProfile("sm_6_6");
        target.forceGLSLScalarBufferLayout = true;
        slang::SessionDesc desc;
        desc.defaultMatrixLayoutMode = SLANG_MATRIX_LAYOUT_ROW_MAJOR;
        desc.targets = &target;
        desc.targetCount = 1;
        desc.searchPaths = paths;
        desc.searchPathCount = 1;
        desc.preprocessorMacros = defines;
        desc.preprocessorMacroCount = std::size(defines);
        desc.compilerOptionEntries = options;
        desc.compilerOptionEntryCount = std::size(options);
        return compileProgram(global.get(), folder / "falcor-material-cache", roots, desc,
                              "updateTriangleVertices", mode, true);
    };
    const auto cold = compile(LiveSlangDiskMode::Off);
    const auto seed = compile(LiveSlangDiskMode::Write);
    const auto loaded = compile(LiveSlangDiskMode::Read);
    require(seed.written > 0 && seed.written < cold.modules, "cache selected imports and leave incompatible generics in source");
    require(loaded.hits == seed.written && loaded.modules == cold.modules, "load all eligible material imports and recompile missing ones");
    require(loaded.bindings == cold.bindings && loaded.code == cold.code, "preserve material reflection, conformance, and exact DXIL");
}

int main(int argc, char** argv)
try
{
    require(argc == 2 || argc == 3, "supply a disposable fixture directory and optional Falcor runtime");
    const auto folder = fs::absolute(argv[1]);
    const auto left = folder / "left";
    const auto right = folder / "right";
    const auto include = folder / "common";
    const auto cache = folder / "cache";
    fs::create_directories(left);
    fs::create_directories(right);
    fs::create_directories(include);
    constexpr const char* mainSource =
        "import helper; RWStructuredBuffer<uint> result; "
        "[numthreads(1,1,1)] void run(uint3 id: SV_DispatchThreadID) { result[id.x] = helperValue(id.x); }"
        "[numthreads(1,1,1)] void alternate(uint3 id: SV_DispatchThreadID) { result[id.x] = helperValue(id.x) + 3; }";
    writeSource(left / "run.slang", mainSource);
    writeSource(right / "run.slang", mainSource);
    writeSource(include / "helper.slang", "import nested; uint helperValue(uint x) { return nestedValue(x) + VALUE; }");
    writeSource(include / "nested.slang", "#include \"constants.slangh\"\nuint nestedValue(uint x) { return x + OFFSET; }");
    writeSource(include / "constants.slangh", "#define OFFSET 5\n");
    writeSource(right / "helper.slang", "uint helperValue(uint x) { return x + 78; }");

    auto run = [&](LiveSlangDiskMode mode, const fs::path& root = {}, const char* value = "2",
                   const fs::path& stage = {}) {
        ComPtr<slang::IGlobalSession> global;
        require(SLANG_SUCCEEDED(slang::createGlobalSession(global.writeRef())), "create a fresh global session");
        return compileFixture(global.get(), stage.empty() ? cache : stage, (root.empty() ? left : root) / "run.slang", include, value, mode);
    };
    const auto baseline = run(LiveSlangDiskMode::Off);
    require(!baseline.hits && !baseline.written && !fs::exists(cache), "off touches no disk cache");
    const auto empty = run(LiveSlangDiskMode::Read);
    require(empty.code == baseline.code && !empty.hits && !empty.written && !fs::exists(cache), "read miss never creates cache");
    const auto seed = run(LiveSlangDiskMode::Write);
    require(seed.code == baseline.code && seed.written >= 2, "write persists transitive modules");
    const auto launchDirectory = folder / "different-launch";
    fs::create_directory(launchDirectory);
    const auto originalDirectory = fs::current_path();
    fs::current_path(launchDirectory);
    const auto loaded = run(LiveSlangDiskMode::Read);
    fs::current_path(originalDirectory);
    require(loaded.code == baseline.code && loaded.hits >= 2 && !loaded.written, "fresh session uses accepted IR and yields identical SPIR-V");

    const auto repeatedWrite = run(LiveSlangDiskMode::Write);
    require(!repeatedWrite.hits && !repeatedWrite.written && repeatedWrite.code == baseline.code,
            "offline mode does not deserialize its own candidate files");

    const auto blocked = folder / "blocked-cache";
    writeSource(blocked, "an ordinary file");
    ComPtr<slang::IGlobalSession> global;
    require(SLANG_SUCCEEDED(slang::createGlobalSession(global.writeRef())), "create publication failure test session");
    const auto newStage = folder / "new-stage";
    const auto trusted = compileFixture(global.get(), newStage, left / "run.slang", include, "2",
                                        LiveSlangDiskMode::Write, cache);
    require(trusted.hits == seed.written && !trusted.written && !fs::exists(newStage) && trusted.code == baseline.code,
            "offline mode reuses separately trusted packages without writing candidates");
    const auto alternate = compileFixture(global.get(), cache, left / "run.slang", include, "2",
                                          LiveSlangDiskMode::Read, {}, "alternate");
    require(!alternate.hits && alternate.code != baseline.code, "a different entry point needs its own qualification");
    const auto failed = compileFixture(global.get(), blocked, left / "run.slang", include, "2", LiveSlangDiskMode::Write);
    require(failed.code == baseline.code && failed.publicationFailed && !failed.written,
            "report publication failure without changing shader code");

    const auto macro = run(LiveSlangDiskMode::Read, left, "9");
    require(!macro.hits && macro.code != baseline.code, "different preprocessor definitions do not share a pack");

    const auto other = run(LiveSlangDiskMode::Read, right);
    require(!other.hits && other.code != baseline.code, "same-named files in different roots do not share a pack");
    require(run(LiveSlangDiskMode::Write, right).written >= 1, "persist second root");
    const auto loadedOther = run(LiveSlangDiskMode::Read, right);
    require(loadedOther.hits && loadedOther.code == other.code, "second root reads its own module pack");
    require(run(LiveSlangDiskMode::Read).code == baseline.code, "switching back uses the first root's module pack");

    const auto originalTime = fs::last_write_time(include / "constants.slangh");
    writeSource(include / "constants.slangh", "#define OFFSET 7\n");
    fs::last_write_time(include / "constants.slangh", originalTime);
    const auto edited = run(LiveSlangDiskMode::Read);
    require(!edited.hits && edited.code != baseline.code, "same-size transitive include edit with restored mtime invalidates IR");
    const auto editedStage = folder / "edited-stage";
    require(run(LiveSlangDiskMode::Write, left, "2", editedStage).written >= 2, "repopulate after transitive edit");
    writeSource(left / "helper.slang", "uint helperValue(uint x) { return x + 53; }");
    const auto shadowed = run(LiveSlangDiskMode::Read, left, "2", editedStage);
    require(!shadowed.hits && shadowed.code != edited.code, "new higher-priority relative import invalidates IR");

    const auto shadowedStage = folder / "shadowed-stage";
    require(run(LiveSlangDiskMode::Write, left, "2", shadowedStage).written, "repopulate after introducing a shadow");
    for (const auto& pack : fs::directory_iterator(shadowedStage))
        writeSource(pack.path(), "invalid package");
    const auto corrupt = run(LiveSlangDiskMode::Read, left, "2", shadowedStage);
    require(!corrupt.hits && corrupt.code == shadowed.code, "corrupted packs fall back to source compilation");
    const auto freshStage = folder / "fresh-stage";
    require(compileFixture(global.get(), freshStage, left / "run.slang", include, "2", LiveSlangDiskMode::Write).written,
            "a fresh producer creates a replacement candidate");
    require(compileFixture(global.get(), freshStage, left / "run.slang", include, "2", LiveSlangDiskMode::Read).hits,
            "a separate read verifies the candidate before promotion");
    if (argc == 3)
        verifyFalcorMaterialCache(folder, fs::absolute(argv[2]));
    std::cout << "Slang disk IR cache tests passed\n";
    return 0;
}
catch (const std::exception& error)
{
    std::cerr << error.what() << '\n';
    return 1;
}