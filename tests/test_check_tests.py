"""Check that dependency-specific test runs cannot hide discovery failures."""
import contextlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts import check_tests


class TestGroupDiscoveryTests(unittest.TestCase):
    def run_fixture(self, *, broken=False, skipped=False, list_only=False):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            tests = root / "tests"
            tests.mkdir()
            body = "self.skipTest('missing compiler')" if skipped else "pass"
            (tests / "test_ci_fixture_native.py").write_text(
                "import unittest\nclass NativeChecks(unittest.TestCase):\n"
                f"    def test_native(self): {body}\n", encoding="utf-8")
            if broken:
                (tests / "test_ci_fixture_broken.py").write_text(
                    "raise RuntimeError('fixture import failure')\n", encoding="utf-8")
            argv = ["check_tests", "--suite", "native"] + (["--list"] if list_only else [])
            output = io.StringIO()
            with (patch.object(check_tests, "ROOT", root),
                  patch.object(check_tests, "INTEGRATION_GROUPS", {
                      "native": ("test_ci_fixture_native.NativeChecks",)}),
                  patch.object(unittest, "defaultTestLoader", unittest.TestLoader()),
                  patch.object(sys, "argv", argv), patch.object(sys, "path", sys.path[:]),
                  patch.dict(sys.modules), contextlib.redirect_stdout(output),
                  contextlib.redirect_stderr(output)):
                result = check_tests.main()
            return result, output.getvalue()

    def test_discovery_error_fails_an_explicit_group_and_its_listing(self):
        for list_only in (False, True):
            with self.subTest(list_only=list_only):
                code, output = self.run_fixture(broken=True, list_only=list_only)
                self.assertNotEqual(code, 0)
                self.assertIn("fixture import failure", output)

    def test_healthy_group_still_runs_and_lists_its_tests(self):
        code, output = self.run_fixture()
        self.assertEqual(code, 0)
        self.assertIn("Ran 1 test", output)
        code, output = self.run_fixture(list_only=True)
        self.assertEqual(code, 0)
        self.assertIn("test_ci_fixture_native.NativeChecks.test_native", output)

    def test_explicit_group_cannot_pass_with_a_skipped_dependency(self):
        code, output = self.run_fixture(skipped=True)
        self.assertNotEqual(code, 0)
        self.assertIn("missing compiler", output)


if __name__ == "__main__":
    unittest.main()
