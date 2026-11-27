"""Build the live Falcor core overlay from the retained pinned Release objects."""

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

from . import live_device_overlay, live_slang_cache
from .process_utils import exclusive_operation, publish_directory
from .runtime_common import sha256_file

ROOT = Path(__file__).resolve().parents[2]
UPSTREAM = ROOT / "renderers/falcor/upstream"
PROJECT = UPSTREAM / "build/lab-vs2022/Source/Falcor"
TLOG = PROJECT / "Falcor.dir/Release/Falcor.tlog"
MOGWAI_PROJECT = PROJECT.with_name("Mogwai")
MOGWAI_TLOG = MOGWAI_PROJECT / "Mogwai.dir/Release/Mogwai.tlog"
SOURCE = UPSTREAM / "Source/Falcor/Core/Program/ProgramManager.cpp"
STOCK = UPSTREAM / "build/lab-vs2022/bin/Release/Falcor.dll"
BINARIES = ("Falcor.dll", "Mogwai.exe")
BUILD = ROOT / "build"


def replace_once(text, anchor, replacement):
    if text.count(anchor) != 1:
        raise ValueError(f"Unexpected Falcor source anchor: {anchor}")
    return text.replace(anchor, replacement, 1)


def patch_source(text):
    text = replace_once(text, "namespace Falcor\n{\n", """namespace Falcor
{
namespace
{
using SlangRequest = std::unique_ptr<SlangCompileRequest, decltype(&spDestroyCompileRequest)>;

// Slang component types refer to their session without owning it. Put the
// session in the first base so it is released after the ProgramVersion base.
struct SlangSessionOwner
{
    Slang::ComPtr<slang::ISession> session;
};

class SessionProgramVersion final : private SlangSessionOwner, public ProgramVersion
{
public:
    SessionProgramVersion(slang::ISession* session, Program* program, slang::IComponentType* scope)
        : SlangSessionOwner{Slang::ComPtr<slang::ISession>(session)}, ProgramVersion(program, scope)
    {}
};
} // namespace

""")
    text = replace_once(
        text,
        "    auto pSlangRequest = createSlangCompileRequest(program);",
        "    SlangRequest requestOwner(createSlangCompileRequest(program), spDestroyCompileRequest);\n"
        "    auto* pSlangRequest = requestOwner.get();",
    )
    text = replace_once(text, "        spDestroyCompileRequest(pSlangRequest);\n        return nullptr;",
                        "        return nullptr;")
    text = replace_once(
        text,
        "ProgramVersion::createEmpty(const_cast<Program*>(&program), pSlangGlobalScope)",
        "make_ref<SessionProgramVersion>(pSlangSession.get(), const_cast<Program*>(&program), pSlangGlobalScope.get())",
    )
    text = replace_once(
        text, "    pSlangSession->createCompileRequest(&pSlangRequest);\n    FALCOR_ASSERT(pSlangRequest);",
        "    pSlangSession->createCompileRequest(&pSlangRequest);\n"
        "    SlangRequest requestOwner(pSlangRequest, spDestroyCompileRequest);\n"
        "    FALCOR_ASSERT(pSlangRequest);",
    )
    text = replace_once(text, "                    spDestroyCompileRequest(pSlangRequest);\n", "")
    text = replace_once(text, "    return pSlangRequest;", "    return requestOwner.release();")
    return live_slang_cache.patch_source(text, replace_once)


def quoted(path):
    return '"' + str(path) + '"'


def replace_switch(command, switch, value):
    pattern = rf"(?i)(?:^|(?<=\s))/{re.escape(switch)}\"[^\"]*\""
    command, count = re.subn(pattern, lambda _: value, command)
    if count != 1:
        raise ValueError(f"Expected one /{switch} switch in Falcor Release build record")
    return command


def compile_command(stage, source, tlog, *, precompiled):
    lines = (tlog / "CL.command.1.tlog").read_text(encoding="utf-16").splitlines()
    matches = [lines[index + 1] for index, line in enumerate(lines)
               if line.startswith("^") and line.casefold().endswith("\\" + source.name.casefold())]
    if len(matches) != 1:
        raise ValueError(f"Expected a single compiler recipe for {source.name}")
    command = matches[0]
    if precompiled:
        # Preserve the original forced header without using the precompiled image.
        for switch in ("Yu", "Fp"):
            command = replace_switch(command, switch, "")
    for switch, suffix in (("Fo", ".obj"), ("Fd", ".compile.pdb")):
        command = replace_switch(command, switch, "/" + switch + quoted(stage / (source.stem + suffix)))
    name = re.escape(source.name)
    command, count = re.subn(
        rf'(?i)\s+(?:"[^"]*\\{name}"|\S*\\{name})$',
        lambda _: " /I" + quoted(source.parent) + " " + quoted(stage / source.name), command,
    )
    if count != 1:
        raise ValueError(f"Expected the stock compiler input for {source.name}")
    return command


def link_command(stage, binary_name, tlog, objects):
    lines = (tlog / "link.command.1.tlog").read_text(encoding="utf-16").splitlines()
    if not lines or not lines[0].startswith("^") or any(line.startswith("^") for line in lines[1:]):
        raise ValueError(f"Expected a single linker recipe for {binary_name}")
    link = "\n".join(lines[1:])
    binary = Path(binary_name)
    for switch, name in (("OUT:", binary.name), ("PDB:", binary.with_suffix(".pdb").name),
                         ("IMPLIB:", binary.with_suffix(".lib").name)):
        link = replace_switch(link, switch, "/" + switch + quoted(stage / name))
    for name in objects:
        relative = f"{binary.stem}.dir\\Release\\{name}"
        link, count = re.subn(
            rf"(?i)(?<!\S){re.escape(relative)}(?=$|\s)",
            lambda _: quoted(stage / name), link,
        )
        if count != 1:
            raise ValueError(f"Expected one linker input for {relative}")
    return link


