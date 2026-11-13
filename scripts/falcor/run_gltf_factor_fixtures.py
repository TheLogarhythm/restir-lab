"""Run small deterministic marker/native texture and emitter controls."""
import json, subprocess, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'src'))
from scripts.falcor.process_utils import exclusive_operation, check_renderer_idle
from image_io.exr import read_exr
import numpy as np

old = ROOT / 'runs/bistro-gltf-investigation-20261111/factor-fixture-01'
out = ROOT / 'runs/gltf-factor-gpu-fixture-01'
if out.exists(): raise FileExistsError(out)
out.mkdir(parents=True)
render_template = (old / 'textured/render.py').read_text(encoding='utf8')
scene_template = (old / 'textured.pyscene').read_text(encoding='utf8')
for name, marked, textured, runtime in [
    ('marked_constant', True, False, 'falcor-gltf-factor-runtime'),
    ('marked_textured', True, True, 'falcor-gltf-factor-runtime'),
    ('native_textured', False, True, 'falcor-gltf-factor-runtime'),
    ('native_baseline', False, True, 'falcor-reference-runtime'),
]:
    d = out / name; d.mkdir()
    scene = scene_template
    if marked:
        scene = scene.replace('mat=StandardMaterial(', 'mat=GltfFactorMaterial(').replace('light=StandardMaterial(', 'light=GltfFactorMaterial(')
        scene += '\nassert mat.gltfFactorMarker and light.gltfFactorMarker\n'
    if not textured:
        scene = '\n'.join(line for line in scene.splitlines() if 'loadMaterialTexture' not in line) + '\n'
    scene_file = d / 'scene.pyscene'; scene_file.write_text(scene, encoding='utf8')
    script = render_template.replace(repr(str(old / 'textured')), repr(str(d)))
    script = script.replace(repr(str(old / 'textured.pyscene')), repr(str(scene_file)))
    # Keep the shared render-graph helper from the original diagnostic.
    script = script.replace('from reference_graph import build_graph', f"sys.path.insert(0, {str(old / 'textured')!r})\nfrom reference_graph import build_graph")
    render = d / 'render.py'; render.write_text(script, encoding='utf8')
    cmd = [str(ROOT / 'build' / runtime / 'runtime/Mogwai.exe'), '--device-type', 'd3d12', '--width', '64', '--height', '36', '--script', str(render), '--headless']
    with exclusive_operation(ROOT / 'build/falcor/.operation.lock'):
        check_renderer_idle()
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=240)
    (d / 'stdout.log').write_text(result.stdout, encoding='utf8')
    (d / 'stderr.log').write_text(result.stderr, encoding='utf8')
    if result.returncode: raise RuntimeError(f'{name} returned {result.returncode}: {result.stderr[-3000:]} {result.stdout[-3000:]}')
    print(name, 'completed', flush=True)

results = {}
for a, b in [('marked_constant', 'marked_textured'), ('native_baseline', 'native_textured')]:
    x = read_exr(out / a / 'capture.AccumulatePass.output.4.exr')
    y = read_exr(out / b / 'capture.AccumulatePass.output.4.exr')
    diff = np.abs(x - y)
    results[a + '_vs_' + b] = {'max_abs': float(np.max(diff)), 'mean_abs': float(np.mean(diff)), 'all_finite': bool(np.isfinite(x).all() and np.isfinite(y).all())}
(out / 'comparison.json').write_text(json.dumps(results, indent=2)+'\n', encoding='utf8')
print(json.dumps(results, indent=2), flush=True)
