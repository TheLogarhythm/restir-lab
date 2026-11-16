"""Fingerprint and apply the PDF PT shaders to an isolated runtime copy.

The shader implementation owns the edits. This module supplies the immutable
input inventory and records exactly which source bytes produced each edit.
"""
import hashlib
from pathlib import Path
import stat

from .spatial_experiment_config import validate_pdf_shader
from . import runtime_common
from .runtime_common import safe_name, reject_link


ROOT = Path(__file__).resolve().parents[2]
MARKER = 'LAB_PDF_PT_PRIVATE_OVERLAY_V1'
PROFILES = ('normal', 'one', 'zero', 'center', 'observe', 'native')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def validate_parameters(parameters):
    return validate_pdf_shader(parameters)


def validate_profile(profile):
    if not isinstance(profile, str) or profile not in PROFILES:
        raise ValueError('Unknown PDF PT compile profile')
    return profile


def shader_module():
    from . import pdf_pt_shader
    return pdf_pt_shader


def source_names():
    names = tuple(shader_module().FILES)
    if not names or len(set(names)) != len(names):
        raise ValueError('PDF PT shader source list is empty or duplicated')
    return tuple(safe_name(name) for name in names)


def implementation_sha256():
    shader = shader_module()
    files = {Path(__file__), Path(shader.__file__), *map(Path, shader.source_files()),
             *runtime_common.implementation_files()}
    result = {}
    for path in sorted(files):
        resolved = path.resolve(strict=True)
        if not resolved.is_relative_to(ROOT.resolve()):
            raise ValueError('PDF PT implementation source escapes the workspace')
        result[resolved.relative_to(ROOT.resolve()).as_posix()] = digest(resolved.read_bytes())
    return result


def build_overlay(sources, parameters, profile='normal'):
    """Return changed existing files, leaving the caller's source dict intact."""
    values = validate_parameters(parameters)
    profile = validate_profile(profile)
    names = source_names()
    if not isinstance(sources, dict) or set(sources) != set(names):
        raise ValueError('Unexpected PDF PT shader input set')
    if any(not isinstance(value, str) for value in sources.values()):
        raise ValueError('PDF PT shader inputs must be UTF-8 source strings')
    before = dict(sources)
    result = shader_module().build_overlay(dict(sources), values, profile=profile)
    if not isinstance(result, dict) or not result or not set(result).issubset(before):
        raise ValueError('PDF PT overlay must change existing declared source files')
    if any(not isinstance(value, str) or value == before[name]
           for name, value in result.items()):
        raise ValueError('PDF PT overlay outputs must contain changed source strings')
    return result


def read_sources(runtime):
    runtime = Path(runtime)
    result = {}
    for name in source_names():
        path = runtime / name
        for parent in path.relative_to(runtime).parents:
            reject_link(runtime / parent)
        info = reject_link(path)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError('PDF PT shader input is not a regular file: ' + name)
        result[name] = path.read_bytes().decode('utf8')
    return result


def apply_overlay(runtime_root, parameters, profile='normal'):
    """Write only private, independently copied runtime files, never a base tree."""
    # Do not resolve an untrusted alias before checking the private namespace.
    runtime = Path(runtime_root).absolute()
    build = ROOT.absolute() / 'build'
    if (runtime.name != 'runtime' or runtime.parent.parent != build
            or not runtime.parent.name.startswith('falcor-pdf-pt-')):
        raise ValueError('PDF PT overlay requires a private build/falcor-pdf-pt-* runtime')
    for path in (build, runtime.parent, runtime):
        reject_link(path)
    if not (runtime / 'Mogwai.exe').is_file():
        raise ValueError('Expected an isolated Falcor runtime root')
    values = validate_parameters(parameters)
    profile = validate_profile(profile)
    inputs = read_sources(runtime)
    outputs = build_overlay(inputs, values, profile=profile)
    # Validate the complete write set before making the first change.
    for name in outputs:
        info = reject_link(runtime / name)
        if info.st_nlink != 1:
            raise ValueError('Refusing to write a hardlinked shader: ' + name)
    files = {}
    for name, output in sorted(outputs.items()):
        original = inputs[name].encode('utf8')
        patched = output.encode('utf8')
        # copy2 may preserve a frozen source's read-only attribute. This file
        # has already been proven independent, so only its private copy changes.
        target = runtime / name
        target.chmod(target.stat().st_mode | stat.S_IWRITE)
        target.write_bytes(patched)
        files[name] = {'original_sha256': digest(original), 'patched_sha256': digest(patched)}
    return {'marker': MARKER, 'parameters': values, 'profile': profile,
            'implementation_sha256': implementation_sha256(), 'files': files}
