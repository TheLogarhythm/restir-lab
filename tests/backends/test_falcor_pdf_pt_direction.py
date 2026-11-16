"""Execute the first-hop recording path and shared vMF/history math on the CPU."""
from pathlib import Path
import subprocess
import tempfile
import unittest

from scripts.falcor import pdf_pt_shader as shader
from tests.fixtures.cpp import compile_cpp, shader_function

ROOT = Path(__file__).resolve().parents[2]


class PdfDirectionTests(unittest.TestCase):
    def test_initial_directions_and_history(self):
        upstream = ROOT / "renderers/falcor/upstream/Source"
        originals = {}
        for name in shader.FILES:
            name_in_source = name.removeprefix("shaders/")
            if name_in_source.startswith("ReSTIRPathTracing/"):
                name_in_source = "Modules/" + name_in_source
            originals[name] = (upstream / name_in_source).read_text(encoding="utf8")
        modified = shader.build_overlay(originals, {"history_limit": 20, "history_decay": .95})
        reservoir = modified[shader.MODULE + "PathReservoir.slang"]
        # Execute the production record and lottery, taking each candidate's
        # arguments directly from the two Falcor call sites under test.
        parts = []
        for name in ("addNEECandidate", "addBSDFHitCandidate"):
            candidate = shader_function(reservoir, name, "bool")
            args = candidate.split("bool selected = ", 1)[1].split(";", 1)[0]
            parts.append(f"bool {name}(float u, unsigned pathLength, float3 wi, "
                         f"float3 pathContribution) {{return {args};}}")
        parts.append(shader_function(reservoir, "addPSSSample", "bool").replace("this.", "this->"))
        parts.append(shader_function(reservoir, "toScalar", "float"))
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "pdf_pt_candidate.inl").write_text("\n".join(parts), encoding="utf8")
            exe = compile_cpp(ROOT / "tests/pdf_pt_direction.cpp", tmp, includes=(tmp,))
            subprocess.run([str(exe)], check=True)
