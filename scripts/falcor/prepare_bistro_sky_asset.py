"""Prepare the byte-verified Bistro procedural sky without historical run inputs."""
import argparse
import hashlib
import json
import tempfile
from pathlib import Path

import OpenEXR

from scripts.falcor import bake_donut_sky
from src.image_io.exr import read_exr

ROOT = Path(__file__).resolve().parents[2]
EXPECTED_SHA256 = '3d99d20cae2d2168a01ee97cb81d0ae3a62dba58897e0c2517e07922e32e650d'


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def prepare(output, *, root=ROOT):
    root = Path(root).resolve(strict=True)
    output = Path(output).resolve()
    if not output.is_relative_to(root):
        raise ValueError('Sky output must be inside the workspace')
    if output.exists():
        if not output.is_file() or sha(output) != EXPECTED_SHA256:
            raise ValueError('Existing sky does not match the expected bytes')
        return output
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.bistro-sky-', dir=output.parent) as tmp:
        tmp = Path(tmp)
        bake_donut_sky.bake(root/'renderers/rtxdi/Assets/Media/bistro-rtxdi.scene.json',
            root/'renderers/rtxdi/Assets/Media', tmp/'bake',
            source_lighting_model='rtxdi_fullsample',
            ignored_top_level={'rtxgi-volumes': 'Not used by the path tracer'})
        staged = tmp/'environment.exr'
        # Preserve the empty name header present in the historical EXR.
        OpenEXR.File({'name': ''}, {'RGB': read_exr(tmp/'bake/environment.exr')}).write(str(staged))
        if sha(staged) != EXPECTED_SHA256:
            raise ValueError('Generated sky does not match the historical SHA-256')
        with staged.open('rb') as source, output.open('xb') as target:
            import shutil
            shutil.copyfileobj(source, target)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'assets/generated/bistro/environment.exr')
    args = parser.parse_args()
    path = prepare(args.output)
    print(json.dumps({'path':path.relative_to(ROOT).as_posix(), 'sha256':sha(path)}))


if __name__ == '__main__':
    main()
