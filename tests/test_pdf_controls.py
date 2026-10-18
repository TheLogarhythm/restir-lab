"""Deterministic temporal states for the approved PDF comparison."""
import copy
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/run"))
from experiment.config import load_definition, make_config
from experiment.scenes import load_scene

PINK = "LMBR_000019a_Paris_StringLights_01_Pink_Color"


def temporal_definition():
    definition = load_definition()
    definition.update(frames=96, logical_fps=30, motion={"start_frame": 32, "end_frame": 64})
    definition["captures"] = {name: [1, 32, 33, 64, 65, 96]
                              for name in ("static", "motion", "reset", "lighting")}
    return definition


class PdfTemporalControlsTests(unittest.TestCase):
    def test_motion_has_32_increments_and_time_is_independent_of_render_speed(self):
        scene = load_scene("cornell-box")
        scene["camera"].update(position=[0, 0, 0], direction=[0, 0, 1], up=[0, 1, 0])
        scene["motion"].update(end_position=[32, 0, 0], end_direction=[1, 0, 0], end_up=[0, 1, 0])
        frames = make_config(scene, temporal_definition(), "combined", "motion")["frames"]
        self.assertEqual(frames[31]["position"], [0., 0., 0.])
        self.assertEqual(frames[32]["position"], [1., 0., 0.])
        self.assertEqual(frames[63]["position"], [32., 0., 0.])
        self.assertEqual(frames[64]["position"], frames[63]["position"])
        self.assertEqual(frames[95]["position"], frames[63]["position"])
        self.assertAlmostEqual(frames[47]["direction"][0], math.sqrt(.5))
        self.assertAlmostEqual(frames[47]["direction"][2], math.sqrt(.5))
        self.assertEqual([f["frame"] for f in frames if f["reset"]], [1])
        self.assertEqual([f["logical_time_seconds"] for f in frames], [i / 30 for i in range(96)])

    def test_half_turn_and_roll_never_produce_zero_or_nonorthogonal_camera_vectors(self):
        for direction, up in (([0, 0, -2], [0, 3, 0]), ([0, 0, 3], [0, -2, 0])):
            with self.subTest(direction=direction, up=up):
                scene = load_scene("cornell-box")
                scene["camera"].update(direction=[0, 0, 2], up=[0, 3, 0])
                scene["motion"].update(end_direction=direction, end_up=up)
                frames = make_config(scene, temporal_definition(), "combined", "motion")["frames"]
                for frame in frames:
                    d, u = frame["direction"], frame["up"]
                    self.assertAlmostEqual(sum(x*x for x in d), 1.)
                    self.assertAlmostEqual(sum(x*x for x in u), 1.)
                    self.assertAlmostEqual(sum(x*y for x, y in zip(d, u)), 0.)
                self.assertAlmostEqual(frames[63]["direction"][2], direction[2] / abs(direction[2]))
                self.assertAlmostEqual(frames[63]["up"][1], up[1] / abs(up[1]))

    def test_lighting_is_17_exact_states_with_static_camera_and_no_midclip_reset(self):
        definition = temporal_definition()
        definition["lighting"] = {"material": PINK, "start_frame": 32, "end_frame": 64,
                                  "peak_multiplier": 2.}
        frames = make_config(load_scene("bistro"), definition, "combined", "lighting")["frames"]
        values = [f["lighting"]["emissive_intensity_multiplier"] for f in frames]
        self.assertEqual(values[:32], [1.] * 32)
        self.assertGreater(values[32], 1.)
        self.assertEqual(values[47], 2.)
        self.assertEqual(values[63:], [1.] * 33)
        self.assertEqual(values[31:48], list(reversed(values[47:64])))
        self.assertEqual(len(set(values)), 17)
        self.assertEqual(len({tuple(f["position"]) for f in frames}), 1)
        self.assertEqual([f["frame"] for f in frames if f["reset"]], [1])
        self.assertTrue(all(f["lighting"]["material"] == PINK for f in frames))
        self.assertEqual(make_config(load_scene("bistro"), definition, "combined", "lighting")
                         ["arguments"]["scene.animation"], 0)

    def test_legacy_static_has_original_camera_and_no_new_frame_fields(self):
        scene = load_scene("cornell-box")
        frames = make_config(scene, load_definition(), "combined", "static")["frames"]
        self.assertEqual(len(frames), 128)
        self.assertTrue(all(f["direction"] == scene["camera"]["direction"] for f in frames))
        self.assertTrue(all("lighting" not in f and "logical_time_seconds" not in f for f in frames))

    def test_invalid_optional_controls_are_rejected_before_rendering(self):
        bad_definitions = []
        for fps in (0, -30, True, "30", float("nan")):
            bad_definitions.append({"logical_fps": fps})
        light = {"material": PINK, "start_frame": 32, "end_frame": 64, "peak_multiplier": 2.}
        for key, value in (("material", ""), ("material", 17), ("start_frame", True),
                           ("end_frame", 63), ("end_frame", 97), ("peak_multiplier", 0),
                           ("peak_multiplier", True), ("peak_multiplier", float("inf"))):
            bad_definitions.append({"lighting": {**light, key: value}})
        for changes in bad_definitions:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                definition = temporal_definition()
                definition.update(changes)
                make_config(load_scene("bistro"), definition, "combined", "static")
        for key, value in (("end_direction", [0, 0, 0]), ("end_direction", [0, 1, 0]),
                           ("end_up", [0, 0, 0]), ("end_up", [float("nan"), 1, 0])):
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                scene = load_scene("cornell-box")
                scene["camera"].update(direction=[0, 0, 1], up=[0, 1, 0])
                scene["motion"][key] = value
                make_config(scene, temporal_definition(), "combined", "motion")

    def test_lighting_scenario_requires_explicit_schedule_and_capture_list(self):
        with self.assertRaisesRegex(ValueError, "lighting"):
            make_config(load_scene("bistro"), temporal_definition(), "combined", "lighting")
        definition = temporal_definition()
        definition["lighting"] = {"material": PINK, "start_frame": 32, "end_frame": 64,
                                  "peak_multiplier": 2.}
        del definition["captures"]["lighting"]
        with self.assertRaisesRegex(ValueError, "lighting"):
            make_config(load_scene("bistro"), definition, "combined", "lighting")


