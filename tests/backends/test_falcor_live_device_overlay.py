"""Check the private live-device rotation's lifetime and build boundaries."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.falcor import live_core_runtime, live_runtime
from scripts.falcor.live_demo.native import device


class LiveDeviceOverlayTests(unittest.TestCase):
    def test_rotation_releases_old_device_and_reuses_window(self):
        paths = device.SOURCES
        app = device.patch_sample_app(paths["SampleApp.cpp"].read_text(encoding="utf8"))
        reset = app.split('m.def("recreateLiveDevice"', 1)[1]
        self.assertIn("gLiveFrameDepth == 0", reset)
        self.assertIn("setActivePythonRenderGraphDevice(nullptr);", reset)
        self.assertLess(reset.index("mpSwapchain.reset();"), reset.index("mpDevice.reset();"))
        self.assertLess(reset.index("mpDevice.reset();"), reset.index("make_ref<Device>(deviceDesc)"))
        self.assertIn("mpWindow->getApiHandle()", reset)
        self.assertNotIn("Window::create", reset)
        self.assertIn("LiveFrameGuard liveFrameGuard;", app)

    def test_renderer_repairs_device_owners_at_scene_release(self):
        paths = device.SOURCES
        renderer = device.patch_mogwai(paths["Mogwai.cpp"].read_text(encoding="utf8"))
        capture = device.patch_capture(paths["FrameCapture.cpp"].read_text(encoding="utf8"))
        self.assertIn("setScene(nullptr);\n        mpSampler.reset();", renderer)
        self.assertNotIn("mpImageProcessing =", capture)
        self.assertIn("ImageProcessing imageProcessing(mpRenderer->getDevice());", capture)

    def test_native_graphs_places_live_controls_before_the_graph_and_preserves_pass_ui(self):
        settings = device.patched_sources().get("MogwaiSettings.cpp")
        self.assertIsNotNone(settings, "The live runtime must build the native Graphs panel")
        graph_ui = settings.split("void MogwaiSettings::renderGraphs", 1)[1].split(
            "void MogwaiSettings::renderMainMenu", 1
        )[0]
        self.assertIn('Gui::Window w(pGui, "Graphs"', graph_ui)
        self.assertLess(graph_ui.index("renderLiveSessionPanel(w)"),
                        graph_ui.index("if (mpRenderer->mGraphs.empty()) return;"))
        self.assertIn("pActiveGraph->renderUI(mpRenderer->getRenderContext(), w)", graph_ui)

    def test_idle_clear_color_only_applies_to_the_managed_graphless_viewport(self):
        renderer = device.patched_sources()["Mogwai.cpp"]
        frame = renderer.split("void Renderer::onFrameRender(", 1)[1].split("void Renderer::onHotReload(", 1)[0]
        self.assertIn("mGraphs.empty() ? MogwaiSettings::get(this) : nullptr", frame)
        self.assertIn("settings && settings->isLiveSessionPanelEnabled()", frame)
        self.assertIn("float4(0.03f, 0.03f, 0.03f, 1.f)", frame)
        self.assertIn("float4(0.38f, 0.52f, 0.10f, 1.f)", frame)

    def test_native_gui_submits_both_mouse_edges_to_imgui_before_low_fps_frames(self):
        gui = device.patched_sources().get("Gui.cpp")
        self.assertIsNotNone(gui, "The private Falcor build must include the mouse event fix")
        event = gui.split("bool Gui::onMouseEvent(", 1)[1].split("bool Gui::onKeyboardEvent(", 1)[0]
        self.assertIn("case MouseEvent::Type::ButtonDown:", event)
        self.assertIn("case MouseEvent::Type::ButtonUp:", event)
        for button_index in range(3):
            self.assertIn(f"io.AddMouseButtonEvent({button_index}, isDown)", event)
        self.assertIn("io.AddMousePosEvent", event)
        self.assertIn("io.AddMouseWheelEvent", event)
        self.assertNotIn("memcpy(io.MouseDown", gui)

    def test_live_renderer_camera_binding_changes_loaded_scene_input(self):
        scripting = device.patched_sources()["MogwaiScripting.cpp"]
        binding = scripting.split('renderer.def("setLiveCameraInputEnabled"', 1)
        self.assertEqual(len(binding), 2, "The private renderer must expose camera input control")
        body = binding[1].split("renderer.def(", 1)[0]
        self.assertIn("pRenderer->getScene()", body)
        self.assertIn("scene->setCameraControlsEnabled(enabled)", body)

    def test_verify_rejects_the_previous_mogwai_overlay(self):
        with tempfile.TemporaryDirectory() as temporary:
            build = Path(temporary)
            inputs = {
                "replacement_hashes": {"Falcor.dll": "core", "Mogwai.exe": "device-rotation",
                                       "plugins/NRDPass.dll": "history-reset"},
                "shader_hashes": {},
                "nrd_overlay_revision": live_runtime.NRD_OVERLAY_REVISION,
            }
            package = build / ("falcor-live-demo-" + live_runtime.fingerprint(inputs)[:16])
            package.mkdir()
            (package / "receipt.json").write_text(json.dumps(
                {"kind": "falcor-live-pt-v1", "inputs": inputs, "files": {}}
            ), encoding="utf8")
            with patch.object(live_runtime, "BUILD", build):
                with self.assertRaisesRegex(live_runtime.OutdatedRuntimeError, "Mogwai Graphs panel"):
                    live_runtime.verify(package)

    def test_relink_replaces_runtime_inputs_only(self):
        if not live_core_runtime.TLOG.is_dir() or not live_core_runtime.MOGWAI_TLOG.is_dir():
            self.skipTest("Retained Falcor Release build records are not installed")
        with tempfile.TemporaryDirectory() as temporary:
            stage = Path(temporary)
            commands, mogwai_link = live_core_runtime.mogwai_commands(stage)
            self.assertEqual(set(commands), {"Mogwai.cpp", "MogwaiSettings.cpp", "MogwaiScripting.cpp", "FrameCapture.cpp"})
            for output in ("Mogwai.obj", "MogwaiSettings.obj", "MogwaiScripting.obj", "FrameCapture.obj",
                           "Mogwai.exe", "Mogwai.lib", "Mogwai.pdb"):
                self.assertIn(str(stage / output), mogwai_link)
            _, falcor_link = live_core_runtime.release_commands(stage)
            self.assertIn(str(stage / "SampleApp.obj"), falcor_link)
            self.assertIn(str(stage / "Gui.obj"), falcor_link)


if __name__ == "__main__":
    unittest.main()
