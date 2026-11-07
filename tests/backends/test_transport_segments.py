"""Run the production ray traversal against legal, deliberately reordered hits."""
from pathlib import Path
import subprocess
import re
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts/run")]
from tests.fixtures.cpp import compile_cpp, shader_function
from rtxdi_transport_fixes import adapt_path, adapt_ray_payload, adapt_rt_shaders, adapt_brdf_trace


class TransportSegmentTests(unittest.TestCase):
    def test_nonopaque_geometry_disallows_duplicate_anyhit(self):
        import shutil
        import rtxdi_transport_fixes as fixes
        renderer = ROOT / "renderers/rtxdi"
        scene_name = "Samples/FullSample/Source/Scene/SampleScene.cpp"
        native_scene = (renderer / scene_name).read_text()
        nvrhi = (renderer / "External/donut/nvrhi/include/nvrhi/nvrhi.h").read_text()
        flags = re.search(r"enum class GeometryFlags : uint8_t\s*\{[^}]+\};", nvrhi).group()
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            for name in set(fixes.SEGMENT_FILES) | {scene_name}:
                path = folder / name
                path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(renderer / name, path)
            fixes.adapt_segments(folder)
            source = (folder / scene_name).read_text()
            self.assertEqual(source.replace("GeometryFlags::NoDuplicateAnyHitInvocation", "GeometryFlags::None"), native_scene)
            assignment = re.search(r"geometryDesc.flags = .*?;", source, re.S).group()
            unit = folder / "geometry_flags.cpp"
            unit.write_text('#include <cstdint>\n#include <cstdio>\n'
                'namespace nvrhi { namespace rt { ' + flags + ' } }\n'
                'namespace engine { enum class MaterialDomain { Opaque=0 }; }\n'
                'struct Material { engine::MaterialDomain domain; };\n'
                'struct Geometry { Material* material; };\n'
                'int main() { for(int domain=0;domain<6;++domain) {\n'
                'Material material{engine::MaterialDomain(domain)}; Geometry storage{&material}; auto geometry=&storage;\n'
                'struct { nvrhi::rt::GeometryFlags flags; } geometryDesc;\n' + assignment + '\n'
                'auto want=domain==0?nvrhi::rt::GeometryFlags::Opaque:nvrhi::rt::GeometryFlags::NoDuplicateAnyHitInvocation;\n'
                'if(geometryDesc.flags!=want) { std::fprintf(stderr,"Nonopaque BLAS must forbid duplicate any-hit invocations\\n"); return 1; }\n'
                '} return 0; }\n')
            exe = compile_cpp(unit, folder)
            result = subprocess.run([str(exe)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_transmission_stops_at_closest_opaque_or_cutout_hit(self):
        bridge = ROOT / "renderers/rtxdi/Samples/FullSample/Shaders/LightingPasses/RtxdiApplicationBridge"
        ray = adapt_rt_shaders((bridge / "RAB_RTShaders.hlsli").read_text())
        payload = adapt_ray_payload((bridge / "RAB_RayPayload.hlsli").read_text())
        payload = payload[payload.index("struct RAB_RayPayload"):payload.index("};") + 2]
        helper = (ROOT / "scripts/run/rtxdi_experiments/OpaqueSegment.hlsli").read_text()
        path = adapt_path((bridge / "PathTracer/RAB_PathTracer.hlsli").read_text())
        gi = adapt_brdf_trace((bridge.parent / "BrdfRayTracing.hlsl").read_text())
        gi_trace = gi[gi.index("    uint instanceMask = INSTANCE_MASK_OPAQUE;"):gi.index("    if (g_PerPassConstants.rayCountBufferIndex >= 0)")]
        functions = [shader_function(ray, "ConsiderTransparentMaterial", "bool"),
                     helper.replace("inout uint traceFlags", "uint& traceFlags"),
                     shader_function(path, "TraceNextBounce", "RAB_RayPayload"),
                     "RAB_RayPayload TraceGiFixture(RayDesc ray) {\n" + gi_trace + "return payload;\n}",
                     shader_function(ray, "AnyHit", "void"), shader_function(ray, "ClosestHit", "void")]
        source = "\n".join(functions).replace("(RAB_RayPayload)0", "RAB_RayPayload{}")
        source = re.sub(r"\s*:\s*SV_\w+", "", source).replace("in RayAttributes", "RayAttributes")
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            (folder / "payload_under_test.h").write_text(payload)
            (folder / "segments_under_test.h").write_text(source)
            for use_query in (1, 0):
                with self.subTest(use_ray_query=use_query):
                    unit = folder / f"segments_{use_query}.cpp"
                    unit.write_text(f'#define USE_RAY_QUERY {use_query}\n#include "{(ROOT / "tests/transport_segments.cpp").as_posix()}"\n')
                    exe = compile_cpp(unit, folder, includes=(folder,))
                    result = subprocess.run([str(exe)], capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_shared_segment_adapter_tracks_every_changed_or_created_file(self):
        import shutil
        import rtxdi_transport_fixes as fixes
        import rtxdi_path_reference as reference
        renderer = ROOT / "renderers/rtxdi"
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)
            before = {}
            for name in fixes.SEGMENT_FILES:
                path = target / name
                path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(renderer / name, path)
                before[name] = path.read_bytes()
            fixes.adapt_segments(target)
            changed = {name for name, data in before.items() if (target / name).read_bytes() != data}
            self.assertEqual(changed, set(fixes.SEGMENT_FILES))
            self.assertTrue(changed <= set(fixes.FILES) and changed <= set(reference.FILES))
            created = {p.relative_to(target).as_posix() for p in target.rglob("*") if p.is_file()} - before.keys()
            self.assertEqual(created, {fixes.SEGMENT_CREATED})
            self.assertTrue(created <= set(fixes.CREATED) and created <= set(reference.CREATED))
            with self.assertRaises(RuntimeError):
                fixes.adapt_segments(target)


if __name__ == "__main__":
    unittest.main()