class PdfResolvedFrameTests(unittest.TestCase):
    def fixture(self):
        definition = temporal_definition()
        definition["lighting"] = {"material": PINK, "start_frame": 32, "end_frame": 64,
                                  "peak_multiplier": 2.}
        scene = load_scene("bistro")
        scene["camera"].update(direction=[0, 0, 1], up=[0, 1, 0])
        config = make_config(scene, definition, "combined", "lighting")
        config["frames"] = [config["frames"][i] for i in (0, 47, 63)]
        records = []
        for i, frame in enumerate(config["frames"]):
            record = {key: frame[key] for key in ("frame", "sampling_frame", "position", "direction",
                                                "up", "logical_time_seconds", "lighting")}
            # The runtime LookAt camera resolves unit forward/up vectors.
            record["direction"] = [x / math.hypot(*frame["direction"]) for x in frame["direction"]]
            record["up"] = [0., 1., 0.]
            record.update(history_reset=frame["reset"], local_lights=100, infinite_lights=1,
                          environment_present=1, local_light_buffer_offset=0 if i % 2 == 0 else 200)
            record["material_update"] = {"material_id": 12, "original_emissive_intensity": 3.,
                "emissive_intensity": 3. * frame["lighting"]["emissive_intensity_multiplier"],
                "emissive_color": [1., .1, .2], "emitting_geometries": 2, "emitting_triangles": 24,
                "dirty_before_upload": True}
            record["light_correspondence"] = {"emissive_triangles": 100,
                "mapped_emissive_triangles": 100 if i else 0,
                "same_offset_emissive_triangles": 100 if i else 0,
                "primitive_lights": 2, "mapped_primitive_lights": 2 if i else 0,
                "same_offset_primitive_lights": 2 if i else 0,
                "sampling_pdf_mip0_refreshed": True, "sampling_pdf_mips_refreshed": True}
            records.append(record)
        return config, records

    def validate(self, config, records):
        from experiment.artifacts import validate_frame_states
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            if records is not None:
                (output / "resolved-frames.jsonl").write_text(
                    "".join(json.dumps(record) + "\n" for record in records))
            validate_frame_states(output, config)

    def test_resolved_states_confirm_absolute_emission_and_complete_correspondence(self):
        self.validate(*self.fixture())

    def test_missing_new_runtime_confirmation_is_rejected(self):
        config, _ = self.fixture()
        with self.assertRaisesRegex(RuntimeError, "frame states"):
            self.validate(config, None)
        legacy = make_config(load_scene("cornell-box"), load_definition(), "combined", "static")
        self.validate(legacy, None)

    def test_wrong_time_light_update_pose_or_correspondence_is_rejected(self):
        for key, value in (("logical_time_seconds", 999), ("direction", [0, 0, 0]),
                           ("local_lights", 101), ("history_reset", True)):
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                config, records = self.fixture()
                records[1][key] = value
                self.validate(config, records)
        for group, key, value in (("material_update", "emissive_intensity", 12.),
                ("material_update", "dirty_before_upload", False),
                ("material_update", "material_id", 13),
                ("material_update", "emitting_triangles", 0),
                ("lighting", "material", "another material"),
                ("lighting", "emissive_intensity_multiplier", 1.),
                ("light_correspondence", "mapped_emissive_triangles", 99),
                ("light_correspondence", "same_offset_primitive_lights", 1),
                ("light_correspondence", "sampling_pdf_mips_refreshed", False)):
            with self.subTest(group=group, key=key), self.assertRaises(RuntimeError):
                config, records = self.fixture()
                records[1] = copy.deepcopy(records[1])
                records[1][group][key] = value
                self.validate(config, records)


if __name__ == "__main__":
    unittest.main()
