#include <Windows.h>
#include <bcrypt.h>

#include <algorithm>
#include <array>
#include <atomic>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <map>
#include <set>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>
#include <utility>

#pragma comment(lib, "bcrypt.lib")

namespace live_slang_disk
{
namespace fs = std::filesystem;
using Slang::ComPtr;

constexpr size_t kMaxPackBytes = 128 * 1024 * 1024;
constexpr uint32_t kMaxRecords = 65536;
constexpr char kFormat[] = "Falcor live Slang IR v4";

bool sameGuid(const SlangUUID& lhs, const SlangUUID& rhs)
{
    return std::memcmp(&lhs, &rhs, sizeof(lhs)) == 0;
}

template<typename Interface>
class Object : public Interface
{
public:
    uint32_t SLANG_MCALL addRef() override { return ++mRefs; }
    uint32_t SLANG_MCALL release() override
    {
        const auto refs = --mRefs;
        if (refs == 0)
            delete this;
        return refs;
    }

    SlangResult SLANG_MCALL queryInterface(const SlangUUID& guid, void** value) override
    {
        *value = interfaceFor(guid);
        if (!*value)
            return SLANG_E_NO_INTERFACE;
        addRef();
        return SLANG_OK;
    }

protected:
    virtual ~Object() = default;

    virtual void* interfaceFor(const SlangUUID& guid)
    {
        return sameGuid(guid, Interface::getTypeGuid()) || sameGuid(guid, ISlangUnknown::getTypeGuid())
            ? static_cast<Interface*>(this) : nullptr;
    }

private:
    std::atomic<uint32_t> mRefs{1};
};

class Blob final : public Object<ISlangBlob>
{
public:
    explicit Blob(std::string bytes) : mBytes(std::move(bytes)) {}
    const void* SLANG_MCALL getBufferPointer() override { return mBytes.data(); }
    size_t SLANG_MCALL getBufferSize() override { return mBytes.size(); }

private:
    std::string mBytes;
};

std::string_view blobBytes(ISlangBlob* blob)
{
    return {static_cast<const char*>(blob->getBufferPointer()), blob->getBufferSize()};
}

std::string digest(std::string_view data)
{
    struct Algorithm
    {
        BCRYPT_ALG_HANDLE handle = nullptr;
        Algorithm() { BCryptOpenAlgorithmProvider(&handle, BCRYPT_SHA256_ALGORITHM, nullptr, 0); }
        ~Algorithm() { if (handle) BCryptCloseAlgorithmProvider(handle, 0); }
    };
    static const Algorithm algorithm;
    std::array<unsigned char, 32> bytes{};
    if (!algorithm.handle || BCryptHash(algorithm.handle, nullptr, 0,
        reinterpret_cast<PUCHAR>(const_cast<char*>(data.data())), static_cast<ULONG>(data.size()),
        bytes.data(), static_cast<ULONG>(bytes.size())) != 0)
        throw std::runtime_error("Cannot hash Slang cache data");
    return {reinterpret_cast<const char*>(bytes.data()), bytes.size()};
}

std::string hex(std::string_view value)
{
    std::string result;
    for (unsigned char byte : value)
    {
        constexpr char digits[] = "0123456789abcdef";
        result.push_back(digits[byte >> 4]);
        result.push_back(digits[byte & 15]);
    }
    return result;
}

std::string readFile(const fs::path& path)
{
    std::ifstream stream(path, std::ios::binary | std::ios::ate);
    const std::streamoff size = stream.tellg();
    if (size < 0 || size > static_cast<std::streamoff>(kMaxPackBytes))
        throw std::runtime_error("Cannot read Slang cache file");
    std::string bytes(static_cast<size_t>(size), '\0');
    if (!stream.seekg(0) || !stream.read(bytes.data(), static_cast<std::streamsize>(bytes.size())) ||
        stream.peek() != std::char_traits<char>::eof())
        throw std::runtime_error("Cannot read Slang cache file");
    return bytes;
}

fs::path utf8Path(std::string_view path)
{
    return fs::u8path(path.begin(), path.end());
}

std::string pathString(const fs::path& path)
{
    const auto bytes = path.generic_u8string();
    return {bytes.begin(), bytes.end()};
}

enum class FileKind : uint8_t { Missing, File, Directory };

struct FileRecord
{
    FileKind kind;
    std::string identity;
    std::string content;
};

FileRecord inspectPath(const fs::path& path)
{
    std::error_code error;
    const auto state = fs::status(path, error);
    if (state.type() == fs::file_type::not_found &&
        (!error || error == std::errc::no_such_file_or_directory || error == std::errc::not_a_directory))
        return {FileKind::Missing, {}, {}};
    if (!error && fs::is_regular_file(state))
        return {FileKind::File, pathString(fs::canonical(path)), {}};
    if (!error && fs::is_directory(state))
        return {FileKind::Directory, pathString(fs::canonical(path)), {}};
    throw std::runtime_error("Unknown Slang shader path status");
}

using FileRecords = std::map<std::string, FileRecord>;

bool matches(const std::string& name, const FileRecord& record)
{
    const auto path = utf8Path(name);
    const auto actual = inspectPath(path);
    return actual.kind == record.kind && actual.identity == record.identity &&
        (record.content.empty() || digest(readFile(path)) == record.content);
}

// Capture the paths Slang actually asks about, including unsuccessful search attempts.
// A new higher-priority include or import can otherwise keep all recorded files unchanged.
class TrackingFileSystem final : public Object<ISlangFileSystemExt>
{
public:
    FileRecords records;
    bool valid = true;

