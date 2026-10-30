"""Build the pinned independent Falcor backend; never patch upstream."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
import shutil
from pathlib import Path
import subprocess
import tempfile

if __package__:
    from .process_utils import check_renderer_idle, exclusive_operation, stop_process
else:
    from process_utils import check_renderer_idle, exclusive_operation, stop_process

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "renderers/falcor/upstream"
OUTPUT = ROOT / "build/falcor"
PIN = ROOT / "renderers/falcor/integration.json"


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def git(*args):
    return subprocess.check_output(["git", "-C", str(SOURCE), *args], text=True).strip()


def source_check():
    pin = json.loads(PIN.read_text())
    if git("rev-parse", "HEAD") != pin["commit"]:
        raise RuntimeError("Falcor revision differs from pin")
    if git("status", "--porcelain", "--untracked-files=no", "--ignore-submodules=none"):
        raise RuntimeError("Falcor tracked source/dependency changes")
    return pin


def check_submodules():
    status = git("submodule", "status", "--recursive")
    if any(line[0] in "-+U" for line in status.splitlines() if line):
        raise RuntimeError(
            "Unresolved submodule revisions; initialize the pinned dependencies with setup.ps1"
        )
    return status


def check_cmake_dependencies(pin):
    for name, dep in pin.get("cmake_dependencies", {}).items():
        check_cmake_dependency(OUTPUT / "deps" / name, dep)


def check_cmake_dependency(path, dep):
    head = subprocess.check_output(
        ["git", "-C", str(path), "rev-parse", "HEAD"], text=True
    ).strip()
    dirty = subprocess.check_output(
        ["git", "-C", str(path), "status", "--porcelain", "--untracked-files=no"],
        text=True,
    ).strip()
    if head != dep["commit"] or dirty:
        raise RuntimeError("CMake dependency differs from pin; preserved: " + str(path))


def prepare_cmake_dependencies(pin, run):
    result = []
    for name, dep in pin.get("cmake_dependencies", {}).items():
        path = OUTPUT / "deps" / name
        if not path.exists() or not any(path.iterdir()):
            path.parent.mkdir(parents=True, exist_ok=True)
            # Publish only a complete checkout. Failed downloads cannot poison a retry.
            with tempfile.TemporaryDirectory(prefix=name + "-", dir=path.parent) as tmp:
                staged = Path(tmp) / "checkout"
                run(["git", "init", str(staged)], name + "-init")
                run(
                    [
                        "git",
                        "-C",
                        str(staged),
                        "remote",
                        "add",
                        "origin",
                        dep["repository"],
                    ],
                    name + "-remote",
                )
                run(
                    [
                        "git",
                        "-C",
                        str(staged),
                        "fetch",
                        "--depth",
                        "1",
                        "origin",
                        dep["commit"],
                    ],
                    name + "-fetch",
                )
                run(
                    ["git", "-C", str(staged), "checkout", "--detach", dep["commit"]],
                    name + "-checkout",
                )
                check_cmake_dependency(staged, dep)
                if path.exists():
                    path.rmdir()  # Remove only the still-empty destination.
                staged.rename(path)
        result.append(
            "-DFETCHCONTENT_SOURCE_DIR_" + name.upper() + "=" + path.as_posix()
        )
    check_cmake_dependencies(pin)
    return result


def check_runtime_files(binary):
    required = (
        "Mogwai.exe",
        "plugins/PathTracer.dll",
        "D3D12/D3D12Core.dll",
        "D3D12/d3d12SDKLayers.dll",
        "dxcompiler.dll",
        "dxil.dll",
        "shaders/nvapi/nvHLSLExtns.h",
        "shaders/nvapi/nvHLSLExtnsInternal.h",
        "shaders/nvapi/nvShaderExtnEnums.h",
    )
    missing = [name for name in required if not (binary / name).is_file()]
    if missing:
        raise RuntimeError("Required runtime deployment missing: " + ", ".join(missing))


def verify_build():
    pin = source_check()
    check_submodules()
    check_cmake_dependencies(pin)
    record = json.loads((OUTPUT / "build.json").read_text())
    if record["commit"] != pin["commit"] or record["pin_sha256"] != sha(PIN):
        raise RuntimeError("Build pin changed")
    check_runtime_files((ROOT / record["executable"]).parent)
    for name, digest in record["files"].items():
        p = ROOT / name
        if not p.is_file() or sha(p) != digest:
            raise RuntimeError("Build input/output changed: " + name)
    return record


def check_build_path(path):
    # Falcor 9.0 setup.bat and Packman contain unquoted internal path expansions.
    if any(char.isspace() for char in str(path)):
        raise RuntimeError(
            "Falcor 9.0 upstream build requires a checkout path without spaces; existing files preserved"
        )


def ensure_source():
    if SOURCE.exists() and (not SOURCE.is_dir() or any(SOURCE.iterdir())):
        source_check()  # Never switch an existing checkout to a different revision.
        return
    OUTPUT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_phase(
        [
            "git",
            "-C",
            str(ROOT),
            "-c",
            "http.sslBackend=openssl",
            "submodule",
            "update",
            "--init",
            "--",
            "renderers/falcor/upstream",
        ],
        ROOT,
        os.environ.copy(),
        OUTPUT / f"{stamp}-source.log",
    )
    source_check()


def run_phase(command, cwd, env, logfile):
    with logfile.open("w", encoding="utf-8") as log:
        proc = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            start_new_session=os.name != "nt",
        )
        try:
            code = proc.wait()
        except BaseException as exc:
            if proc.poll() is None:
                cleanup_error = stop_process(proc)
                if cleanup_error:
                    log.write(cleanup_error + "\n")
                    exc.add_note(cleanup_error)
            raise
    if code:
        raise RuntimeError(f"Phase failed ({code}): {logfile}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--jobs", type=int, default=4)
    args = parser.parse_args()
    with exclusive_operation(OUTPUT / ".operation.lock"):
        _build(args)


def _build(args):
    if args.check_only:
        print(
            json.dumps(
                {"status": "verified", "executable": verify_build()["executable"]}
            )
        )
        return
    if not 1 <= args.jobs <= 8:
        raise ValueError("jobs must be 1..8")
    check_renderer_idle()
    check_build_path(SOURCE)
    ensure_source()
    pin = source_check()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    sdk = (
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
        / "Windows Kits/10/Include"
        / pin["sdk"]
    )
    if not sdk.is_dir():
        raise RuntimeError("Required SDK missing: " + str(sdk))
    if shutil.disk_usage(OUTPUT).free < 15 * 1024**3:
        raise RuntimeError("Falcor build requires at least 15 GiB free")
    vswhere = (
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
        / "Microsoft Visual Studio/Installer/vswhere.exe"
    )
    if not vswhere.is_file():
        raise RuntimeError("Visual Studio installer locator missing")
    vs = subprocess.check_output(
        [
            str(vswhere),
            "-latest",
            "-version",
            "[17.0,18.0)",
            "-products",
            "*",
            "-requires",
            "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
            "-property",
            "installationPath",
        ],
        text=True,
    ).strip()
    if not vs:
        raise RuntimeError("VS2022 C++ compiler missing")
    env = os.environ.copy()
    env["PM_PACKAGES_ROOT"] = str(OUTPUT / "packman-cache")
    index = int(env.get("GIT_CONFIG_COUNT", "0"))
    settings = {
        "http.sslBackend": "openssl",
        "http.lowSpeedLimit": "1024",
        "http.lowSpeedTime": "60",
    }
    for offset, (key, value) in enumerate(settings.items(), index):
        env[f"GIT_CONFIG_KEY_{offset}"] = key
        env[f"GIT_CONFIG_VALUE_{offset}"] = value
    env["GIT_CONFIG_COUNT"] = str(index + len(settings))
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    def run(command, phase):
        logfile = OUTPUT / f"{stamp}-{phase}.log"
        print(phase, logfile, flush=True)
        run_phase(command, SOURCE, env, logfile)

    for attempt in range(1, 4):
        try:
            run(
                ["git", "submodule", "update", "--init", "--recursive", "--depth", "1"],
                f"submodules-{attempt}",
            )
            break
        except RuntimeError:
            if attempt == 3:
                raise
    check_submodules()
    run(["cmd", "/d", "/c", str(SOURCE / "setup.bat")], "dependencies")
    source_check()
    preset = {
        "version": 3,
        "configurePresets": [
            {
                "name": pin["preset"],
                "inherits": "windows-vs2022",
                "binaryDir": "${sourceDir}/build/" + pin["preset"],
                "toolset": {"value": "host=x64", "strategy": "set"},
                "cacheVariables": {
                    "CMAKE_SYSTEM_VERSION": pin["sdk"],
                    "FALCOR_USE_SYSTEM_PYTHON": "OFF",
                },
            }
        ],
    }
    path = SOURCE / "CMakeUserPresets.json"
    if path.exists() and json.loads(path.read_text()) != preset:
        raise RuntimeError("Existing user preset differs; preserved")
    path.write_text(json.dumps(preset, indent=2) + "\n")
    cmake = SOURCE / "tools/.packman/cmake/bin/cmake.exe"
    cmake_dependencies = prepare_cmake_dependencies(pin, run)
    run([str(cmake), "--preset", pin["preset"], *cmake_dependencies], "configure")
    directory = SOURCE / "build" / pin["preset"]
    run(
        [
            str(cmake),
            "--build",
            str(directory),
            "--config",
            "Release",
            "--target",
            "Mogwai",
            "falcor-copy-files",
            "--parallel",
            str(args.jobs),
        ],
        "compile",
    )
    source_check()
    binary = directory / "bin/Release"
    exe = binary / "Mogwai.exe"
    check_runtime_files(binary)
    files = [
        PIN,
        Path(__file__),
        Path(__file__).with_name("process_utils.py"),
        ROOT / "scripts/falcor/setup.ps1",
        SOURCE / "dependencies.xml",
        path,
        directory / "CMakeCache.txt",
    ]
    files += [
        p
        for p in binary.rglob("*")
        if p.is_file()
        and p.suffix.lower()
        in (
            ".exe",
            ".dll",
            ".pyd",
            ".slang",
            ".slangh",
            ".hlsl",
            ".hlsli",
            ".h",
            ".json",
        )
    ]
    record = {
        "schema_version": 1,
        "status": "built",
        "commit": pin["commit"],
        "configuration": "Release",
        "visual_studio": vs,
        "sdk": pin["sdk"],
        "built_utc": datetime.now(timezone.utc).isoformat(),
        "pin_sha256": sha(PIN),
        "executable": exe.relative_to(ROOT).as_posix(),
        "cmake_dependencies": pin.get("cmake_dependencies", {}),
        "submodules": git("submodule", "status", "--recursive"),
        "files": {p.relative_to(ROOT).as_posix(): sha(p) for p in files},
    }
    (OUTPUT / "build.json").write_text(json.dumps(record, indent=2) + "\n")
    print("Built and recorded", exe)


if __name__ == "__main__":
    main()
