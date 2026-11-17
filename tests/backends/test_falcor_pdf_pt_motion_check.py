"""CPU contracts for bounded continuous-camera PDF-history diagnostics."""

from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np


CAMERA = dict(position=[0., 0., 0.], direction=[0., 0., 1.], up=[0., 1., 0.], vertical_fov=45.)


class PdfMotionCheckTests(unittest.TestCase):
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('scripts.falcor.pdf_pt_motion_check'),
                             'Continuous-camera diagnostic driver is missing')
        from scripts.falcor import pdf_pt_motion_check
        return pdf_pt_motion_check

    def test_plan_preserves_history_during_motion_and_explicitly_resets_the_cut(self):
        check = self.module()
        plan = check.frame_plan(100)
        self.assertEqual(len(plan), 28)
        self.assertEqual([row['phase'] for row in plan[:8]], ['warmup'] * 8)
        self.assertEqual([row['offset'] for row in plan[8:20]], [.004 * i for i in range(1, 13)])
        self.assertEqual([row['offset'] for row in plan[20:24]], [.048] * 4)
        self.assertFalse(any(row['reset'] or row['replace'] for row in plan[:24]))
        self.assertEqual([row['clock_frame'] for row in plan], list(range(1, 29)))
        self.assertEqual(plan[24]['phase'], 'cut-reset')
        self.assertTrue(plan[24]['reset'])
        self.assertEqual(plan[24]['path_seed'], plan[25]['path_seed'])
        self.assertNotEqual(plan[24]['graph'], plan[25]['graph'])
        self.assertTrue(plan[26]['replace'])
        self.assertEqual(plan[26]['path_seed'], plan[27]['path_seed'])
        self.assertNotEqual(plan[26]['graph'], plan[27]['graph'])
        for offset in (-1, True, 2**32 - 25):
            with self.subTest(seed=offset), self.assertRaises(ValueError):
                check.frame_plan(offset)
        fast = check.frame_plan(motion_step=.05)
        self.assertEqual(fast[19]['offset'], .05 * 12)
        self.assertEqual(fast[24]['offset'], 1.6)
        for step in (0, -.01, .050001, float('nan'), True):
            with self.subTest(step=step), self.assertRaises(ValueError):
                check.frame_plan(motion_step=step)

    def test_generated_script_applies_motion_before_render_and_records_runtime_values(self):
        check = self.module()
        class Float3:
            def __init__(self, x, y, z): self.x, self.y, self.z = x, y, z
        class Pass:
            def __init__(self): self.fixedSeed, self.reset_count = 0, 0
            def reset(self): self.reset_count += 1
        class Graph:
            def __init__(self, name): self.name, self.passes = name, {}
            def addPass(self, value, name): self.passes[name] = value
            def addEdge(self, *args): pass
            def markOutput(self, *args): pass
            def __getitem__(self, key): return self.passes[key]
            def print(self): print(self.name)
        camera = SimpleNamespace()
        rendered, captured, graphs = [], [], []
        m = SimpleNamespace(scene=SimpleNamespace(camera=camera), clock=SimpleNamespace(framerate=0, frame=0, time=0))
        m.clock.pause = lambda: None
        m.addGraph = graphs.append
        m.removeGraph = graphs.remove
        m.loadScene = lambda *args: None
        m.setActiveGraph = lambda graph: setattr(m, 'active', graph)
        def render():
            rendered.append((m.clock.frame, camera.position.x, camera.target.x,
                             m.active['PathTracer'].fixedSeed, m.active['PathTracer'].reset_count))
        m.renderFrame = render
        m.frameCapture = SimpleNamespace(capture=lambda: captured.append(m.frameCapture.baseFilename))
        falcor = SimpleNamespace(float3=Float3, RenderGraph=Graph, createPass=lambda *args: Pass(),
                                 TextureChannelFlags=SimpleNamespace(RGBA=15))
        source = check.render_script(Path('scene'), CAMERA, check.frame_plan(100))
        with tempfile.TemporaryDirectory() as directory:
            original = Path.cwd()
            try:
                os.chdir(directory)
                with patch.dict(sys.modules, {'falcor': falcor}):
                    exec(compile(source, 'motion-render.py', 'exec'), {'m': m, 'exit': lambda: None})
                records = json.loads(Path('executed-frames.json').read_text())
            finally:
                os.chdir(original)
        self.assertEqual(len(rendered), 28)
        self.assertEqual(len(captured), 28)
        self.assertEqual(rendered[7], (8, 0., 0., 107, 0))
        self.assertEqual(rendered[8], (9, -.004, -.004, 108, 0))
        self.assertEqual(rendered[19], (20, -.048, -.048, 119, 0))
        self.assertEqual(rendered[23], (24, -.048, -.048, 123, 0))
        self.assertEqual(rendered[24], (25, -1.048, -1.048, 124, 1))
        self.assertEqual(rendered[25], (26, -1.048, -1.048, 124, 0))
        self.assertEqual(records[24]['actual_fixed_seed'], 124)
        self.assertEqual(records[24]['camera']['position'], [-1.048, 0., 0.])
        self.assertEqual(records[26]['renders_on_graph'], 1)
        self.assertTrue(records[26]['graph_created'])
        self.assertEqual(CAMERA['position'], [0., 0., 0.])

    def write_fixture(self, root, check):
        import OpenEXR
        plan = check.frame_plan(100)
        executed, graph_seeds, graph_frames = [], {}, {}
        for event in plan:
            created = event['replace'] or event['graph'] not in graph_seeds
            if created:
                graph_seeds[event['graph']], graph_frames[event['graph']] = 0, 0
            previous_seed = graph_seeds[event['graph']]
            graph_seeds[event['graph']] = event['path_seed']
            graph_frames[event['graph']] += 1
            camera = {'position': [-event['offset'], 0., 0.], 'target': [-event['offset'], 0., 1.], 'up': [0., 1., 0.]}
            executed.append({**event, 'actual_fixed_seed': event['path_seed'],
                             'fixed_seed_before_assignment': previous_seed,
                             'actual_clock_frame': event['clock_frame'], 'camera': camera,
                             'graph_created': created, 'renders_on_graph': graph_frames[event['graph']],
                             'render_wall_seconds': .01})
            fresh = event['phase'] in ('cut-reset', 'fresh-cut', 'replacement', 'fresh-replacement')
            age = 1 if fresh else min(event['clock_frame'], 8)
            rgba = {
                'color': [2., 3., 4., 1.],
                'nrdEmission': [float(age * 2), 1., 1., float(age)],
                'nrdDiffuseRadianceHitDist': [.25 * age, 0., 0., float(age)],
                'nrdSpecularRadianceHitDist': [.8 if age > 1 else 1., 2., 4., float(age)],
                'nrdResidualRadianceHitDist': [1., 1., 1., 1.],
            }
            for name, pixel in rgba.items():
                image = np.broadcast_to(np.asarray(pixel, dtype=np.float32), (2, 3, 4)).copy()
                channels = {channel: image[..., i].copy() for i, channel in enumerate('RGBA')}
                OpenEXR.File({}, channels).write(str(root / f"{event['capture']}.PathTracer.{name}.{event['clock_frame']}.exr"))
        (root / 'executed-frames.json').write_text(json.dumps(executed))
        return plan, executed

    def test_real_float_exrs_prove_motion_history_and_explicit_reset_fresh_equality(self):
        check = self.module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan, executed = self.write_fixture(root, check)
            before = {path.name: path.read_bytes() for path in root.iterdir()}
            result = check.verify_results(root, plan, 3, 2, CAMERA)
            self.assertEqual(result['status'], 'passed')
            self.assertEqual(len(result['frames']), 28)
            self.assertEqual(len(result['artifacts']), 140)
            self.assertEqual(result['motion']['frames'], 12)
            self.assertEqual(result['motion']['minimum_h'], float(np.float32(.8)))
            self.assertEqual(result['cut_reset']['raw_moment_changed_pixels'], 0)
            self.assertEqual(result['replacement']['hdr_changed_pixels'], 0)
            self.assertEqual({path.name: path.read_bytes() for path in root.iterdir()}, before)
            for field, value in (('actual_fixed_seed', 999), ('actual_clock_frame', 999),
                                 ('camera', {'position': [0., 0., 0.], 'target': [0., 0., 1.], 'up': [0., 1., 0.]})):
                altered = deepcopy(executed)
                altered[10][field] = value
                (root / 'executed-frames.json').write_text(json.dumps(altered))
                with self.subTest(field=field), self.assertRaises(ValueError):
                    check.verify_results(root, plan, 3, 2, CAMERA)

    def test_diagnostic_rejects_direction_reset_native_history_loss_and_missing_active_h(self):
        import OpenEXR
        check = self.module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan, executed = self.write_fixture(root, check)
            event = plan[10]
            for name, channel, value in (('nrdEmission', 'A', 1.), ('nrdSpecularRadianceHitDist', 'A', 1.),
                                         ('nrdSpecularRadianceHitDist', 'R', 1.), ('nrdEmission', 'R', float('nan'))):
                path = root / f"{event['capture']}.PathTracer.{name}.{event['clock_frame']}.exr"
                original = path.read_bytes()
                with OpenEXR.File(str(path), separate_channels=True) as image:
                    channels = {key: val.pixels.copy() for key, val in image.channels().items()}
                channels[channel][:] = value
                OpenEXR.File({}, channels).write(str(path))
                with self.subTest(aov=name, channel=channel), self.assertRaises(ValueError):
                    check.verify_results(root, plan, 3, 2, CAMERA)
                path.write_bytes(original)
            path = root / f"{plan[24]['capture']}.PathTracer.nrdDiffuseRadianceHitDist.25.exr"
            with OpenEXR.File(str(path), separate_channels=True) as image:
                channels = {key: val.pixels.copy() for key, val in image.channels().items()}
            channels['R'][:] *= 2
            OpenEXR.File({}, channels).write(str(path))
            with self.assertRaises(ValueError):
                check.verify_results(root, plan, 3, 2, CAMERA)


if __name__ == '__main__':
    unittest.main()