    SlangResult SLANG_MCALL loadFile(const char* name, ISlangBlob** output) override
    {
        *output = nullptr;
        try
        {
            auto& record = observe(name);
            if (record.kind != FileKind::File)
                return SLANG_E_NOT_FOUND;
            auto data = readFile(utf8Path(name));
            auto hash = digest(data);
            if (!record.content.empty() && record.content != hash)
                valid = false;
            record.content = std::move(hash);
            *output = new Blob(std::move(data));
            return SLANG_OK;
        }
        catch (const std::exception&) { valid = false; return SLANG_FAIL; }
    }

    SlangResult SLANG_MCALL getFileUniqueIdentity(const char* name, ISlangBlob** output) override
    {
        *output = nullptr;
        try
        {
            const auto& record = observe(name);
            if (record.kind == FileKind::Missing)
                return SLANG_E_NOT_FOUND;
            return outputPath(record.identity, output);
        }
        catch (const std::exception&) { valid = false; return SLANG_FAIL; }
    }

    SlangResult SLANG_MCALL calcCombinedPath(
        SlangPathType type, const char* relativeTo, const char* name, ISlangBlob** output) override
    {
        *output = nullptr;
        try
        {
            const auto base = utf8Path(relativeTo);
            return outputPath(pathString((type == SLANG_PATH_TYPE_FILE ? base.parent_path() : base) / utf8Path(name)), output);
        }
        catch (const std::exception&) { valid = false; return SLANG_FAIL; }
    }

    SlangResult SLANG_MCALL getPathType(const char* name, SlangPathType* type) override
    {
        try
        {
            switch (observe(name).kind)
            {
            case FileKind::File: *type = SLANG_PATH_TYPE_FILE; return SLANG_OK;
            case FileKind::Directory: *type = SLANG_PATH_TYPE_DIRECTORY; return SLANG_OK;
            case FileKind::Missing: return SLANG_E_NOT_FOUND;
            }
        }
        catch (const std::exception&) { valid = false; }
        return SLANG_FAIL;
    }

    SlangResult SLANG_MCALL getPath(PathKind kind, const char* name, ISlangBlob** output) override
    {
        *output = nullptr;
        try
        {
            switch (kind)
            {
            case PathKind::Simplified: return outputPath(pathString(utf8Path(name).lexically_normal()), output);
            case PathKind::Canonical: return getFileUniqueIdentity(name, output);
            case PathKind::Display:
            case PathKind::OperatingSystem: return outputPath(name, output);
            default: return SLANG_E_NOT_IMPLEMENTED;
            }
        }
        catch (const std::exception&) { valid = false; return SLANG_FAIL; }
    }

    void SLANG_MCALL clearCache() override {}
    OSPathKind SLANG_MCALL getOSPathKind() override { return OSPathKind::Direct; }
    SlangResult SLANG_MCALL enumeratePathContents(const char*, FileSystemContentsCallBack, void*) override
    {
        valid = false;
        return SLANG_E_NOT_IMPLEMENTED;
    }

    void* SLANG_MCALL castAs(const SlangUUID& guid) override { return interfaceFor(guid); }

protected:
    void* interfaceFor(const SlangUUID& guid) override
    {
        if (sameGuid(guid, ISlangFileSystem::getTypeGuid()) || sameGuid(guid, ISlangCastable::getTypeGuid()))
            return static_cast<ISlangFileSystemExt*>(this);
        return Object::interfaceFor(guid);
    }

private:
    FileRecord& observe(const char* name)
    {
        // Preserve relative lookups so a later launch can validate them against its own working directory.
        const auto path = utf8Path(name);
        const auto key = pathString(path);
        const auto found = records.find(key);
        if (found != records.end())
            return found->second;
        return records.emplace(key, inspectPath(path)).first->second;
    }

