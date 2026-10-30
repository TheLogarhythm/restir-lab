"""Cross-process exclusion for the Falcor adapters, without a GPU or build."""

from contextlib import contextmanager
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
WORKER = r"""
import json, sys, time
from pathlib import Path
from unittest.mock import patch
from scripts.falcor import build, run

root, action, label = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
record = json.loads((root / 'build/falcor/build.json').read_text())
config = dict(width=3, height=2, frames=1, captures=[1], timeout=5, mode='path-tracer')

def verify_build():
    if label == 'owner':
        (root / 'ready').touch()
        deadline = time.monotonic() + 15
        while not (root / 'release').exists():
            if time.monotonic() >= deadline:
                raise TimeoutError('fixture release missing')
            time.sleep(0.01)
    return record

def execute(command, output, timeout, *, prepare, **kwargs):
    output.mkdir(parents=True)
    prepare(output)
    return output / 'manifest.json'

with patch.object(run, 'ROOT', root), patch.object(
    run, '__file__', str(root / 'scripts/falcor/run.py')
), patch.object(build, 'OUTPUT', root / 'build/falcor'), patch.object(
    build, 'verify_build', side_effect=verify_build
), patch.object(run.subprocess, 'check_output', return_value=''), patch.object(
    run, 'version', return_value='fixture'
), patch.object(run, 'execute', side_effect=execute):
    if action == 'run':
        run.launch(config, root / 'runs' / label, root / 'bin/Mogwai.exe')
    else:
        with patch.object(sys, 'argv', ['build.py']), patch.object(
            build, 'ensure_source', side_effect=RuntimeError('build reached mutable setup')
        ):
            build.main()
"""


class FalcorConcurrencyTests(unittest.TestCase):
    def command(self, root, action, label):
        return [sys.executable, "-B", "-c", WORKER, str(root), action, label]

    @contextmanager
    def pending_launch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = {
                "build/falcor/build.json": json.dumps(
                    {"commit": "a" * 40, "executable": "bin/Mogwai.exe"}
                ),
                "scripts/falcor/run.py": "# fixture launcher",
                "scripts/falcor/graphs.py": "# fixture graph",
                "scenes/configs/falcor/cornell-box.pyscene": "# fixture scene",
                "renderers/rtxdi/Assets/Media/CornellBox/CornellBox.gltf": "{}",
            }
            for name, data in files.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(data)
            owner = subprocess.Popen(
                self.command(root, "run", "owner"),
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            try:
                deadline = time.monotonic() + 10
                while not (root / "ready").exists():
                    if owner.poll() is not None:
                        self.fail(
                            "Owner failed before preflight: " + owner.communicate()[0]
                        )
                    if time.monotonic() >= deadline:
                        self.fail("Owner did not reach preflight")
                    time.sleep(0.01)
                yield root, owner
            finally:
                (root / "release").touch()
                try:
                    owner.communicate(timeout=10)
                except subprocess.TimeoutExpired:
                    owner.kill()
                    owner.communicate(timeout=5)

    def contender(self, root, action, label="contender"):
        return subprocess.run(
            self.command(root, action, label),
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )

    def test_second_launch_is_rejected_before_first_renderer_exists(self):
        # The first runner is still checking its build: a process-name probe sees no renderer.
        with self.pending_launch() as (root, owner):
            second = self.contender(root, "run")
            self.assertNotEqual(second.returncode, 0, second.stdout)
            self.assertIn("Another Falcor", second.stderr)
            self.assertFalse((root / "runs/contender").exists())
            self.assertIsNone(owner.poll())

    def test_build_cannot_mutate_inputs_while_launch_is_preparing(self):
        with self.pending_launch() as (root, owner):
            second = self.contender(root, "build")
            self.assertNotEqual(second.returncode, 0)
            self.assertIn("Another Falcor", second.stderr)
            self.assertNotIn("build reached mutable setup", second.stderr)
            self.assertIsNone(owner.poll())

    def test_abrupt_exit_releases_exclusion_for_next_launch(self):
        with self.pending_launch() as (root, owner):
            owner.terminate()
            owner.wait(timeout=5)
            later = self.contender(root, "run", "later")
            self.assertEqual(later.returncode, 0, later.stderr)
            self.assertTrue((root / "runs/later/build.json").is_file())


if __name__ == "__main__":
    unittest.main()
