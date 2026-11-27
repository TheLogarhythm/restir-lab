"""Patch the private Falcor overlay to reuse serialized Slang imports."""

from pathlib import Path


def patch_source(text, replace_once):
    disk_cache = Path(__file__).with_name("slang_disk_cache.inl").read_text(encoding="utf8")
    text = replace_once(
        text, "#include <slang.h>",
        "#include <atomic>\n#include <slang.h>\n#include <slang-com-ptr.h>\n"
        "#include <slang-deprecated.h>\n\n" + disk_cache,
    )
    anchor = "using SlangRequest = "
    native = r"""
LiveSlangDiskMode getLiveSlangDiskMode()
{
    const auto value = getEnvironmentVariable("RESTIR_LIVE_SLANG_CACHE_MODE");
    if (!value || *value == "read")
        return LiveSlangDiskMode::Read;
    return *value == "write" ? LiveSlangDiskMode::Write : LiveSlangDiskMode::Off;
}

std::filesystem::path getLiveSlangDiskDirectory()
{
    const auto value = getEnvironmentVariable("RESTIR_LIVE_SLANG_CACHE_DIR");
    return value ? std::filesystem::path(*value) : getRuntimeDirectory() / ".slangcache";
}

std::filesystem::path getLiveSlangTrustedDirectory()
{
    const auto value = getEnvironmentVariable("RESTIR_LIVE_SLANG_CACHE_TRUSTED_DIR");
    return value ? std::filesystem::path(*value) : std::filesystem::path{};
}

void reportLiveSlangReadAttempt(const std::filesystem::path& path)
{
    static const bool qualifying = getEnvironmentVariable("RESTIR_LIVE_SLANG_CACHE_QUALIFY") == "1";
    if (qualifying)
        logInfo("Live Slang cache: attempt {}", path.stem().string());
}

std::string getLiveSlangProgramSignature(const ProgramDesc& desc, const TypeConformanceList& conformances,
                                        SlangCompilerFlags flags)
{
    using live_slang_disk::appendField;
    using live_slang_disk::appendNumber;
    std::string signature;
    const auto appendConformances = [&](const TypeConformanceList& list) {
        appendNumber(signature, static_cast<uint32_t>(list.size()));
        for (const auto& [conformance, id] : list)
        {
            appendField(signature, conformance.typeName);
            appendField(signature, conformance.interfaceName);
            appendNumber(signature, id);
        }
    };

    appendNumber(signature, static_cast<uint32_t>(flags));
    appendConformances(conformances);
    appendNumber(signature, static_cast<uint32_t>(desc.entryPointGroups.size()));
    for (const auto& group : desc.entryPointGroups)
    {
        appendNumber(signature, group.shaderModuleIndex);
        appendConformances(group.typeConformances);
        appendNumber(signature, static_cast<uint32_t>(group.entryPoints.size()));
        for (const auto& entry : group.entryPoints)
        {
            appendField(signature, entry.name);
            appendField(signature, entry.exportName);
            appendNumber(signature, static_cast<uint32_t>(entry.type));
        }
    }
    return signature;
}

thread_local LiveSlangDiskCache* gLiveSlangDiskAttempt = nullptr;

struct ScopedLiveSlangDiskAttempt
{
    explicit ScopedLiveSlangDiskAttempt(LiveSlangDiskCache& cache)
        : previous(std::exchange(gLiveSlangDiskAttempt, &cache))
    {}
    ~ScopedLiveSlangDiskAttempt() { gLiveSlangDiskAttempt = previous; }

    LiveSlangDiskCache* previous;
};

std::atomic<uint64_t> gLiveSlangGeneration{0};

struct LiveSlangCache
{
    struct Entry
    {
        std::string key;
        std::vector<std::string> roots;
        Slang::ComPtr<slang::ISession> session;
    };
    Slang::ComPtr<slang::IGlobalSession> owner;
    std::vector<Entry> entries;
    uint64_t generation = 0;

    void clear()
    {
        entries.clear();
        owner.setNull();
    }

    Slang::ComPtr<slang::ISession> acquire(
        slang::IGlobalSession* global, slang::SessionDesc& desc, std::vector<std::string> roots)
    {
        const auto currentGeneration = gLiveSlangGeneration.load();
        if (owner.get() != global || generation != currentGeneration)
        {
            clear();
            owner = global;
            generation = currentGeneration;
        }

        Slang::ComPtr<ISlangBlob> digest;
        if (SLANG_FAILED(global->getSessionDescDigest(&desc, digest.writeRef())) || !digest)
            return {};
        std::string key(static_cast<const char*>(digest->getBufferPointer()), digest->getBufferSize());
        // Slang resolves relative imports by module name within one session. The same
        // import in a different source tree can refer to an entirely different file.
        auto it = std::find_if(entries.begin(), entries.end(), [&](const Entry& entry) {
            return entry.key == key && entry.roots == roots;
        });
        if (it != entries.end())
        {
            std::rotate(it, it + 1, entries.end());
            return entries.back().session;
        }

        Slang::ComPtr<slang::ISession> session;
        if (SLANG_SUCCEEDED(global->createSession(desc, session.writeRef())) && session)
        {
            // Released ProgramVersions can leave large scene imports behind. Bound retention on the demo GPU host.
            if (entries.size() == 4)
                entries.erase(entries.begin());
            entries.push_back({std::move(key), std::move(roots), session});
        }
        return session;
    }
};

thread_local LiveSlangCache gLiveSlangCache;

"""
    text = replace_once(text, anchor, native + anchor)
    anchor = "    SlangRequest requestOwner(createSlangCompileRequest(program), spDestroyCompileRequest);"
    text = replace_once(text, anchor, r"""    LiveSlangDiskCache diskCache(
        getLiveSlangDiskMode(), getLiveSlangDiskDirectory(), getLiveSlangTrustedDirectory(), reportLiveSlangReadAttempt
    );
    auto createRequest = [&]() {
        ScopedLiveSlangDiskAttempt scope(diskCache);
        return createSlangCompileRequest(program);
    };
    SlangRequest requestOwner(createRequest(), spDestroyCompileRequest);""")
    anchor = "    SlangResult slangResult = spCompile(pSlangRequest);"
    text = replace_once(text, anchor, anchor + r"""
    if (SLANG_FAILED(slangResult) && diskCache.modifiedSession())
    {
        // A partially restored session cannot be repurposed for a source retry.
        diskCache.useFreshSource();
        requestOwner.reset(createRequest());
        pSlangRequest = requestOwner.get();
        if (!pSlangRequest)
            return nullptr;
        slangResult = spCompile(pSlangRequest);
    }""")
    anchor = "    timer.update();\n    double time = timer.delta();\n    mCompilationStats.programVersionCount++;"
    text = replace_once(text, anchor, anchor + r"""
    const auto written = diskCache.record(pSlangSession.get());
    if (diskCache.hitCount())
        logInfo("Live Slang cache: hit {} modules {}", diskCache.hitCount(), diskCache.path().stem().string());
    else if (written)
        logInfo("Live Slang cache: write {} modules {}", written, diskCache.path().stem().string());
    else if (diskCache.publicationFailed())
        logWarning("Live Slang cache: write failed {}", diskCache.path().string());
    else if (diskCache.attempted())
        logInfo("Live Slang cache: miss {}", diskCache.path().stem().string());""")
    anchor = "    std::vector<const char*> slangSearchPaths;"
    text = replace_once(text, anchor, "    searchPaths.reserve(getShaderDirectoriesList().size());\n" + anchor)
    anchor = "    pSlangGlobalSession->createSession(sessionDesc, pSlangSession.writeRef());"
    text = replace_once(text, anchor, r"""    const auto& modules = program.mDesc.shaderModules;
    bool shareImports = mGlobalCompilerArguments.empty() && program.mDesc.compilerArguments.empty() &&
        !mGenerateDebugInfo && !is_set(compilerFlags, SlangCompilerFlags::GenerateDebugInfo) &&
        !is_set(compilerFlags, SlangCompilerFlags::DumpIntermediates) &&
        std::all_of(modules.begin(), modules.end(), [](const auto& module) {
            return module.name.empty() && module.sources.size() == 1 &&
                module.sources.front().type == ProgramDesc::ShaderSource::Type::File;
        });
    if (shareImports)
    {
        std::vector<std::string> roots;
        for (const auto& module : modules)
        {
            std::filesystem::path resolved;
            if (!findFileInShaderDirectories(module.sources.front().path, resolved))
            {
                roots.clear();
                break;
            }
            roots.push_back(resolved.string());
        }
        if (gLiveSlangDiskAttempt)
        {
            const auto signature = getLiveSlangProgramSignature(program.mDesc, program.getTypeConformances(), compilerFlags);
            pSlangSession = gLiveSlangDiskAttempt->acquire(pSlangGlobalSession, sessionDesc, roots, signature);
        }
        if (!pSlangSession && !roots.empty() && (!gLiveSlangDiskAttempt || gLiveSlangDiskAttempt->allowInMemoryFallback()))
            pSlangSession = gLiveSlangCache.acquire(pSlangGlobalSession, sessionDesc, std::move(roots));
    }
    if (!pSlangSession)
        pSlangGlobalSession->createSession(sessionDesc, pSlangSession.writeRef());""")
    for anchor in (
        "    bool hasReloaded = false;",
        "    mpDevice->getSlangGlobalSession()->setLanguagePrelude(",
    ):
        text = replace_once(text, anchor, "    ++gLiveSlangGeneration;\n    gLiveSlangCache.clear();\n" + anchor)
    anchor = "    mLoadedPrograms.erase(std::remove(mLoadedPrograms.begin(), mLoadedPrograms.end(), program), mLoadedPrograms.end());"
    return replace_once(text, anchor, anchor + """
    if (mLoadedPrograms.empty() && gLiveSlangCache.owner.get() == mpDevice->getSlangGlobalSession())
        gLiveSlangCache.clear();""")