    static SlangResult outputPath(std::string path, ISlangBlob** output)
    {
        path.push_back('\0');
        *output = new Blob(std::move(path));
        return SLANG_OK;
    }
};

void appendNumber(std::string& result, uint32_t value)
{
    result.append(reinterpret_cast<const char*>(&value), sizeof(value));
}

void appendField(std::string& result, std::string_view value)
{
    if (value.size() > kMaxPackBytes || result.size() + value.size() + sizeof(uint32_t) > kMaxPackBytes)
        throw std::runtime_error("Slang IR package exceeded size limit");
    appendNumber(result, static_cast<uint32_t>(value.size()));
    result.append(value);
}

class PackReader
{
public:
    explicit PackReader(std::string_view remaining) : mRemaining(remaining) {}

    uint32_t number()
    {
        uint32_t value;
        const auto bytes = take(sizeof(value));
        std::memcpy(&value, bytes.data(), sizeof(value));
        return value;
    }

    std::string_view field() { return take(number()); }
    bool empty() const { return mRemaining.empty(); }

private:
    std::string_view take(size_t size)
    {
        if (size > mRemaining.size())
            throw std::runtime_error("Truncated Slang IR package");
        const auto value = mRemaining.substr(0, size);
        mRemaining.remove_prefix(size);
        return value;
    }

    std::string_view mRemaining;
};

bool publish(const fs::path& destination, std::string_view contents)
{
    static std::atomic<uint64_t> counter{0};
    auto temporary = destination;
    temporary += "." + std::to_string(GetCurrentProcessId()) + "." + std::to_string(GetTickCount64()) +
        "." + std::to_string(++counter) + ".tmp";
    fs::create_directories(destination.parent_path());
    std::ofstream stream(temporary, std::ios::binary | std::ios::trunc);
    stream.write(contents.data(), static_cast<std::streamsize>(contents.size()));
    stream.close();
    const bool moved = stream && MoveFileExW(temporary.c_str(), destination.c_str(),
        MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH);
    if (!moved)
    {
        std::error_code error;
        fs::remove(temporary, error);
    }
    return moved;
}
} // namespace live_slang_disk

enum class LiveSlangDiskMode { Off, Read, Write };

class LiveSlangDiskCache
{
public:
    using ReadAttempt = void (*)(const std::filesystem::path&);

    LiveSlangDiskCache(LiveSlangDiskMode mode, std::filesystem::path directory,
                       std::filesystem::path trustedDirectory = {}, ReadAttempt readAttempt = nullptr)
        : mMode(mode), mDirectory(std::move(directory)), mTrustedDirectory(std::move(trustedDirectory)),
          mReadAttempt(readAttempt)
    {}

    Slang::ComPtr<slang::ISession> acquire(
        slang::IGlobalSession* global, slang::SessionDesc& desc, const std::vector<std::string>& roots,
        std::string_view programSignature = {})
    {
        using namespace live_slang_disk;
        if (!global || mForceSource || mMode == LiveSlangDiskMode::Off || !mDirectory.is_absolute() || roots.empty())
            return {};

        try
        {
            ComPtr<ISlangBlob> sessionDigest, prelude;
            if (SLANG_FAILED(global->getSessionDescDigest(&desc, sessionDigest.writeRef())) || !sessionDigest)
                return {};
            global->getLanguagePrelude(SLANG_SOURCE_LANGUAGE_HLSL, prelude.writeRef());
            appendField(mKey, kFormat);
            appendField(mKey, global->getBuildTagString());
            appendField(mKey, blobBytes(sessionDigest));
            appendField(mKey, programSignature);
            appendField(mKey, prelude ? blobBytes(prelude) : std::string_view{});
            for (const auto& root : roots)
                appendField(mKey, pathString(fs::canonical(utf8Path(root))));
            const auto filename = hex(digest(mKey)) + ".irpack";
            mPath = mDirectory / filename;
            if (mMode == LiveSlangDiskMode::Read || mTrustedDirectory.is_absolute())
            {
                const auto readPath = mMode == LiveSlangDiskMode::Read ? mPath : mTrustedDirectory / filename;
                if (auto session = restore(global, desc, readPath))
                    return session;
            }

            if (mMode == LiveSlangDiskMode::Write)
            {
                // A candidate is never deserialized in its producer. Duplicate variants
                // within the same render can still use the ordinary source session.
                std::error_code error;
                if (fs::is_regular_file(mPath, error))
                {
                    mExistingCandidate = true;
                    return {};
                }
                mTracking.attach(new TrackingFileSystem);
                auto trackingDesc = desc;
                trackingDesc.fileSystem = mTracking.get();
                ComPtr<slang::ISession> session;
                if (SLANG_SUCCEEDED(global->createSession(trackingDesc, session.writeRef())))
                    return session;
                mTracking.setNull();
            }
        }
        catch (const std::exception&) {}
        return {};
    }

