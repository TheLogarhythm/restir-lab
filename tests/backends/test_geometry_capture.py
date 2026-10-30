"""Geometry captures are lossless, versioned and usable by shared masks."""
from pathlib import Path
import importlib
import csv
import json
import sys
import tempfile
import unittest
from unittest import mock
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/run"))
from experiment import artifacts
from experiment.config import load_definition, make_config
from experiment.scenes import load_scene


class GeometryCaptureTests(unittest.TestCase):
    def module(self):
        return importlib.import_module("experiment.geometry_io")

    def config(self):
        definition = load_definition()
        definition["geometry_export"] = True
        config = make_config(load_scene("cornell-box"), definition, "initial", "static", resolution=(3, 1))
        config["frames"] = config["frames"][:1]
        config["frames"][0]["capture"] = True
        config["scene"]["camera"]["vertical_fov"] = 90.
        return config

    def raw(self, directory, depths=(1., 2., 65504.)):
        stem = directory / "frame-0001"
        np.array(depths, dtype="<f4").tofile(stem.with_suffix(".depth32f"))
        np.array([0x7fff7fff, 0x7ffffffe, 0], dtype="<u4").tofile(stem.with_suffix(".normals32u"))
        return stem

    def test_export_switch_rejects_nonboolean_definition_before_render(self):
        for value in (1, "true", None, []):
            definition = load_definition()
            definition["geometry_export"] = value
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "geometry_export"):
                make_config(load_scene("cornell-box"), definition, "initial", "static")
        self.assertTrue(self.config()["geometry_export"])

    def test_default_configuration_preserves_legacy_serialized_shape(self):
        definition = load_definition()
        config = make_config(load_scene("cornell-box"), definition, "initial", "static")
        self.assertNotIn("geometry_export", config)
        self.assertNotIn("geometry_export", config["definition"])

    def test_octahedral_decode_uses_donut_65534_scaling_and_fold(self):
        words = np.array([[0x7fff7fff, 0x7ffffffe, 0xfffe7fff, 0, 0xffffffff]], dtype=np.uint32)
        result = self.module().decode_normals(words)
        np.testing.assert_allclose(result, [[[0, 0, 1], [1, 0, 0], [0, 1, 0], [0, 0, -1], [0, 0, -1]]], atol=1e-15)
        self.assertEqual(result.dtype, np.float64)

    def test_oblique_lower_hemisphere_normal_folds_both_components(self):
        # Hand-decoded signed integer numerators: x=43688, y=54610,
        # z=-32764 before folding; subtract32764 from both x and y.
        expected = np.array([10924., 21846., -32764.])
        expected /= np.linalg.norm(expected)
        result = self.module().decode_normals(np.array([[0xeaa8d553]], dtype="<u4"))
        np.testing.assert_allclose(result[0, 0], expected, atol=2e-16, rtol=2e-16)

    def test_non_square_two_dimensional_rays_match_literal_inverse_projection(self):
        # Donut's row-vector reversed infinite perspective at FOV90, aspect2,
        # near .01. Invert this literal matrix independently of the decoder.
        projection = np.array([[.5, 0, 0, 0], [0, 1, 0, 0],
                               [0, 0, 0, 1], [0, 0, .01, 0]])
        clip = np.array([[[-.75, .5, .5, 1], [-.25, .5, .5, 1],
                          [.25, .5, .5, 1], [.75, .5, .5, 1]],
                         [[-.75, -.5, .5, 1], [-.25, -.5, .5, 1],
                          [.25, -.5, .5, 1], [.75, -.5, .5, 1]]])
        view = clip @ np.linalg.inv(projection)
        rays = view[..., :3] / view[..., 2, None]
        depth = np.array([[1, 2, 3, 4], [5, 6, 7, 8]], dtype="<f4")
        expected = np.linalg.norm(rays * depth[..., None], axis=-1)
        with tempfile.TemporaryDirectory() as folder:
            stem = Path(folder) / "frame"
            depth.tofile(stem.with_suffix(".depth32f"))
            np.full((2, 4), 0x7fff7fff, dtype="<u4").tofile(stem.with_suffix(".normals32u"))
            geometry = self.module().load_raw_geometry(stem, 4, 2, 90.)
        # Multiplying before or after the norm differs by ordinary float64 rounding.
        np.testing.assert_allclose(geometry["camera_distance"], expected, rtol=2e-15)

    def test_radial_distance_uses_pixel_centers_fov_and_aspect(self):
        # 3x1, 90-degree vertical FOV: rays at x=-2,0,+2; radial multipliers sqrt(5),1,sqrt(5).
        with tempfile.TemporaryDirectory() as folder:
            path = self.raw(Path(folder))
            geometry = self.module().load_raw_geometry(path, 3, 1, 90.)
        np.testing.assert_allclose(geometry["camera_distance"], [[np.sqrt(5), 2., 0.]])
        np.testing.assert_array_equal(geometry["valid"], [[True, True, False]])
        np.testing.assert_array_equal(geometry["shading_normals"], [[[0, 0, 1], [1, 0, 0], [0, 0, 0]]])

    def test_save_round_trip_preserves_raw_words_and_verified_capture_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            stem = self.raw(directory)
            record = self.module().save_geometry(stem, 3, 1, 90.)
            path = directory / record["geometry"]
            restored = self.module().read_geometry(path)
            np.testing.assert_allclose(restored["camera_distance"], [[np.sqrt(5), 2., 0.]])
            self.assertEqual(record["geometry_valid_fraction"], 2/3)
            self.assertEqual(len(record["geometry_sha256"]), 64)
            with np.load(path, allow_pickle=False) as archive:
                np.testing.assert_array_equal(archive["view_depth"], [[1., 2., 65504.]])
                np.testing.assert_array_equal(archive["packed_normals"], [[0x7fff7fff, 0x7ffffffe, 0]])
                self.assertEqual(archive["schema_version"], 1)
                self.assertEqual(set(archive.files), {"schema_version", "vertical_fov_degrees", "view_depth", "packed_normals"})
            self.assertTrue(stem.with_suffix(".depth32f").is_file())
            self.assertTrue(stem.with_suffix(".normals32u").is_file())

    def test_raw_rejects_missing_extra_truncated_nonfinite_nonpositive_depth(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            for extension in (".depth32f", ".normals32u"):
                for length in (0, 11, 13, 16):
                    stem = self.raw(directory)
                    stem.with_suffix(extension).write_bytes(bytes(length))
                    with self.subTest(extension=extension, length=length), self.assertRaises(RuntimeError):
                        self.module().load_raw_geometry(stem, 3, 1, 90.)
            for value in (np.nan, np.inf, -1., 0.):
                stem = self.raw(directory, (1, value, 65504))
                with self.subTest(depth=value), self.assertRaises(RuntimeError):
                    self.module().load_raw_geometry(stem, 3, 1, 90.)
            for fov in (0, 180, np.nan, np.inf, True):
                with self.subTest(fov=fov), self.assertRaises(ValueError):
                    self.module().load_raw_geometry(self.raw(directory), 3, 1, fov)

    def test_read_rejects_wrong_schema_dtype_shape_nonfinite_and_unexpected_fields(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            record = self.module().save_geometry(self.raw(directory), 3, 1, 90.)
            path = directory / record["geometry"]
            with np.load(path, allow_pickle=False) as archive:
                original = dict(archive)
            changes = [("schema_version", np.array(2)), ("valid", np.ones((1, 3), dtype=np.uint8)),
                       ("view_depth", np.zeros((1, 2), dtype="<f4")), ("view_depth", np.full((1, 3), np.nan, dtype="<f4")),
                       ("view_depth", np.ones((1, 3), dtype="<f8")), ("packed_normals", np.zeros((1, 3, 3), dtype="<u4")),
                       ("packed_normals", np.zeros((1, 3), dtype="<f4"))]
            for key, value in changes:
                changed = {**original, key: value}
                np.savez_compressed(path, **changed)
                with self.subTest(key=key, shape=value.shape), self.assertRaises(RuntimeError):
                    self.module().read_geometry(path)

    def test_runtime_requires_matching_format_switch_and_all_requested_captures(self):
        config = self.config()
        module = self.module()
        resolved = {"geometry_export": True, "geometry_format": module.GEOMETRY_FORMAT}
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            self.raw(directory)
            module.validate_geometry_outputs(directory, config, resolved)
            for key, value in (("geometry_export", None), ("geometry_export", False), ("geometry_export", 1),
                               ("geometry_format", None), ("geometry_format", "other")):
                altered = dict(resolved)
                if value is None: altered.pop(key)
                else: altered[key] = value
                with self.subTest(key=key, value=value), self.assertRaisesRegex(RuntimeError, "geometry|Geometry"):
                    module.validate_geometry_outputs(directory, config, altered)
            self.raw(directory).with_suffix(".normals32u").unlink()
            with self.assertRaises(RuntimeError): module.validate_geometry_outputs(directory, config, resolved)

    def test_run_validation_enforces_geometry_confirmation_before_finalization(self):
        from tests.fixtures.cgns import cgns_runtime_record
        config, resolved, row = cgns_runtime_record(False)
        config["geometry_export"] = config["definition"]["geometry_export"] = True
        config["width"], config["height"] = 3, 1
        config["scene"]["camera"]["vertical_fov"] = 90.
        config["frames"][0]["capture"] = True
        resolved.update(width=3, height=1, vertical_fov_degrees=90., geometry_export=True,
                        geometry_format=self.module().GEOMETRY_FORMAT)
        row["capture"] = 1
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            self.raw(directory)
            with (directory / "timings.csv").open("w", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=row)
                writer.writeheader()
                writer.writerow(row)
            path = directory / "resolved.json"
            path.write_text(json.dumps(resolved))
            artifacts.validate_run_outputs(directory, config)
            resolved.pop("geometry_format")
            path.write_text(json.dumps(resolved))
            with self.assertRaisesRegex(RuntimeError, "geometry"):
                artifacts.validate_run_outputs(directory, config)

    def test_finalization_keeps_lossless_geometry_and_removes_only_verified_raw(self):
        config = self.config()
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            stem = self.raw(directory)
            np.ones((1, 3, 4), dtype="<f2").tofile(stem.with_suffix(".rgba16f"))
            with mock.patch.object(artifacts, "validate_run_outputs"):
                records = artifacts.finalize_outputs(directory, config)
            path = directory / records[0]["geometry"]
            self.assertTrue(path.is_file())
            self.assertFalse(stem.with_suffix(".depth32f").exists())
            self.assertFalse(stem.with_suffix(".normals32u").exists())
            self.assertEqual(json.loads((directory / "captures.json").read_text()), records)
            self.module().read_geometry(path)


if __name__ == "__main__":
    unittest.main()
