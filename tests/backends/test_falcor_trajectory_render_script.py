"""Shared trajectory scripts preserve camera evidence without importing a CLI."""
import copy
import importlib
import importlib.util
import json
import math
from pathlib import Path
from types import SimpleNamespace
import unittest

from scripts.falcor import camera_trajectory, trajectory_preview

ROOT = Path(__file__).resolve().parents[2]


def shared_builder():
    if importlib.util.find_spec("scripts.falcor.trajectory_render_script") is None:
        raise AssertionError("The neutral trajectory script builder is missing")
    return importlib.import_module("scripts.falcor.trajectory_render_script")


class TrajectoryRenderScriptTests(unittest.TestCase):
    def frames(self, seed_offset=0):
        return camera_trajectory.sample_frames(camera_trajectory.load(
            ROOT / "scenes/trajectories/pt-walkthroughs/classroom.json"), seed_offset=seed_offset)

    def test_shared_script_preserves_all_actual_camera_seed_and_clock_evidence(self):
        shared = shared_builder()
        frames = self.frames(seed_offset=17)
        source = shared.build_script(Path("scene.pyscene"), frames, Path("out"), {}, captures=[41, 340])
        compile(source, "<shared-trajectory>", "exec")
        begin = source.index("for frame in range(1,")
        end = source.index("\nwith Path(", begin)
        clock = SimpleNamespace(frame=0, framerate=0, time=0)
        tracer = SimpleNamespace(fixedSeed=0)
        camera = SimpleNamespace(position=None, target=None, up=None)
        captured, rendered, evidence = [], [], []
        def camera_state():
            return {"position": camera.position[:], "target": camera.target[:], "up": camera.up[:],
                    "frameHeight": 24, "focalLength": 12 / math.tan(math.radians(65) / 2),
                    "apertureRadius": 0, "animated": False, "nearPlane": frames[0]["camera"]["near_plane"]}
        def render():
            rendered.append((clock.frame, tracer.fixedSeed, camera.position[:], camera.target[:], camera.up[:]))
        engine = SimpleNamespace(renderFrame=render, clock=clock,
            frameCapture=SimpleNamespace(capture=lambda: captured.append(clock.frame)),
            scene=SimpleNamespace(renderSettings=SimpleNamespace(useAnalyticLights=True, useEnvLight=True,
                useEmissiveLights=True), lights=[], envMap=None, stats={}))
        class Sink:
            def write_text(self, *args, **kwargs):
                pass
        exec(source[begin:end], {"trajectory": frames, "trajectory_records": evidence,
            "m": engine, "tracer": tracer, "camera": camera,
            "float3": lambda *values: list(values), "camera_state": camera_state,
            "records": {}, "Path": lambda *args: Sink(), "json": json})
        self.assertEqual([r[:2] for r in rendered], [(f, f + 16) for f in range(1, 341)])
        self.assertEqual([r[2:] for r in rendered],
            [(f["camera"]["position"], f["camera"]["target"], f["camera"]["up"]) for f in frames])
        self.assertEqual(captured, [41, 340])
        shared.verify_camera_records(evidence, frames)
        for actual, expected in zip(evidence, frames):
            self.assertEqual({key: actual[key] for key in expected}, expected)
        self.assertEqual(len(evidence), 340)

    def test_shared_builder_rejects_mislabeled_frames_or_discontinuous_seeds(self):
        shared = shared_builder()
        frames = self.frames(seed_offset=17)
        for index, change in ((0, {"frame": 2}), (39, {"video_frame": 0}),
                              (339, {"video_frame": 300}), (1, {"path_seed": 99})):
            changed = copy.deepcopy(frames)
            changed[index].update(change)
            with self.subTest(index=index, change=change), self.assertRaisesRegex(ValueError, r"40\+300"):
                shared.build_script(Path("scene.pyscene"), changed, Path("out"), {})

    def test_preview_keeps_its_resolution_limit_separate_from_formal_size(self):
        for width, height in ((1920, 1080), (642, 360), (640, 362)):
            with self.subTest(width=width, height=height), self.assertRaisesRegex(ValueError, "640x360"):
                trajectory_preview.launch(ROOT / "missing-route", ROOT / "runs/new-preview", ROOT,
                    width=width, height=height)

    def test_preview_script_rejects_schedule_changes_but_accepts_seed_offsets(self):
        frames = self.frames(seed_offset=17)
        trajectory_preview.render_script(Path("scene.pyscene"), frames, Path("out"), {})
        for index, change in ((0, {"frame": 2}), (39, {"video_frame": 0}),
                              (339, {"video_frame": 300}), (1, {"path_seed": 99})):
            changed = copy.deepcopy(frames)
            changed[index].update(change)
            with self.subTest(index=index, change=change), self.assertRaisesRegex(ValueError, r"40\+300"):
                trajectory_preview.render_script(Path("scene.pyscene"), changed, Path("out"), {})


if __name__ == "__main__":
    unittest.main()