    size_t hitCount() const { return mHits; }
    bool attempted() const { return !mPath.empty(); }
    bool modifiedSession() const { return mHits || mTracking; }
    bool publicationFailed() const { return mPublicationFailed; }
    bool allowInMemoryFallback() const
    {
        if (mForceSource)
            return false;
        if (mMode == LiveSlangDiskMode::Off || mPath.empty() || mExistingCandidate)
            return true;
        std::error_code error;
        return !std::filesystem::exists(mPath, error) && !error;
    }

    void useFreshSource()
    {
        mForceSource = true;
        mTracking.setNull();
        mHits = 0;
    }
    const std::filesystem::path& path() const { return mPath; }

    size_t record(slang::ISession* session)
    {
        using namespace live_slang_disk;
        if (!mTracking || !mTracking->valid || mTracking->records.empty() || !session)
            return 0;
        const auto moduleCount = session->getLoadedModuleCount();
        if (moduleCount < 1 || moduleCount > kMaxRecords || mTracking->records.size() > kMaxRecords)
            return 0;
        try
        {
            std::string payload;
            appendField(payload, mKey);
            appendNumber(payload, static_cast<uint32_t>(mTracking->records.size()));
            for (const auto& [path, file] : mTracking->records)
            {
                if (!matches(path, file))
                    return 0;
                appendField(payload, path);
                appendNumber(payload, static_cast<uint32_t>(file.kind));
                appendField(payload, file.identity);
                appendField(payload, file.content);
            }

            std::vector<slang::IModule*> modules;
            std::set<std::filesystem::path> sourceOnly;
            for (SlangInt index = 0; index < moduleCount; ++index)
            {
                auto* module = session->getLoadedModule(index);
                if (!module || !module->getFilePath())
                    return 0;
                if (requiresSource(module->getModuleReflection(), false, false))
                    sourceOnly.insert(fs::canonical(utf8Path(module->getFilePath())));
                modules.push_back(module);
            }
            modules.erase(std::remove_if(modules.begin(), modules.end(), [&](auto* module) {
                return dependsOnSourceOnly(module, sourceOnly);
            }), modules.end());
            if (modules.empty())
                return 0;
            appendNumber(payload, static_cast<uint32_t>(modules.size()));
            std::set<std::string> names;
            for (auto* module : modules)
            {
                if (!module->getName() || !module->getFilePath() || !names.insert(module->getName()).second)
                    return 0;
                const auto shaderPath = utf8Path(module->getFilePath());
                const auto found = mTracking->records.find(pathString(shaderPath));
                if (found == mTracking->records.end() || found->second.content.empty())
                    return 0;
                ComPtr<ISlangBlob> blob;
                if (SLANG_FAILED(module->serialize(blob.writeRef())) || !blob)
                    return 0;
                appendField(payload, module->getName());
                appendField(payload, pathString(fs::absolute(shaderPath)));
                appendField(payload, blobBytes(blob));
            }
            if (payload.size() + 32 > kMaxPackBytes)
                return 0;
            payload.append(digest(payload));
            mPublicationFailed = true;
            if (publish(mPath, payload))
            {
                mPublicationFailed = false;
                return modules.size();
            }
        }
        catch (const std::exception&) {}
        return 0;
    }

private:
    static bool requiresSource(slang::DeclReflection* decl, bool inGeneric, bool inStruct)
    {
        // Slang 2025.13.2 loses information used to evaluate generic static
        // constants and default-initialize struct fields when restoring ASTs.
        if (!decl)
            return true;
        using Kind = slang::DeclReflection::Kind;
        const auto kind = decl->getKind();
        if (kind == Kind::Variable)
        {
            auto* variable = decl->asVariable();
            if (!variable)
                return true;
            const bool isStatic = variable->findModifier(slang::Modifier::Static) != nullptr;
            return (inGeneric && isStatic && variable->findModifier(slang::Modifier::Const)) ||
                (inStruct && !isStatic && variable->hasDefaultValue());
        }
        if (kind == Kind::Func)
            return false;
        if (kind == Kind::Generic)
        {
            auto* generic = decl->asGeneric();
            return !generic || requiresSource(generic->getInnerDecl(), true, inStruct);
        }
        for (auto* child : decl->getChildren())
        {
            if (requiresSource(child, inGeneric, inStruct || kind == Kind::Struct))
                return true;
        }
        return false;
    }

