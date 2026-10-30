"""Execute the shared CGNS shader math on CPU."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tests.fixtures.cpp import compile_cpp
PAYLOAD = ROOT / "scripts/run/rtxdi_experiments"


class CgnsMathTests(unittest.TestCase):
    def test_shared_scoring_sampling_and_disk_mapping(self):
        self.assertTrue((PAYLOAD / "CgnsMath.h").is_file(), "CGNS shared math is not implemented")
        temporary = ROOT / "tmp"
        temporary.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="cgns-math-", dir=temporary) as directory:
            executable = compile_cpp(ROOT / "tests/cgns_math.cpp", directory, includes=(PAYLOAD,))
            result = subprocess.run([str(executable)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