def release_commands(stage):
    core_sources = (SOURCE, *(live_device_overlay.SOURCES[name]
                              for name in ("SampleApp.cpp", "Gui.cpp", "RenderGraph.cpp", "RenderGraphExe.cpp")))
    commands = {path.name: compile_command(stage, path, TLOG, precompiled=True) for path in core_sources}
    objects = tuple(path.with_suffix(".obj").name for path in core_sources)
    link = link_command(stage, "Falcor.dll", TLOG, objects)
    return commands, link


def mogwai_commands(stage):
    paths = live_device_overlay.SOURCES
    names = ("Mogwai.cpp", "MogwaiSettings.cpp", "MogwaiScripting.cpp", "FrameCapture.cpp")
    commands = {name: compile_command(stage, paths[name], MOGWAI_TLOG, precompiled=False) for name in names}
    objects = tuple(Path(name).with_suffix(".obj").name for name in names)
    link = link_command(stage, "Mogwai.exe", MOGWAI_TLOG, objects)
    return commands, link


def exports(path):
    return {
        (int(ordinal), name)
        for ordinal, name in re.findall(r"(?m)^\s+(\d+)\s+[a-fA-F0-9]+\s+[a-fA-F0-9]{8}\s+(\S+)",
                                        path.read_text(encoding="utf8", errors="replace"))
    }


def compile_core(stage, record, sources):
    vs = Path(record["visual_studio"]) / "Common7/Tools/VsDevCmd.bat"
    if not vs.is_file():
        raise FileNotFoundError(vs)
    commands = ["@echo off", f"call {quoted(vs)} -arch=x64 -host_arch=x64 >nul"]

    def run(command):
        commands.extend((command, "if errorlevel 1 exit /b %errorlevel%"))

    for name, contents in sources.items():
        (stage / name).write_text(contents, encoding="utf8")

    for project, recipe, binary in (
        (PROJECT, release_commands, "Falcor.dll"),
        (MOGWAI_PROJECT, mogwai_commands, "Mogwai.exe"),
    ):
        run(f"cd /d {quoted(project)}")
        compile_recipes, link_recipe = recipe(stage)
        for name, argument in compile_recipes.items():
            rsp = stage / (name + ".rsp")
            rsp.write_text(argument + "\n", encoding="utf8")
            run(f"cl @{quoted(rsp)}")
        rsp = stage / (binary + ".rsp")
        rsp.write_text(link_recipe + "\n", encoding="utf8")
        run(f"link @{quoted(rsp)}")

    for label, dll in (("stock", STOCK), ("overlay", stage / "Falcor.dll")):
        run(f"dumpbin /nologo /exports {quoted(dll)} > {quoted(stage / (label + '.exports'))}")
    (stage / "build.cmd").write_text("\n".join([*commands, "exit /b 0", ""]), encoding="utf8")
    log = stage / "build.log"
    with log.open("w", encoding="utf8") as handle:
        result = subprocess.run(["cmd.exe", "/d", "/c", "build.cmd"], cwd=stage, stdout=handle,
                                stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise RuntimeError(log.read_text(encoding="utf8", errors="replace")[-6500:])
    stock, overlay = (exports(stage / (name + ".exports")) for name in ("stock", "overlay"))
    if not stock or stock != overlay:
        raise RuntimeError(f"Falcor export ordinals or names changed ({len(stock - overlay)} removed, "
                           f"{len(overlay - stock)} added)")


def build_core(record):
    """Return an ABI-checked replacement DLL without modifying the pinned build."""
    if os.name != "nt":
        raise OSError("Building the Falcor core overlay requires Windows")
    sources = live_device_overlay.patched_sources()
    sources[SOURCE.name] = patch_source(SOURCE.read_text(encoding="utf8"))
    inputs = {
        "commit": record["commit"],
        "stock": {name: sha256_file(STOCK.with_name(name)) for name in BINARIES},
        "sources": {name: hashlib.sha256(text.encode()).hexdigest() for name, text in sources.items()},
        "recipe": sha256_file(Path(__file__)),
        "build_recipes": {
            str(tlog.relative_to(UPSTREAM) / name): sha256_file(tlog / name)
            for tlog in (TLOG, MOGWAI_TLOG)
            for name in ("CL.command.1.tlog", "link.command.1.tlog")
        },
    }
    identity = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()[:16]
    target = BUILD / ("falcor-live-core-" + identity)
    def built_files(folder):
        return {name: sha256_file(folder / name) for name in BINARIES}

    with exclusive_operation(BUILD / ".falcor-live-core.lock"):
        if not target.is_dir():
            with tempfile.TemporaryDirectory(dir=BUILD, prefix="live-core-stage-") as temporary:
                stage = Path(temporary) / "core"
                stage.mkdir()
                compile_core(stage, record, sources)
                receipt = {"inputs": inputs, "files": built_files(stage)}
                (stage / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf8")
                publish_directory(stage, target)
        receipt = json.loads((target / "receipt.json").read_text(encoding="utf8"))
        if receipt != {"inputs": inputs, "files": built_files(target)}:
            raise ValueError("Private Falcor core does not match its build receipt")
    return target / "Falcor.dll"


if __name__ == "__main__":
    from .live_runtime import build_record

    print(build_core(build_record()))
