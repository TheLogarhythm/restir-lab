"""Execute the patched light-preparation shader's packed geometry lookup."""
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from fixtures.cpp import compile_cpp, compiler_environment

ROOT = Path(__file__).resolve().parents[1]
SHADER = Path("Samples/FullSample/Shaders/PrepareLights.hlsl")


class LightGeometryIndexTests(unittest.TestCase):
    def test_global_geometry_base_survives_packed_local_index(self):
        toolchain = compiler_environment()
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            shader = directory / SHADER
            shader.parent.mkdir(parents=True)
            shutil.copyfile(ROOT / "renderers/rtxdi" / SHADER, shader)
            subprocess.run(["git", "apply", "--include=" + SHADER.as_posix(),
                            str(ROOT / "scripts/run/rtxdi_experiments.patch")],
                           cwd=directory, check=True, capture_output=True, text=True)
            expressions = re.findall(r"GeometryData geometry = t_GeometryData\[(.*?)\];",
                                     shader.read_text(encoding="utf-8"))
            self.assertEqual(len(expressions), 1)
            source = directory / "light_geometry_index.cpp"
            source.write_text("""#include <cstdio>
#include <initializer_list>
int main()
{
    struct { unsigned firstGeometryIndex; } instance;
    struct { unsigned instanceAndGeometryIndex; } task;
    for (unsigned base : {0u, 1u, 4095u, 4096u, 5000u, 16384u})
        for (unsigned local : {0u, 1u, 3u, 4095u})
            for (unsigned meshInstance : {0u, 1u, 8123u, 0x7ffffu})
            {
                instance.firstGeometryIndex = base;
                task.instanceAndGeometryIndex = (meshInstance << 12) | local;
                unsigned actual = """ + expressions[0] + """;
                if (actual != base + local)
                {
                    std::printf("base=%u local=%u instance=%u: got %u, expected %u\\n",
                                base, local, meshInstance, actual, base + local);
                    return 1;
                }
            }
    return 0;
}
""", encoding="utf-8")
            executable = compile_cpp(source, directory, toolchain=toolchain)
            result = subprocess.run([str(executable)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