    static bool dependsOnSourceOnly(slang::IModule* module, const std::set<std::filesystem::path>& sourceOnly)
    {
        using namespace live_slang_disk;
        if (sourceOnly.empty())
            return false;
        for (SlangInt32 i = 0, count = module->getDependencyFileCount(); i < count; ++i)
        {
            const auto* dependency = module->getDependencyFilePath(i);
            if (!dependency)
                return true;
            std::error_code error;
            const auto canonical = fs::canonical(utf8Path(dependency), error);
            if (error || sourceOnly.count(canonical))
                return true;
        }
        return false;
    }

    Slang::ComPtr<slang::ISession> restore(
        slang::IGlobalSession* global, const slang::SessionDesc& desc, const std::filesystem::path& path)
    {
        using namespace live_slang_disk;
        try
        {
            std::error_code error;
            if (!fs::is_regular_file(path, error))
                return {};
            const auto package = readFile(path);
            if (package.size() < 32)
                return {};
            const auto payload = std::string_view(package).substr(0, package.size() - 32);
            if (digest(payload) != std::string_view(package).substr(payload.size()))
                return {};
            PackReader reader(payload);
            if (reader.field() != mKey)
                return {};

            const auto files = reader.number();
            if (files == 0 || files > kMaxRecords)
                return {};
            std::set<std::string> sourcePaths;
            for (uint32_t index = 0; index < files; ++index)
            {
                const std::string name(reader.field());
                const auto kind = reader.number();
                if (kind > static_cast<uint32_t>(FileKind::Directory))
                    return {};
                const FileRecord record{static_cast<FileKind>(kind), std::string(reader.field()), std::string(reader.field())};
                if (name.empty() || !matches(name, record))
                    return {};
                if (record.kind == FileKind::File && record.content.size() == 32)
                    sourcePaths.insert(pathString(fs::absolute(utf8Path(name))));
            }

            const auto modules = reader.number();
            if (modules == 0 || modules > kMaxRecords)
                return {};
            struct Module
            {
                std::string name;
                std::string path;
                std::string_view ir;
            };
            std::vector<Module> ordered;
            std::set<std::string> seen;
            for (uint32_t index = 0; index < modules; ++index)
            {
                Module module{std::string(reader.field()), std::string(reader.field()), reader.field()};
                if (module.name.empty() || !sourcePaths.count(module.path) || module.ir.empty() || !seen.insert(module.name).second)
                    return {};
                ordered.push_back(std::move(module));
            }
            if (!reader.empty())
                return {};

            ComPtr<slang::ISession> session;
            if (SLANG_FAILED(global->createSession(desc, session.writeRef())) || !session ||
                session->getLoadedModuleCount() != 0)
                return {};
            if (mReadAttempt)
                mReadAttempt(path);
            // The pinned compiler reports loaded modules after their own imports.
            // Deserializing in this order ensures dependencies are already present.
            for (size_t index = 0; index < ordered.size(); ++index)
            {
                const auto& module = ordered[index];
                ComPtr<ISlangBlob> ir(Slang::INIT_ATTACH, new Blob(std::string(module.ir)));
                ComPtr<ISlangBlob> diagnostics;
                auto* loaded = session->loadModuleFromIRBlob(module.name.c_str(), module.path.c_str(), ir, diagnostics.writeRef());
                if (!loaded || (diagnostics && diagnostics->getBufferSize() > 1) ||
                    session->getLoadedModuleCount() != static_cast<SlangInt>(index + 1) ||
                    session->getLoadedModule(static_cast<SlangInt>(index)) != loaded)
                    return {};
            }
            mHits = ordered.size();
            return session;
        }
        catch (const std::exception&) { return {}; }
    }

    LiveSlangDiskMode mMode;
    std::filesystem::path mDirectory;
    std::filesystem::path mTrustedDirectory;
    ReadAttempt mReadAttempt;
    std::filesystem::path mPath;
    std::string mKey;
    Slang::ComPtr<live_slang_disk::TrackingFileSystem> mTracking;
    size_t mHits = 0;
    bool mForceSource = false;
    bool mExistingCandidate = false;
    bool mPublicationFailed = false;
};