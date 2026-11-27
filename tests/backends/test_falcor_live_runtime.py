"""Verify that switching graphs selects each production shader and keeps native NRD outputs."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.falcor import cgns_cached_overlay, live_runtime, pdf_pt_overlay
from scripts.falcor.live_demo.native import render_passes
from scripts.falcor.spatial_experiment_config import load_config


class LiveDeploymentTests(unittest.TestCase):
    def test_stock_slang_cache_does_not_change_the_deployment_fingerprint(self):
        from scripts.falcor import live_core_runtime, live_scenes_runtime

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            build, release, native = (root / name for name in ("build", "release", "native"))
            (release / "plugins").mkdir(parents=True)
            (release / "plugins/plugins.json").write_text("[]", encoding="utf8")
            (release / "stock.txt").write_text("pinned file", encoding="utf8")
            config = root / "config.json"
            config.write_text('{"methods": {}}', encoding="utf8")
            names = (live_runtime.PLUGIN, live_runtime.NRD_PLUGIN, live_runtime.CORE_DLL,
                     live_runtime.MOGWAI_EXE, *live_runtime.DISPLAY_PLUGINS)
            binaries = {name: native / Path(name).name for name in names}
            native.mkdir()
            for name, path in binaries.items():
                path.write_text(name, encoding="utf8")

            with (
                patch.multiple(live_runtime, BUILD=build, RELEASE=release, CONFIG=config,
                               LOCK=build / "prepare.lock", POINTER=build / "active.json"),
                patch.object(live_runtime, "build_record", return_value={"commit": "pinned"}),
                patch.object(live_runtime, "native_plugin", return_value=binaries[live_runtime.PLUGIN]),
                patch.object(live_runtime, "native_nrd_plugin", return_value=binaries[live_runtime.NRD_PLUGIN]),
                patch.object(live_runtime, "native_display_plugins",
                             return_value={name: binaries[name] for name in live_runtime.DISPLAY_PLUGINS}),
                patch.object(render_passes, "shader_sources", return_value={}),
                patch.object(live_core_runtime, "build_core", return_value=binaries[live_runtime.CORE_DLL]),
                patch.object(live_scenes_runtime, "build_plugins"),
                patch.object(live_scenes_runtime, "bistro_overlay", return_value={}),
            ):
                deployed = live_runtime.prepare()
                stock_cache = release / ".slangcache"
                stock_cache.mkdir()
                (stock_cache / "stock.irpack").write_bytes(b"transient Slang modules")
                (release / ".slangcache.precompile.lock").touch()
                candidate = release / ".slangcache-stage-test" / "candidate"
                candidate.mkdir(parents=True)
                (candidate / "unqualified.irpack").write_bytes(b"staged modules")

                self.assertEqual(live_runtime.prepare(), deployed)
                self.assertFalse((deployed / ".slangcache").exists())
                self.assertEqual((deployed / "stock.txt").read_text(encoding="utf8"), "pinned file")


class LiveRuntimeTests(unittest.TestCase):
    def setUp(self):
        if not (live_runtime.UPSTREAM / "Source/Modules/ReSTIRPathTracing/ReSTIRPathTracing.h").is_file():
            self.skipTest("requires the pinned Falcor source submodule")

    def test_spatial_methods_share_the_pdf_reservoir_layout_and_nrd_outputs(self):
        with tempfile.TemporaryDirectory() as temp:
            runtime = Path(temp)
            module = "shaders/ReSTIRPathTracing/"
            tracer = "shaders/RenderPasses/PathTracer/"
            nrd_only = {tracer + name for name in ("PathTracerNRD.slang", "ResolvePass.cs.slang", "Params.slang")}
            names = set(pdf_pt_overlay.source_names()) | nrd_only
            names.update(module + name for name in (*cgns_cached_overlay.CONSUMERS, "ResamplingCommon.slang"))
            for name in names:
                upstream = live_runtime.UPSTREAM / "Source" / name.removeprefix("shaders/")
                if name.startswith(module):
                    upstream = live_runtime.UPSTREAM / "Source/Modules/ReSTIRPathTracing" / Path(name).name
                target = runtime / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(upstream.read_bytes())
            settings = load_config()["methods"]
            pdf = pdf_pt_overlay.build_overlay(pdf_pt_overlay.read_sources(runtime), settings["pdf-similarity"]["shader"])
            cgns = cgns_cached_overlay.shader_outputs(runtime, settings["cgns"]["shader"])
            merged = render_passes.shader_sources(runtime, settings)
            self.assertEqual(set(merged), pdf.keys() | cgns.keys() | nrd_only)
            for name in ("PathTracer.slang", "GeneratePaths.cs.slang", "ResolvePass.cs.slang"):
                shader = merged[tracer + name]
                self.assertIn("LabPathOutputOptions labPathOutputs;", shader)
                self.assertIn("if (labPathOutputs.nrdData", shader)
                self.assertIn("if (labPathOutputs.guideData", shader)
            self.assertIn(
                "if (labPathOutputs.nrdAdditionalData)",
                merged[tracer + "PathTracerNRD.slang"],
            )
            self.assertIn("setPrimarySurfaceGuideData(labPathOutputs.guideData,",
                          merged[tracer + "PathTracer.slang"])
            self.assertIn("PathTracer::setBackgroundGuideData(labPathOutputs.guideData,",
                          merged[tracer + "GeneratePaths.cs.slang"])
            self.assertEqual(merged[module + "PathReservoir.slang"], pdf[module + "PathReservoir.slang"])
            self.assertNotIn(module + "FetchDenoiserData.cs.slang", merged)
            self.assertFalse(any("LAB_LIVE_SPATIAL_METHOD" in source for source in merged.values()))
            for name, count in cgns_cached_overlay.CONSUMERS.items():
                source = merged[module + name]
                self.assertEqual(source.count("decodeCgnsNeighbor(cgnsNeighbors[pixel], params.frameDim.x)"), count)
                self.assertEqual(source.count("getNextNeighborPixel("), count)
            for stage in cgns_cached_overlay.STAGES:
                name = module + "cgns_cached_" + stage + ".cs.slang"
                self.assertEqual(merged[name], cgns[name])

    def test_host_binds_the_selected_method_and_preserves_programs_on_method_flip(self):
        sources = render_passes.host_sources(live_runtime.UPSTREAM)
        self.assertIn('ar("labSpatialMethod", labSpatialMethod);', sources["ReSTIRPathTracing.h"])
        self.assertFalse(any("LAB_LIVE_SPATIAL_METHOD" in source for source in sources.values()))
        host = sources["ReSTIRPathTracing.cpp"]
        self.assertIn('var["labSpatialMethod"] = mOptions.labSpatialMethod;', host)
        self.assertIn("mOptions.labSpatialMethod == 2 && mOptions.spatialIterations", host)
        self.assertIn("if (mOptions.labSpatialMethod == 2) selectCgnsNeighbors", host)
        setter = sources["PathTracer.cpp"].split('pass.def("setLiveSpatialMethod"', 1)[1].split("});", 1)[0]
        self.assertIn("mReSTIRPathTracingOptions.labSpatialMethod = method", setter)
        self.assertIn("resetLiveHistory(tracer)", setter)
        header = sources["ReSTIRPathTracing.h"].split("void setLiveSpatialMethod(uint32_t method)", 1)[1].split("}", 1)[0]
        for assignment in ("mReallocate", "mRecompile", "mOwnerDefines"):
            self.assertNotIn(assignment, setter + header)
        self.assertIn("mOptions.labSpatialMethod = method", header)
        self.assertIn("resetLiveHistory()", header)

    def test_retained_nrd_outputs_can_skip_execution_without_a_new_path_tracer_program(self):
        tracer = render_passes.host_sources(live_runtime.UPSTREAM)["PathTracer.cpp"]
        self.assertIn('renderData.getDictionary().getValue("labLiveNrdEnabled", true)', tracer)
        self.assertIn('outputs["guideData"] = guideData;', tracer)
        self.assertIn('outputs["nrdData"] = enableNrd && nrdData;', tracer)
        self.assertIn('outputs["nrdAdditionalData"] = enableNrd && nrdAdditionalData;', tracer)
        for define in ("OUTPUT_GUIDE_DATA", "OUTPUT_NRD_DATA", "OUTPUT_NRD_ADDITIONAL_DATA"):
            self.assertNotIn(f'addDefine("{define}"', tracer[:tracer.index("DefineList PathTracer::StaticParams::getDefines")])
        execute = tracer.split("void PathTracer::execute(", 1)[1].split("void PathTracer::renderUI(", 1)[0]
        self.assertIn("if ((enableNrd && mOutputNRDAdditionalData) || specularMVecEnabled)", execute)
        self.assertIn("if (mOutputGuideData || (enableNrd && mOutputNRDData))", execute)
        self.assertIn("resolveReSTIRPTPass(pRenderContext, renderData);", execute)
        definitions = tracer.split("bool PathTracer::beginFrame(", 1)[1].split("void PathTracer::endFrame(", 1)[0]
        self.assertNotIn("labLiveNrdEnabled", definitions)
        self.assertNotIn("liveNrdEnabled", definitions)

    def test_verify_rejects_a_runtime_with_the_old_native_nrd_reset(self):
        with tempfile.TemporaryDirectory() as temp:
            build = Path(temp)
            inputs = {"replacement_hashes": {"plugins/NRDPass.dll": "history-reset-v1"}, "shader_hashes": {}}
            package = build / ("falcor-live-demo-" + live_runtime.fingerprint(inputs)[:16])
            package.mkdir()
            (package / "receipt.json").write_text(json.dumps(
                {"kind": "falcor-live-pt-v1", "inputs": inputs, "files": {}}
            ), encoding="utf8")
            with patch.object(live_runtime, "BUILD", build):
                with self.assertRaisesRegex(ValueError, "NRD history reset"):
                    live_runtime.verify(package)

    def test_verify_rejects_current_nrd_without_the_core_overlay(self):
        with tempfile.TemporaryDirectory() as temp:
            build = Path(temp)
            inputs = {
                "replacement_hashes": {"plugins/NRDPass.dll": "history-reset-v2"},
                "shader_hashes": {},
                "nrd_overlay_revision": live_runtime.NRD_OVERLAY_REVISION,
            }
            package = build / ("falcor-live-demo-" + live_runtime.fingerprint(inputs)[:16])
            package.mkdir()
            (package / "receipt.json").write_text(json.dumps(
                {"kind": "falcor-live-pt-v1", "inputs": inputs, "files": {}}
            ), encoding="utf8")
            with patch.object(live_runtime, "BUILD", build):
                with self.assertRaisesRegex(ValueError, "Falcor core overlay"):
                    live_runtime.verify(package)

    def test_verify_rejects_a_retained_nrd_runtime_with_specialized_output_programs(self):
        with tempfile.TemporaryDirectory() as temp:
            build = Path(temp)
            plugins = (live_runtime.PLUGIN, live_runtime.NRD_PLUGIN, live_runtime.CORE_DLL,
                       live_runtime.MOGWAI_EXE, *live_runtime.DISPLAY_PLUGINS)
            inputs = {
                "replacement_hashes": dict.fromkeys(plugins, "stand-in"),
                "shader_hashes": {},
                "nrd_overlay_revision": live_runtime.NRD_OVERLAY_REVISION,
                "native_panel_overlay_revision": live_runtime.NATIVE_PANEL_OVERLAY_REVISION,
                "live_display_overlay_revision": live_runtime.LIVE_DISPLAY_OVERLAY_REVISION,
            }
            package = build / ("falcor-live-demo-" + live_runtime.fingerprint(inputs)[:16])
            package.mkdir()
            (package / "receipt.json").write_text(json.dumps(
                {"kind": "falcor-live-pt-v1", "inputs": inputs, "files": {}}
            ), encoding="utf8")
            with patch.object(live_runtime, "BUILD", build):
                with self.assertRaisesRegex(live_runtime.OutdatedRuntimeError, "shared PathTracer output wiring"):
                    live_runtime.verify(package)

    def test_locate_rejects_a_runtime_that_cannot_read_precompiled_modules(self):
        with tempfile.TemporaryDirectory() as temp:
            build = Path(temp)
            plugins = (live_runtime.PLUGIN, live_runtime.NRD_PLUGIN, live_runtime.CORE_DLL,
                       live_runtime.MOGWAI_EXE, *live_runtime.DISPLAY_PLUGINS)
            inputs = {
                "replacement_hashes": dict.fromkeys(plugins, "stand-in"),
                "shader_hashes": {},
                "nrd_overlay_revision": live_runtime.NRD_OVERLAY_REVISION,
                "native_panel_overlay_revision": live_runtime.NATIVE_PANEL_OVERLAY_REVISION,
                "live_display_overlay_revision": live_runtime.LIVE_DISPLAY_OVERLAY_REVISION,
                "path_tracer_output_revision": live_runtime.PATH_TRACER_OUTPUT_REVISION,
            }
            package = build / ("falcor-live-demo-" + live_runtime.fingerprint(inputs)[:16])
            package.mkdir()
            (package / "receipt.json").write_text(json.dumps(
                {"kind": "falcor-live-pt-v1", "inputs": inputs, "files": {}}
            ), encoding="utf8")
            with patch.object(live_runtime, "BUILD", build):
                with self.assertRaisesRegex(live_runtime.OutdatedRuntimeError, "Slang"):
                    live_runtime.verify(package)

    def test_nrd_overlay_queues_a_single_clear_without_changing_the_frame_index(self):
        sources = render_passes.nrd_host_sources(live_runtime.UPSTREAM)
        source = sources["NRDPass.cpp"]
        self.assertIn('pass.def("resetLiveHistory", &NRDPass::resetLiveHistory)', source)
        execute = source.split("void NRDPass::executeInternal(", 1)[1].split("void NRDPass::dispatch(", 1)[0]
        self.assertIn("if (mFrameIndex == 0 || mResetLiveHistory)", execute)
        self.assertIn("mResetLiveHistory ? nrd::AccumulationMode::CLEAR_AND_RESTART : nrd::AccumulationMode::CONTINUE", execute)
        self.assertNotIn("mFrameIndex = 0;", execute)
        self.assertLess(execute.index("GetComputeDispatches"), execute.index("mResetLiveHistory = false;"))


    def test_nrd_overlay_preserves_initialized_resources_for_same_size_and_method(self):
        sources = render_passes.nrd_host_sources(live_runtime.UPSTREAM)
        self.assertIn("std::unique_ptr<nrd::Denoiser, DenoiserDeleter> mpDenoiser", sources["NRDPass.h"])
        self.assertIn("nrd::DestroyDenoiser(*denoiser)", sources["NRDPass.h"])
        source = sources["NRDPass.cpp"]
        compile_pass = source.split("void NRDPass::compile(", 1)[1].split("void NRDPass::execute(", 1)[0]
        self.assertIn("mScreenSize.x == previousSize.x && mScreenSize.y == previousSize.y", compile_pass)
        self.assertIn("mInitializedMethod == mDenoisingMethod", compile_pass)
        self.assertIn("resetLiveHistory();", compile_pass)
        self.assertNotIn("mFrameIndex = 0;", compile_pass)
        reinit = source.split("void NRDPass::reinit(", 1)[1].split("void NRDPass::createPipelines(", 1)[0]
        self.assertLess(reinit.index("mpDenoiser.reset();"), reinit.index("nrd::CreateDenoiser("))
        self.assertLess(reinit.index("createPipelines();"), reinit.index("mInitializedMethod = mDenoisingMethod;"))
        self.assertIn("mFrameIndex = 0;", reinit)
        execute = source.split("void NRDPass::executeInternal(", 1)[1].split("void NRDPass::dispatch(", 1)[0]
        self.assertIn("if (mInitializedMethod != mDenoisingMethod)", execute)
