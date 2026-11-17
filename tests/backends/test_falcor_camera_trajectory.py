"""Deterministic trajectory timing, speed and preview-script contracts."""
import copy
import math
from pathlib import Path
import unittest

from scripts.falcor import camera_trajectory as trajectory

ROOT = Path(__file__).resolve().parents[2]
ROUTES = ROOT / "scenes/trajectories/pt-walkthroughs"


def fixture():
    return {
        "schema_version": 1, "id": "test-walk",
        "scene_config": "experiments/configs/test.json",
        "meters_per_scene_unit": 1.0,
        "unit_basis": "Test fixture uses metres.",
        "fps": 30, "warmup_frames": 40,
        "hold_start_seconds": 1, "move_seconds": 8, "hold_end_seconds": 1,
        "speed_m_per_second": 1.5,
        "camera": {"vertical_fov": 45, "up": [0, 1, 0], "near_plane": 0.01},
        "waypoints": [
            {"position": [0, 1.6, 0], "target": [0, 1.6, 1]},
            {"position": [12, 1.6, 0], "target": [12, 1.6, 1]},
        ],
    }


class TrajectoryTests(unittest.TestCase):
    def test_holds_warmup_and_exact_endpoints(self):
        frames = trajectory.sample_frames(fixture())
        self.assertEqual(len(frames), 340)
        self.assertEqual([f["frame"] for f in frames], list(range(1, 341)))
        self.assertEqual([f["path_seed"] for f in frames], list(range(340)))
        self.assertTrue(all(f["video_frame"] is None for f in frames[:40]))
        captured = frames[40:]
        self.assertEqual([f["video_frame"] for f in captured], list(range(300)))
        self.assertTrue(all(f["camera"] == captured[0]["camera"] for f in captured[:30]))
        self.assertTrue(all(f["camera"] == captured[-1]["camera"] for f in captured[-30:]))
        self.assertEqual(captured[30]["camera"]["position"], [0, 1.6, 0])
        self.assertEqual(captured[270]["camera"]["position"], [12, 1.6, 0])
        self.assertEqual(captured[150]["camera"]["position"], [6, 1.6, 0])
        for left, right in zip(captured[30:270], captured[31:271]):
            self.assertAlmostEqual(math.dist(left["camera"]["position"], right["camera"]["position"]), 0.05)
        self.assertEqual(captured[0]["video_time_seconds"], 0)
        self.assertAlmostEqual(captured[-1]["video_time_seconds"], 299 / 30)

    def test_arc_length_uses_distance_not_number_of_waypoints(self):
        value = fixture()
        value["waypoints"].insert(1, {"position": [3, 1.6, 0], "target": [3, 1.6, 1]})
        self.assertEqual(trajectory.sample_frames(value)[190]["camera"]["position"], [6, 1.6, 0])

    def test_classroom_has_exact_analytic_twelve_unit_length(self):
        value = trajectory.load(ROUTES / "classroom.json")
        frames = trajectory.sample_frames(value)
        self.assertEqual(trajectory.validate(value)[-1], 12.0)
        self.assertEqual(frames[-1]["camera"]["position"][:2], [-1.5, 1.6])
        self.assertAlmostEqual(frames[-1]["camera"]["position"][2],
                               1.7300888156922487, places=12)

    def test_classroom_analytic_semicircle_has_continuous_tangents(self):
        value = trajectory.load(ROUTES / "classroom.json")
        distances, pose = trajectory._rounded_u_path(value)
        self.assertEqual(len(distances), 4)
        self.assertAlmostEqual(distances[1], 5.3)
        self.assertAlmostEqual(distances[2] - distances[1], 3.7699111843077517)
        for actual, expected in zip(pose((distances[1] + distances[2]) / 2)["position"],
                                    [-0.3, 1.6, -2.4]):
            self.assertAlmostEqual(actual, expected, places=12)
        epsilon = 1e-5
        for distance, expected in ((distances[1], [0, 0, -1]),
                                   (distances[2], [0, 0, 1])):
            before = pose(distance - epsilon)["position"]
            at = pose(distance)["position"]
            after = pose(distance + epsilon)["position"]
            incoming = [(b - a) / epsilon for a, b in zip(before, at)]
            outgoing = [(b - a) / epsilon for a, b in zip(at, after)]
            self.assertLess(math.dist(incoming, expected), 1e-5)
            self.assertLess(math.dist(outgoing, expected), 1e-5)
        for change in ({"radius": 0}, {"radius": 10}, {"side": "unknown"},
                       {"turn_entry": [0.9, 1.7, -1.2]}):
            invalid = copy.deepcopy(value)
            invalid["rounded_u"].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                trajectory.sample_frames(invalid)

    def test_classroom_analytic_samples_preserve_dense_route_within_tolerance(self):
        value = trajectory.load(ROUTES / "classroom.json")
        legacy = copy.deepcopy(value)
        legacy.pop("rounded_u", None)
        positions = [[0.9, 1.6, 4.1]] + [
            [-0.3 + 1.2 * math.cos(math.pi * i / 360), 1.6,
             -1.2 - 1.2 * math.sin(math.pi * i / 360)] for i in range(361)
        ] + [[-1.5, 1.6, 1.7301007779789952]]
        legacy["waypoints"] = [{"position": p, "target": [0.9, 1.4, -3.2]} for p in positions]
        for actual, old in zip(trajectory.sample_frames(value), trajectory.sample_frames(legacy)):
            self.assertLess(math.dist(actual["camera"]["position"], old["camera"]["position"]), 1e-4)
            self.assertLess(math.dist(actual["camera"]["target"], old["camera"]["target"]), 1e-4)
            self.assertEqual(actual["path_seed"], old["path_seed"])
            self.assertEqual(actual["distance_scene_units"], old["distance_scene_units"])

    def test_all_four_routes_retain_approved_schedule_and_physical_length(self):
        for name in ("classroom", "bistro-interior", "bistro-exterior", "zero-day"):
            with self.subTest(name=name):
                value = trajectory.load(ROUTES / (name + ".json"))
                frames = trajectory.sample_frames(value)
                self.assertEqual(len(frames), 340)
                self.assertEqual(frames[-1]["video_frame"], 299)
                self.assertAlmostEqual(frames[-1]["distance_scene_units"] *
                                       value["meters_per_scene_unit"], 12.0)
                self.assertEqual(frames[70]["camera"], frames[40]["camera"])
                self.assertEqual(frames[310]["camera"], frames[-1]["camera"])

    def test_invalid_inputs_fail_before_rendering(self):
        for key, bad in (("fps", 60), ("warmup_frames", 0), ("move_seconds", 9),
                         ("meters_per_scene_unit", 0), ("speed_m_per_second", float("nan"))):
            with self.subTest(key=key):
                value = fixture()
                value[key] = bad
                with self.assertRaises(ValueError):
                    trajectory.sample_frames(value)
        for mutate in (
            lambda v: v["waypoints"][1].update(position=[11, 1.6, 0]),
            lambda v: v["waypoints"][1].update(position=[0, 1.6, 0]),
            lambda v: v["waypoints"][0].update(target=[0, 1.6, 0]),
            lambda v: v["camera"].update(up=[0, 0, 1]),
            lambda v: v.update(scene_config="../outside.json"),
        ):
            value = fixture()
            mutate(value)
            with self.assertRaises(ValueError):
                trajectory.sample_frames(value)

    def test_actual_camera_verification_rejects_incomplete_or_nonfinite_records(self):
        from scripts.falcor.trajectory_preview import verify_camera_records
        frames = trajectory.sample_frames(fixture())[:1]
        actual = {**frames[0], "actual_fixed_seed": 0, "actual_clock_frame": 1,
                  "actual_camera": {**frames[0]["camera"], "frameHeight": 24,
                                    "focalLength": 12 / math.tan(math.radians(45) / 2),
                                    "apertureRadius": 0, "animated": False, "nearPlane": 0.01}}
        verify_camera_records([actual], frames)
        for key, value in (("position", []), ("target", [0]), ("up", [0, 1]),
                           ("frameHeight", float("nan")), ("focalLength", float("nan")),
                           ("nearPlane", 100)):
            broken = copy.deepcopy(actual)
            broken["actual_camera"][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                verify_camera_records([broken], frames)
        actual["actual_fixed_seed"] = 4
        with self.assertRaises(ValueError):
            verify_camera_records([actual], frames)

    def test_render_script_sets_every_pose_before_render_without_reset(self):
        from pathlib import Path
        from scripts.falcor.trajectory_preview import render_script
        frames = trajectory.sample_frames(fixture())
        source = render_script(Path("test.pyscene"), frames, Path("preview"), {}, captures=[41, 340])
        compile(source, "preview-script", "exec")
        self.assertLess(source.index("camera.position = float3(*pose['position'])"),
                        source.index("m.renderFrame()"))
        self.assertIn("trajectory-records.json", source)
        self.assertIn("if frame in [41, 340]", source)
        self.assertNotIn("tracer.reset()", source)
        self.assertIn("m.clock.framerate = 0", source)


if __name__ == "__main__":
    unittest.main()
