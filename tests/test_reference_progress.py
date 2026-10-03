"""Per-view checkpoint stopping, reuse, and interrupted-stream continuation."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/run"))
from experiment.artifacts import save_json, write_pfm
from experiment import reference_runner as ref_runner
from experiment.config import make_config, load_definition
from experiment.reference import ImageCache, metrics, reference_config, target
from experiment.scenes import load_scene
from rtxdi_common import sha
import rtxdi_reference as cli


class ProgressTests(unittest.TestCase):
    def fixture(self, directory, value=2.):
        path = directory / "baseline.pfm.gz"
        write_pfm(path, np.full((2, 2, 3), value, dtype=np.float32))
        return [{"image": path, "config": {"preview": {"exposure_ev": 0}}}]

    def fake_stream(self, directory, calls, values):
        def run(seed, samples, previous_samples, previous_image, previous_rgb=None):
            calls.append((seed, samples, previous_samples, previous_image))
            stream = directory / f"seed-{seed}/checkpoint-{samples}/attempt-0"
            stream.mkdir(parents=True, exist_ok=True)
            image = stream / f"frame-{samples//8:04d}.pfm.gz"
            write_pfm(image, np.full((2,2,3), values(samples, seed), dtype=np.float32))
            save_json(stream / "manifest.json", {"status": "completed"})
            return image
        return run

    def test_stops_after_two_passes_and_reuses_existing_checkpoints(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            captures = self.fixture(directory)
            calls=[]
            runner=self.fake_stream(directory, calls, lambda n,s: 1.)
            result = ref_runner.run_pose(directory, captures, [16,32,64,128], 8, [1001,2001], .1, runner)
            self.assertTrue(result["converged"])
            self.assertEqual(result["samples_per_class_per_stream"], 64)
            self.assertEqual(len(calls), 6)
            self.assertEqual(calls[2][2],16)
            self.assertTrue(calls[2][3].is_file())
            again = ref_runner.run_pose(directory, captures, [16,32,64,128], 8, [1001,2001], .1,
                                    lambda *args: self.fail("Rerendered an existing checkpoint"))
            self.assertTrue(again["converged"])

    def test_reassessment_retains_latest_saved_checkpoint(self):
        for latest, accepted in [(1.005, True), (2., False)]:
            with self.subTest(latest=latest), tempfile.TemporaryDirectory() as folder:
                directory = Path(folder)
                captures = self.fixture(directory)
                writer = self.fake_stream(directory, [], lambda n, seed: latest if n == 128 else 1.)
                for samples in [16, 32, 64, 128]:
                    for seed in [1001, 2001]:
                        writer(seed, samples, 0, None)
                result = ref_runner.run_pose(directory, captures, [16, 32, 64, 128], 8,
                                         [1001, 2001], .1, None)
                self.assertEqual(result["samples_per_class_per_stream"], 128)
                self.assertEqual(result["converged"], accepted)
                np.testing.assert_allclose(ref_runner.read_pfm(directory / "reference.pfm.gz"), latest)

    def test_unstable_reference_reaches_cap_and_reassess_never_launches(self):
        with tempfile.TemporaryDirectory() as folder:
            directory=Path(folder); captures=self.fixture(directory, 10.)
            calls=[]
            runner=self.fake_stream(directory,calls,lambda n,s: n/16.)
            result=ref_runner.run_pose(directory,captures,[16,32,64],8,[1001,2001],.1,runner)
            self.assertFalse(result["converged"])
            self.assertEqual(len(calls),6)
            result=ref_runner.run_pose(directory,captures,[16,32,64,128],8,[1001,2001],.1,None)
            self.assertFalse(result["converged"])
            self.assertEqual(result["samples_per_class_per_stream"],64)

    def test_resume_reuses_decoded_stream_pixels(self):
        with tempfile.TemporaryDirectory() as folder:
            directory=Path(folder);captures=self.fixture(directory)
            calls=[]; writer=self.fake_stream(directory,calls,lambda n,s:1.)
            def run(seed,samples,previous_samples,previous_image,previous_rgb):
                if previous_samples:
                    np.testing.assert_array_equal(previous_rgb, np.ones((2,2,3)))
                return writer(seed,samples,previous_samples,previous_image)
            with mock.patch.object(ref_runner,"read_pfm",wraps=ref_runner.read_pfm) as reader:
                ref_runner.run_pose(directory,captures,[16,32,64],8,[1001,2001],.1,run)
                self.assertEqual(reader.call_count,6)

    def test_isolated_outlier_no_longer_controls_acceptance(self):
        with tempfile.TemporaryDirectory() as folder:
            directory=Path(folder)
            baseline=directory/"baseline.pfm.gz"
            write_pfm(baseline,np.full((100,100,3),2,dtype=np.float32))
            captures=[{"image":baseline,"config":{"preview":{"exposure_ev":0}}}]
            a=np.ones((100,100,3));b=a.copy();b[0,0]=51
            assessment=ref_runner.PoseAssessment(captures,.1,ImageCache())
            self.assertFalse(assessment.add(16,[a,b]))
            self.assertFalse(assessment.add(32,[a,b]))
            self.assertTrue(assessment.add(64,[a,b]))
            full=assessment.rows[-1]["regions"]["full"]
            self.assertGreater(full["estimated_reference_nrmse"], .1 * metrics(np.full_like(a,2),(a+b)/2)["nrmse"])
            self.assertTrue(assessment.save(directory)["converged"])

    def test_quadrant_noise_does_not_block_full_image_acceptance(self):
        a = np.ones((20, 20, 3))
        b = a.copy()
        b[0, 0] = 51.
        captures = [{"image": "baseline"}]
        assessment = ref_runner.PoseAssessment(captures, .1, lambda _: np.full_like(a, 2.))
        self.assertFalse(assessment.add(16, [a, b]))
        self.assertFalse(assessment.add(32, [a, b]))
        self.assertTrue(assessment.add(64, [a, b]))
        checks = assessment.rows[-1]["regions"]
        self.assertTrue(checks["full"]["passed"])
        self.assertFalse(checks["quadrant-0-0"]["passed"])

    def test_checkpoint_validation_rejects_changed_images_and_shaders(self):
        base=make_config(load_scene("cornell-box"),load_definition(),"initial","static",resolution=[2,2])
        config=reference_config(base,base["frames"][0],[16],8,1001,"POWER_RIS")
        build={"renderer_commit":config["definition"]["renderer_commit"],"shader_sha256":{"shader":"fixture"}, "executable_sha256":"exe", "integration_sha256":{"patch":"fixture"}}
        with tempfile.TemporaryDirectory() as folder:
            directory=Path(folder);image=directory/"frame-0002.pfm.gz"
            write_pfm(image,np.ones((2,2,3),dtype=np.float32))
            save_json(directory/"config.json",config)
            save_json(directory/"manifest.json",{"status":"completed","config_sha256":sha(directory/"config.json"),
                "scene":{"sha256":"fixture-assets"},"build":build,
                "captures":[{"frame":2,"image_sha256":sha(image)}]})
            sample={"target":target(base,base["frames"][0],"fixture-assets")}
            ref_runner.validate_checkpoint(image,sample,1001,16,8,build)
            with self.assertRaisesRegex(ValueError,"shaders changed"):
                ref_runner.validate_checkpoint(image,sample,1001,16,8,{**build,"shader_sha256":{}})
            write_pfm(image,np.full((2,2,3),2,dtype=np.float32))
            with self.assertRaisesRegex(ValueError,"image was modified"):
                ref_runner.validate_checkpoint(image,sample,1001,16,8,build)

    def test_one_completed_stream_survives_interruption(self):
        with tempfile.TemporaryDirectory() as folder:
            directory=Path(folder);captures=self.fixture(directory)
            calls=[]
            runner=self.fake_stream(directory,calls,lambda n,s:1.)
            runner(1001,16,0,None)
            calls.clear()
            ref_runner.run_pose(directory,captures,[16,32,64],8,[1001,2001],.1,runner)
            self.assertEqual(calls[0][:3],(2001,16,0))
            self.assertEqual(len(calls),5)


class SceneNoiseRatioTests(unittest.TestCase):
    def test_override_isolated_and_available_for_new_scenes(self):
        scenes = {"bistro", "cornell-box", "arcade", "new-scene"}
        self.assertEqual(cli.scene_noise_ratios(.1, [], scenes), dict.fromkeys(scenes, .1))
        self.assertEqual(cli.scene_noise_ratios(.1, ["bistro=0.53", "new-scene=0.2"], scenes),
                         {"bistro": .53, "cornell-box": .1, "arcade": .1, "new-scene": .2})

    def test_invalid_or_unused_overrides_are_rejected(self):
        for values in [["bistro"], ["bistro=no"], ["bistro=nan"], ["bistro=inf"],
                       ["bistro=0"], ["bistro=1"], ["bistr=0.53"],
                       ["bistro=0.53", "bistro=0.2"]]:
            with self.subTest(values=values), self.assertRaises(ValueError):
                cli.scene_noise_ratios(.1, values, {"bistro", "cornell-box"})


if __name__ == "__main__":
    unittest.main()
