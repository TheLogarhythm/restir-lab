"""Check shader precompile coverage and the report from the native process."""

import json
import os
from pathlib import Path
import tempfile
import unittest

from PIL import Image
from PIL.PngImagePlugin import PngInfo

from scripts.falcor.live_demo import precompile
from scripts.falcor.live_demo.scenes import SCENE_NAMES
from scripts.falcor.live_demo.acceptance import validate_sequence


class LivePrecompileTests(unittest.TestCase):
    def test_failed_replay_preserves_previously_qualified_pack(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            cache = output / "active-cache"
            key = "1" * 64
            filename = key + ".irpack"
            config = self.warmup_config()

            def first_pass(path, config, environment):
                stage = Path(environment["RESTIR_LIVE_SLANG_CACHE_DIR"])
                mode = environment["RESTIR_LIVE_SLANG_CACHE_MODE"]
                if mode == "write":
                    (stage / filename).write_bytes(b"known good")
                return self.fake_pass(path, mode, key)

            precompile.warm(output / "first", config, cache, first_pass)
            manifest = (cache / "qualified.json").read_bytes()

            def failing_pass(path, config, environment):
                stage = Path(environment["RESTIR_LIVE_SLANG_CACHE_DIR"])
                mode = environment["RESTIR_LIVE_SLANG_CACHE_MODE"]
                if mode == "read":
                    self.assertEqual(environment["RESTIR_LIVE_SLANG_CACHE_QUALIFY"], "1")
                    self.assertNotIn("RESTIR_LIVE_SLANG_CACHE_TRUSTED_DIR", environment)
                    self.assertEqual((stage / filename).read_bytes(), b"bad candidate")
                    raise RuntimeError("simulated Mogwai crash")
                self.assertNotIn("RESTIR_LIVE_SLANG_CACHE_QUALIFY", environment)
                trust = Path(environment["RESTIR_LIVE_SLANG_CACHE_TRUSTED_DIR"])
                self.assertNotEqual(stage, trust)
                self.assertEqual((trust / filename).read_bytes(), b"known good")
                temporary = stage / "new-pack.tmp"
                temporary.write_bytes(b"bad candidate")
                os.replace(temporary, stage / filename)
                return self.fake_pass(path, mode, key)

            with self.assertRaisesRegex(RuntimeError, "simulated Mogwai crash"):
                precompile.warm(output / "second", config, cache, failing_pass)
            self.assertEqual((cache / filename).read_bytes(), b"known good")
            self.assertEqual((cache / "qualified.json").read_bytes(), manifest)
            self.assertFalse((output / "second/precompile.json").exists())
            self.assertEqual(sorted(p.name for p in output.iterdir() if p.is_dir()),
                             ["active-cache", "first", "second"])

    def test_precompile_publishes_only_replayed_packs_and_skips_read_on_repeat(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            cache = output / "active-cache"
            key, rejected = "2" * 64, "3" * 64
            filename = key + ".irpack"
            runs = []

            def run(path, config, environment):
                stage = Path(environment["RESTIR_LIVE_SLANG_CACHE_DIR"])
                mode = environment["RESTIR_LIVE_SLANG_CACHE_MODE"]
                runs.append(mode)
                if len(runs) == 1:
                    (stage / filename).write_bytes(b"accepted")
                    (stage / (rejected + ".irpack")).write_bytes(b"not replayed")
                    return self.fake_pass(path, "write", key, extra=f"Live Slang cache: write 1 modules {rejected}\n")
                if len(runs) == 2:
                    self.assertFalse((cache / filename).exists())
                else:
                    trust = Path(environment["RESTIR_LIVE_SLANG_CACHE_TRUSTED_DIR"])
                    self.assertEqual((trust / filename).read_bytes(), b"accepted")
                pid = self.fake_pass(path, "read", key)
                if mode == "read":
                    # Qualification compares pixels, so a different PNG encoding can still pass.
                    image, = path.glob("*.png")
                    with Image.open(image) as original:
                        rgb = original.copy()
                    metadata = PngInfo()
                    metadata.add_text("Pass", "Replay")
                    rgb.save(image, pnginfo=metadata)
                return pid

            precompile.warm(output / "first", self.warmup_config(), cache, run)
            self.assertEqual((cache / filename).read_bytes(), b"accepted")
            self.assertFalse((cache / (rejected + ".irpack")).exists())
            result = json.loads((output / "first/precompile.json").read_text(encoding="utf8"))
            self.assertEqual(result["passes"], {"write": "write/precompile.json", "read": "read/precompile.json"})
            precompile.warm(output / "repeat", self.warmup_config(), cache, run)
            self.assertEqual(runs, ["write", "read", "write"])

    def test_precompile_rejects_mismatched_render_pixels(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            cache = output / "active-cache"
            key = "4" * 64

            def run(path, config, environment):
                stage = Path(environment["RESTIR_LIVE_SLANG_CACHE_DIR"])
                mode = environment["RESTIR_LIVE_SLANG_CACHE_MODE"]
                if mode == "write":
                    (stage / (key + ".irpack")).write_bytes(b"candidate")
                return self.fake_pass(path, mode, key, pixel=(30, 50, 70) if mode == "read" else (50, 70, 90))

            with self.assertRaisesRegex(ValueError, "rendered pixels differ.*Classroom"):
                precompile.warm(output / "run", self.warmup_config(), cache, run)
            self.assertFalse((cache / (key + ".irpack")).exists())

    def test_stale_same_key_can_be_refreshed_while_other_seeds_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            cache = output / "active-cache"
            key, other = "d" * 64, "e" * 64
            refreshed_file, reused_file = key + ".irpack", other + ".irpack"

            def collect_first(path, config, environment):
                stage = Path(environment["RESTIR_LIVE_SLANG_CACHE_DIR"])
                mode = environment["RESTIR_LIVE_SLANG_CACHE_MODE"]
                if mode == "write":
                    (stage / refreshed_file).write_bytes(b"old")
                    (stage / reused_file).write_bytes(b"shared")
                event = "write" if mode == "write" else "hit"
                return self.fake_pass(path, mode, key, extra=f"Live Slang cache: {event} 1 modules {other}\n")

            precompile.warm(output / "first", self.warmup_config(), cache, collect_first)

            def collect_refresh(path, config, environment):
                stage = Path(environment["RESTIR_LIVE_SLANG_CACHE_DIR"])
                mode = environment["RESTIR_LIVE_SLANG_CACHE_MODE"]
                if mode == "write":
                    trust = Path(environment["RESTIR_LIVE_SLANG_CACHE_TRUSTED_DIR"])
                    self.assertEqual((trust / refreshed_file).read_bytes(), b"old")
                    self.assertFalse((stage / refreshed_file).exists())
                    (stage / refreshed_file).write_bytes(b"refreshed")
                else:
                    self.assertEqual((stage / refreshed_file).read_bytes(), b"refreshed")
                    self.assertEqual((stage / reused_file).read_bytes(), b"shared")
                    self.assertEqual((cache / refreshed_file).read_bytes(), b"old")
                return self.fake_pass(path, mode, key, extra=f"Live Slang cache: hit 1 modules {other}\n")

            precompile.warm(output / "refresh", self.warmup_config(), cache, collect_refresh)
            self.assertEqual((cache / refreshed_file).read_bytes(), b"refreshed")
            self.assertEqual((cache / reused_file).read_bytes(), b"shared")

    def test_fresh_cache_requires_at_least_one_qualified_write(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            cache = output / "new-parent" / "active-cache"
            key, unrelated = "b" * 64, "c" * 64

            def run(path, config, environment):
                stage = Path(environment["RESTIR_LIVE_SLANG_CACHE_DIR"])
                mode = environment["RESTIR_LIVE_SLANG_CACHE_MODE"]
                if mode == "write":
                    (stage / (key + ".irpack")).write_bytes(b"candidate")
                return self.fake_pass(path, mode, key if mode == "write" else unrelated)

            with self.assertRaisesRegex(ValueError, "No Slang cache packs qualified"):
                precompile.warm(output / "run", self.warmup_config(), cache, run)
            self.assertFalse(cache.exists())

    @staticmethod
    def warmup_config():
        return {"sequence": precompile.precompile_steps("Classroom")[:1], "width": 64, "height": 64}

    def fake_pass(self, path, mode, key, *, extra="", pixel=(50, 70, 90)):
        path.mkdir(parents=True, exist_ok=True)
        event = "write" if mode == "write" else "hit"
        self.frame_evidence(path, {"Classroom": f"Live Slang cache: {event} 1 modules {key}\n" + extra}, pixel=pixel)
        return 19

    def test_each_scene_starts_in_the_interactive_default_and_warms_every_branch(self):
        rows = precompile.precompile_steps()
        validate_sequence(rows)
        self.assertEqual(list(dict.fromkeys(row["Scene"] for row in rows)), list(SCENE_NAMES))
        for scene in SCENE_NAMES:
            with self.subTest(scene=scene):
                group = [row for row in rows if row["Scene"] == scene]
                self.assertEqual((group[0]["Method"], group[0]["Display"]), ("CGNS", "Raw"))
                self.assertEqual((group[-1]["Method"], group[-1]["Display"]), ("CGNS", "Raw"))
                self.assertEqual({(row["Method"], row["Display"]) for row in group}, {
                    (method, mode) for method in ("Original", "PDF Similarity", "CGNS")
                    for mode in ("Raw", "Accumulation", "NRD")
                })
                self.assertTrue(all(row["frames"] >= 2 for row in group))
                self.assertEqual([(row["Method"], row["Display"]) for row in group if row["verify_image"]],
                                 [("CGNS", "Raw"), ("Original", "Accumulation"), ("PDF Similarity", "NRD")])
                for first, second in zip(group, group[1:]):
                    self.assertNotEqual(first["Method"] == second["Method"], first["Display"] == second["Display"])

        classroom = precompile.precompile_steps("Classroom")
        self.assertEqual(classroom, [row for row in rows if row["Scene"] == "Classroom"])

    def test_report_requires_real_cache_activity_and_accepts_a_repeated_run(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            cache = output / ".slangcache"
            cache.mkdir()
            startup = f"(Info) Live Slang cache: write 1 modules {'5' * 64}\n"
            classroom = f"(Info) Live Slang cache: hit 1 modules {'6' * 64}\n"
            config, _ = self.frame_evidence(output, {
                "Classroom": classroom, "Sun Temple": "(Info) Live Slang cache: miss temple-module\n",
            }, startup=startup)
            with self.assertRaisesRegex(ValueError, "cache .*writes or hits.*Sun Temple"):
                precompile.verify(output, config, 19, cache)
            self.assertFalse((output / "precompile.json").exists())
            config, record = self.frame_evidence(output, {
                "Classroom": classroom, "Sun Temple": f"(Info) Live Slang cache: hit 1 modules {'7' * 64}\n",
            }, startup=startup)
            precompile.verify(output, config, 19, cache)
            result = json.loads((output / "precompile.json").read_text(encoding="utf8"))
            self.assertEqual(result["status"], "passed")
            self.assertEqual(result["cache"]["hits"], 2)
            self.assertEqual(result["cache"]["writes"], 0)
            self.assertEqual(result["frames"][0]["file"], record["file"])
            self.assertEqual(result["cache"]["scenes"], {
                "Classroom": {"hits": 1, "writes": 0, "misses": 0},
                "Sun Temple": {"hits": 1, "writes": 0, "misses": 0},
            })

    def test_report_rejects_persistence_failure_even_with_successful_cache_activity(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            config, _ = self.frame_evidence(output, {
                "Classroom": f"(Info) Live Slang cache: write 1 modules {'8' * 64}\n"
                             "(Warning) Live Slang cache: write failed second\n",
            })
            cache = output / ".slangcache"
            cache.mkdir()
            with self.assertRaisesRegex(ValueError, "cache write failed"):
                precompile.verify(output, config, 19, cache)

    def test_read_replay_rejects_native_write_events(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            config, _ = self.frame_evidence(output, {
                "Classroom": f"Live Slang cache: hit 1 modules {'5' * 64}\n"
                             f"Live Slang cache: write 1 modules {'6' * 64}\n",
            })
            cache = output / ".slangcache"
            cache.mkdir()
            with self.assertRaisesRegex(ValueError, "wrote to a read-only replay"):
                precompile.verify(output, config, 19, cache, mode="read")

    def test_report_excludes_cache_activity_before_scene_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            config, _ = self.frame_evidence(output, {
                "Classroom": "(Info) Live Slang cache: miss classroom-module\n",
            }, startup=f"(Info) Live Slang cache: write 1 modules {'9' * 64}\n")
            cache = output / ".slangcache"
            cache.mkdir()
            with self.assertRaisesRegex(ValueError, "cache .*writes or hits.*Classroom"):
                precompile.verify(output, config, 19, cache)

    def test_report_rejects_blank_render(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            config, record = self.frame_evidence(output, {"Classroom": f"Live Slang cache: write 1 modules {'a' * 64}\n"})
            cache = output / ".slangcache"
            cache.mkdir()
            Image.new("RGB", (64, 64)).save(output / record["file"])
            with self.assertRaisesRegex(ValueError, "constant rendered image"):
                precompile.verify(output, config, 19, cache)

    @staticmethod
    def frame_evidence(output, scene_logs, *, startup="", pixel=(50, 70, 90)):
        image = Image.new("RGB", (64, 64))
        image.putpixel((32, 32), pixel)
        rows, records = [], []
        log = startup.encode()
        for scene, text in scene_logs.items():
            row = precompile.precompile_steps(scene)[0]
            rows.append(row)
            start = len(log)
            log += text.encode()
            record = {**row, "frame": 2, "settled_frames": 2, "method_id": 2,
                      "display_input": "PathTracer.color", "tone_mapper_raw_input": True,
                      "accumulation_bypassed": True, "tone_mapper_display_mode": 0,
                      "nrd_passes_enabled": False, "visible": True, "pid": 19, "hwnd": 21,
                      "resolution": [64, 64], "file": row["label"] + ".png",
                      "scene_cache_log_start": start, "cache_log_end": len(log)}
            records.append(record)
            image.save(output / record["file"])
        (output / "mogwai.log").write_bytes(log)
        config = {"sequence": rows, "width": 64, "height": 64}
        evidence = {"pid": 19, "hwnd": 21, "total_frames": len(rows) * 2, "captures": records}
        (output / "renderer-complete.json").write_text(json.dumps(evidence), encoding="utf8")
        return config, records[0]
