"""Build a private point-CGNS PathTracer.dll and the matching per-round cache shaders."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from . import build, cgns_cached_overlay as overlay, cgns_single_overlay as original
from . import runtime_common as common, prepare_adapted_plugins as compiler
from . import reference_runtime, prepare_gltf_composite_runtime_v3 as gltf_runtime
from . import process_utils, spatial_experiment_config
from .runtime_common import is_transient_runtime_file as _transient_runtime_file, validate_runtime_inventory
from .process_utils import check_renderer_idle, exclusive_operation
from .runtime_common import sha256_file as sha
from .spatial_experiment_config import load_config, validate_cgns_shader

ROOT = overlay.HERE.parents[1]
UPSTREAM = ROOT / 'renderers/falcor/upstream'
MODULES = UPSTREAM / 'Source/Modules'
PLUGIN = 'plugins/PathTracer.dll'
KIND = 'falcor_cgns_cached_private_runtime'
PREFIX = 'falcor-cgns-cached-'
SOURCES = {'reference': reference_runtime, 'gltf-v3': gltf_runtime}
SCHEMA_VERSION = 2
LINK_INPUT_NAMES = frozenset(('Falcor.lib', 'fmt.lib', 'LightTileResampling.lib', 'python310.lib',
                              'slang.lib', 'gfx.lib', 'cuda.lib', 'cudart_static.lib'))
HOST_SOURCE_NAMES = frozenset(('ReSTIRPathTracing.h', 'ReSTIRPathTracing.cpp'))


def implementation_files():
    return (Path(__file__), Path(overlay.__file__), overlay.HOST_IMPLEMENTATION,
            Path(compiler.__file__), Path(original.__file__), Path(original.legacy.__file__),
            Path(build.__file__), Path(process_utils.__file__), Path(spatial_experiment_config.__file__),
            *common.implementation_files(), original.SELECTOR, original.CORE,
            *(overlay.HERE / f'cgns_cached_{stage}.cs.slang' for stage in overlay.STAGES))


def _hashes(paths):
    return {path.relative_to(ROOT).as_posix(): sha(path) for path in paths}


def _fingerprint(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def identity(kind, parameters):
    if kind not in SOURCES:
        raise ValueError('Unknown CGNS source runtime')
    return {'source_kind': kind, 'parameters': validate_cgns_shader(parameters),
            'source_receipt_sha256': sha(SOURCES[kind].DEST / 'receipt.json'),
            'implementation_sha256': _hashes(implementation_files()),
            'falcor_build_sha256': sha(ROOT / 'build/falcor/build.json')}


def variant_destination(kind, parameters):
    return ROOT / 'build' / (PREFIX + kind + '-' + _fingerprint(identity(kind, parameters))[:16])


def _compile_plugin(folder, record):
    # PathTracer allocates ReSTIRPathTracing. Compile both translation units
    # against the same private header so the enlarged object has the correct size.
    host = MODULES / 'ReSTIRPathTracing'
    module = folder / 'ReSTIRPathTracing'
    module.mkdir()
    for name, source in overlay.host_sources(host).items():
        (module / name).write_text(source, encoding='utf8')
    cuda = Path(os.environ.get('CUDA_PATH', r'C:/Program Files/NVIDIA GPU Computing Toolkit/CUDA/v12.6'))
    base = UPSTREAM / 'build/lab-vs2022'
    vs = Path(record['visual_studio']) / 'Common7/Tools/VsDevCmd.bat'
    includes = [folder, host, MODULES, *(UPSTREAM / name for name in compiler.INCLUDES), cuda / 'include']
    libs = [base / 'Source/Falcor/Release/Falcor.lib', base / 'external/fmt/Release/fmt.lib',
            base / 'Source/Modules/LightTileResampling/Release/LightTileResampling.lib',
            UPSTREAM / 'external/packman/python/libs/python310.lib',
            *(UPSTREAM / 'external/packman/slang/lib' / lib for lib in ('slang.lib', 'gfx.lib')),
            *(cuda / 'lib/x64' / lib for lib in ('cuda.lib', 'cudart_static.lib'))]
    tracer = UPSTREAM / 'Source/RenderPasses/PathTracer/PathTracer.cpp'
    params = ['/nologo', '/std:c++17', '/EHsc', '/MD', '/O2', '/LD', '/fp:precise',
              '/D_SCL_SECURE_NO_WARNINGS', '/D_SILENCE_CXX17_CODECVT_HEADER_DEPRECATION_WARNING',
              *('/D' + key for key in compiler.DEFINES),
              *('/I' + compiler.quoted(path) for path in includes),
              compiler.quoted(tracer), compiler.quoted(module / 'ReSTIRPathTracing.cpp'),
              '/link', '/OUT:PathTracer.dll', '/INCREMENTAL:NO', '/Brepro',
              *(compiler.quoted(path) for path in libs)]
    (folder / 'compile.rsp').write_text(' '.join(params) + '\n', encoding='utf8')
    batch = folder / 'compile.bat'
    batch.write_text('@echo off\ncall ' + compiler.quoted(vs) +
                     ' -arch=x64 -host_arch=x64 >nul\nif errorlevel 1 exit /b %errorlevel%\n'
                     'cl @compile.rsp\nexit /b %errorlevel%\n', encoding='utf8')
    with (folder / 'compile.log').open('w', encoding='utf8') as log:
        proc = subprocess.run(['cmd.exe', '/d', '/c', 'compile.bat'], cwd=folder,
                              stdout=log, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
    if proc.returncode:
        raise RuntimeError((folder / 'compile.log').read_text(errors='replace')[-5000:])
    return {'plugin_sha256': sha(folder / 'PathTracer.dll'), 'falcor_commit': record['commit'],
            'generated_host_sha256': {p.name: sha(p) for p in module.iterdir()},
            'link_inputs_sha256': {p.name: sha(p) for p in libs}}


def ensure_variant(kind, parameters):
    info = identity(kind, parameters)
    dest = variant_destination(kind, parameters)
    with exclusive_operation(ROOT / 'build/falcor/.operation.lock'):
        check_renderer_idle()
        if dest.exists():
            verify_prepared(dest / 'runtime', expected_parameters=parameters)
            return dest / 'runtime'
        record = build.verify_build()
        source, base = common.read_baseline(SOURCES[kind])
        outputs = overlay.shader_outputs(source, info['parameters'])
        with tempfile.TemporaryDirectory(prefix='cgns-staging-', dir=dest.parent) as stage:
            # Rename the completed package atomically out of the disposable staging root.
            package = Path(stage) / 'package'
            native = package / 'host'
            native.mkdir(parents=True)
            binary = _compile_plugin(native, record)
            runtime = package / 'runtime'
            for name, expected in base['runtime_files_sha256'].items():
                if _transient_runtime_file(name):
                    continue
                target = runtime / name
                target.parent.mkdir(parents=True, exist_ok=True)
                if name == PLUGIN:
                    shutil.copyfile(native / 'PathTracer.dll', target)
                elif name not in outputs:
                    shutil.copyfile(source / name, target)
                    if sha(target) != expected:
                        raise ValueError('Changed CGNS source file: ' + name)
            for name, content in outputs.items():
                (runtime / name).write_bytes(content.encode('utf8'))
            receipt = {'schema_version': SCHEMA_VERSION, 'kind': KIND, **info, **binary,
                       'shader_sha256': {name: sha(runtime / name) for name in outputs}}
            if identity(kind, parameters) != info:
                raise RuntimeError('CGNS implementation changed during preparation')
            (package / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf8')
            (runtime / '.shadercache').mkdir()
            package.rename(dest)
        verify_prepared(dest / 'runtime', expected_parameters=parameters)
    return dest / 'runtime'


def _verify_build_evidence(dest, receipt):
    """Check retained host source bytes and the shape of recorded link hashes.

    Link inputs are provenance, not deployment dependencies. The original .lib
    files need not exist or match a later compiler installation on this machine.
    The pinned receipt and plugin hash bind the saved package to that record.
    """
    sources = common.validate_hash_inventory(receipt.get('generated_host_sha256'), 'CGNS host source record')
    if set(sources) != HOST_SOURCE_NAMES:
        raise ValueError('CGNS host source record inventory differs')
    module = dest / 'host/ReSTIRPathTracing'
    try:
        common.reject_link(dest / 'host')
        common.check_tree(module)
        for name, expected in sources.items():
            target = module / name
            if not target.is_file() or sha(target) != expected:
                raise ValueError('CGNS host source hash differs: ' + name)
    except FileNotFoundError as exc:
        raise ValueError('CGNS host source is missing') from exc
    links = common.validate_hash_inventory(receipt.get('link_inputs_sha256'), 'CGNS link input record')
    if set(links) != LINK_INPUT_NAMES:
        raise ValueError('CGNS link input record inventory differs')


def verify_prepared(runtime, *, expected_parameters=None):
    runtime = common.private_runtime_path(runtime, root=ROOT, prefix=PREFIX)
    dest = runtime.parent
    for path in (dest, runtime, dest / 'receipt.json', dest / 'host', dest / 'host/PathTracer.dll'):
        common.reject_link(path)
    receipt = json.loads((dest / 'receipt.json').read_text(encoding='utf8'))
    kind = receipt['source_kind']
    info = identity(kind, receipt['parameters'])
    if (receipt.get('schema_version') != SCHEMA_VERSION or receipt.get('kind') != KIND
            or any(receipt.get(key) != value for key, value in info.items())
            or dest != variant_destination(kind, info['parameters'])):
        raise ValueError('Cached CGNS current runtime fingerprint differs; use verify_snapshot for historical packages')
    if expected_parameters is not None and info['parameters'] != validate_cgns_shader(expected_parameters):
        raise ValueError('CGNS shader parameters differ')
    _verify_build_evidence(dest, receipt)
    source, base = common.read_baseline(SOURCES[kind])
    outputs = overlay.shader_outputs(source, info['parameters'])
    hashes = {name: hashlib.sha256(code.encode('utf8')).hexdigest() for name, code in outputs.items()}
    plugin_hash = sha(dest / 'host/PathTracer.dll')
    if receipt['shader_sha256'] != hashes or receipt['plugin_sha256'] != plugin_hash:
        raise ValueError('Cached CGNS shader or host receipt differs')
    common.check_tree(runtime)
    validate_runtime_inventory(runtime, {**base['runtime_files_sha256'], **hashes, PLUGIN: plugin_hash})
    return {'kind': KIND, **info, 'receipt_sha256': sha(dest / 'receipt.json'),
            'plugin_sha256': plugin_hash, 'shader_sha256': hashes}


def verify_snapshot(runtime, *, expected_receipt_sha256):
    """Inspect a pinned historical package, requiring its frozen baseline.

    This validates saved bytes and build records without requiring the original
    compiler/link files or claiming they match the current implementation.
    Rendering must continue to use the strict verify_prepared() entry point.
    """
    runtime, receipt, source, base = common.read_snapshot(
        runtime, root=ROOT, prefix=PREFIX, kind=KIND, versions=(1, SCHEMA_VERSION),
        sources=SOURCES, expected_receipt_sha256=expected_receipt_sha256)
    dest = runtime.parent
    _verify_build_evidence(dest, receipt)
    plugin = dest / 'host/PathTracer.dll'
    common.reject_link(plugin)
    plugin_record = common.validate_hash_inventory({PLUGIN: receipt.get('plugin_sha256')}, 'Historical CGNS plugin record')
    plugin_hash = plugin_record[PLUGIN]
    if sha(plugin) != plugin_hash:
        raise ValueError('Historical CGNS host plugin hash differs')
    shaders = common.validate_hash_inventory(receipt.get('shader_sha256'), 'Historical CGNS shader record')
    if any(not name.startswith('shaders/ReSTIRPathTracing/') for name in shaders):
        raise ValueError('Historical CGNS shader inventory differs')
    validate_runtime_inventory(runtime, {**base['runtime_files_sha256'], **shaders, PLUGIN: plugin_hash})
    return {'kind': 'historical_cgns_cached_runtime_snapshot', 'current_implementation': False,
            'verification_scope': 'recorded-bytes-only', 'source_kind': receipt['source_kind'],
            'receipt_sha256': expected_receipt_sha256,
            'plugin_sha256': plugin_hash, 'shader_sha256': shaders}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, choices=tuple(SOURCES))
    args = parser.parse_args()
    print(ensure_variant(args.source, load_config()['methods']['cgns']['shader']))
