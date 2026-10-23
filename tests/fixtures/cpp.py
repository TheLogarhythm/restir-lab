"""Compile actual shared shader code on CPU using the local MSVC toolchain."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import unittest


def compiler_environment():
    compiler = shutil.which("cl")
    if compiler is None:
        raise unittest.SkipTest("MSVC is required for the production shader checks")
    environment = os.environ.copy()
    if not environment.get("INCLUDE"):
        vcvars = Path(compiler).parents[6] / "Auxiliary/Build/vcvars64.bat"
        settings = subprocess.check_output(f'cmd /d /s /c ""{vcvars}" >nul && set"', text=True)
        environment.update(line.split("=", 1) for line in settings.splitlines()
                           if "=" in line and not line.startswith("="))
    return compiler, environment


def shader_function(source, name, return_type=r"(?:bool|void|RTXDI_DIReservoir)"):
    matches = list(re.finditer(r"\b" + return_type + r"\s+" + name + r"\s*\(", source))
    if len(matches) != 1:
        raise AssertionError(f"Expected one production {name} function")
    start = matches[0].start()
    opening = source.index("{", matches[0].end())
    depth, end = 1, opening + 1
    while depth and end < len(source):
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    if depth:
        raise AssertionError(f"Unterminated production {name} function")
    return re.sub(r"\binout\s+(\w+)\s+(\w+)", r"\1& \2", source[start:end])


def compile_cpp(source, directory, *, includes=(), toolchain=None):
    compiler, environment = toolchain or compiler_environment()
    directory, source = Path(directory), Path(source)
    executable = directory / (source.stem + ".exe")
    result = subprocess.run([compiler, "/nologo", "/EHsc", "/std:c++17", str(source),
        *("/I" + str(path) for path in includes), "/Fe:" + str(executable),
        "/Fo:" + str(directory / (source.stem + ".obj"))],
        cwd=directory, capture_output=True, text=True, env=environment)
    if result.returncode:
        raise AssertionError(result.stdout + result.stderr)
    return executable
