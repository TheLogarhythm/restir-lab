"""Regressions for live graph switching, capture requests, and optional NRD outputs."""

import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from scripts.falcor.live_demo.acceptance import acceptance_steps, validate_sequence, verify
from scripts.falcor.live_demo.scenes import ROOT
from scripts.falcor.live_demo.graph import METHODS, MODES, SOURCES, build_graph, switch_display


class LauncherTests(unittest.TestCase):
    def test_interactive_selector_prepares_sky_but_classroom_only_acceptance_skips_it(self):
        from scripts.falcor.live_demo import launcher

        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "Mogwai.exe").touch()
            with (patch.object(launcher, "prepare_sky") as prepare,
                  patch.object(launcher, "run_session") as run,
                  patch.object(launcher, "verify") as verify):
                launcher.main(["--runtime", directory])
                prepare.assert_called_once_with()
                config = run.call_args.args[2]
                self.assertIsNone(config["scene"])
                self.assertEqual((config["width"], config["height"]), (1920, 1080))
                prepare.reset_mock()
                launcher.main(["--runtime", directory, "--acceptance", "classroom"])
                prepare.assert_not_called()
                verify.assert_called_once()


class AcceptanceCaptureTests(unittest.TestCase):
    def test_first_prefix_is_an_ordinary_label_and_client_size_may_be_clamped(self):
        from PIL import Image

        row = {"Scene": "Classroom", "Method": "CGNS", "Display": "Raw", "label": "first-look", "frames": 8}
        pose = {"position": [1, 0, 0], "target": [0, 0, 0], "up": [0, 1, 0]}
        rec = {**row, "pid": 7, "hwnd": 11, "visible": True, "settled_frames": 8,
               "resolution": [64, 64], "method_id": METHODS["CGNS"], "display_input": SOURCES["Raw"],
               "tone_mapper_raw_input": True, "accumulation_bypassed": True, "camera": pose, "preset_camera": pose,
               "file": "display.png", "raw_file": "raw.png"}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            image = Image.new("RGB", (64, 64))
            image.putpixel((0, 0), (255, 255, 255))
            image.save(output / "display.png")
            image.save(output / "raw.png")
            (output / "renderer-complete.json").write_text(
                json.dumps({"pid": 7, "hwnd": 11, "captures": [rec]}), encoding="utf8"
            )
            validate_sequence([row])
            verify(output, {"sequence": [row], "suite": None, "width": 1920, "height": 1080}, 7)
            result = json.loads((output / "acceptance.json").read_text(encoding="utf8"))
            self.assertTrue(result["captures"][0]["same_as_raw"])


class Graph:
    """Model the public graph-edit operations, including unique input edges."""

    def __init__(self, name):
        self.name = name
        self.passes, self.edges, self.outputs = {}, {}, []

    def addPass(self, render_pass, name):
        self.passes[name] = render_pass

    def removePass(self, name):
        self.passes.pop(name)
        self.outputs = [output for output in self.outputs if not output.startswith(name + ".")]
        self.edges = {target: source for target, source in self.edges.items()
                      if not source.startswith(name + ".") and not target.startswith(name + ".")}

    def addEdge(self, source, target):
        if target in self.edges:
            raise ValueError("duplicate graph input")
        self.edges[target] = source

    def removeEdge(self, source, target):
        # The pinned string overload compares field names but omits the target
        # node identity. Reproduce that behavior so accidental aliases fail here.
        for candidate, connection in self.edges.items():
            if connection == source and candidate.split(".")[1] == target.split(".")[1]:
                del self.edges[candidate]
                return

    def markOutput(self, name):
        if name not in self.outputs:
            self.outputs.append(name)

    def unmarkOutput(self, name):
        self.outputs.remove(name)

    def __getitem__(self, name):
        return self.passes[name]


class Pass:
    def __init__(self, kind, options):
        self.kind, self.properties = kind, options
        self.liveRawInput = self.liveBypass = False
        self.enabled = options.get("enabled", False)
        self.exposureCompensation = options.get("exposureCompensation", 0.0)
        self.reset_count = 0

    def reset(self):
        self.reset_count += 1


class LiveGraphTests(unittest.TestCase):
    def test_restores_maximized_window_before_correcting_falcor_client_size(self):
        from scripts.falcor.live_demo.window import WindowIdentity

        trace = MagicMock()
        window = WindowIdentity.__new__(WindowIdentity)
        window.hwnd = 21
        window.client_size = trace.client_size
        window.is_zoomed = trace.is_zoomed
        window.show_window = trace.show_window
        trace.client_size.side_effect = [(1920, 1061), (1920, 1080)]
        trace.is_zoomed.return_value = True

        self.assertEqual(window.resize_client(trace.resize_framebuffer, trace.flush_resize_events, 1920, 1080),
                         (1920, 1080))
        self.assertEqual([call[0] for call in trace.mock_calls], [
            "client_size", "is_zoomed", "show_window", "resize_framebuffer", "flush_resize_events", "client_size",
        ])
        trace.show_window.assert_called_once_with(21, 9)
        trace.resize_framebuffer.assert_called_once_with(1920, 1080)

    def test_already_correct_client_size_does_not_touch_window(self):
        from scripts.falcor.live_demo.window import WindowIdentity

        trace = MagicMock()
        window = WindowIdentity.__new__(WindowIdentity)
        window.client_size = trace.client_size
        trace.client_size.return_value = (1920, 1080)
        self.assertEqual(window.resize_client(trace.resize_framebuffer, trace.flush_resize_events, 1920, 1080),
                         (1920, 1080))
        self.assertEqual([call[0] for call in trace.mock_calls], ["client_size"])

    def test_win32_fallback_preserves_decorations_when_native_resize_is_clamped(self):
        from scripts.falcor.live_demo.window import WindowIdentity

        trace = MagicMock()
        window = WindowIdentity.__new__(WindowIdentity)
        window.hwnd = 21
        window.client_size = trace.client_size
        window.is_zoomed = trace.is_zoomed
        window.rect_size = trace.rect_size
        window.get_window_rect = trace.get_window_rect
        window.allow_outer_size = trace.allow_outer_size
        trace.client_size.side_effect = [(1920, 1061), (1920, 1061), (1920, 1080)]
        trace.is_zoomed.return_value = False
        trace.rect_size.return_value = (1936, 1100)

        self.assertEqual(window.resize_client(trace.resize_framebuffer, trace.flush_resize_events, 1920, 1080),
                         (1920, 1080))
        self.assertEqual([call[0] for call in trace.mock_calls], [
            "client_size", "is_zoomed", "resize_framebuffer", "flush_resize_events", "client_size",
            "rect_size", "allow_outer_size", "allow_outer_size().__enter__", "resize_framebuffer",
            "flush_resize_events", "allow_outer_size().__exit__", "client_size",
        ])
        trace.allow_outer_size.assert_called_once_with(1936, 1119)

    def test_temporary_resize_callback_preserves_default_limits_and_is_removed_on_error(self):
        from scripts.falcor.live_demo import window as menu

        window = menu.WindowIdentity.__new__(menu.WindowIdentity)
        window.hwnd = 21
        controls = MagicMock()
        controls.SetWindowSubclass.return_value = controls.RemoveWindowSubclass.return_value = True
        limits = menu.MinMaxInfo()

        def default(*_):
            limits.max_size.x, limits.max_size.y = 1900, 1200
            limits.max_track.x, limits.max_track.y = 1940, 1100
            return 10

        controls.DefSubclassProc.side_effect = default
        with (patch.object(menu.C, "WinDLL", return_value=controls, create=True),
              patch.object(menu.C, "WINFUNCTYPE", menu.C.CFUNCTYPE, create=True)):
            with self.assertRaisesRegex(ValueError, "resize failed"):
                with window.allow_outer_size(1936, 1119):
                    callback = controls.SetWindowSubclass.call_args.args[1]
                    result = callback(21, menu.WM_GETMINMAXINFO, 0, menu.C.addressof(limits), 0, 0)
                    self.assertEqual(result, 10)
                    self.assertEqual((limits.max_size.x, limits.max_size.y), (1936, 1200))
                    self.assertEqual((limits.max_track.x, limits.max_track.y), (1940, 1119))
                    raise ValueError("resize failed")
        controls.RemoveWindowSubclass.assert_called_once_with(21, callback, 0)

    def test_spatial_methods_keep_temporal_and_spatial_reuse_enabled_in_each_display(self):
        methods = {"Original": 0, "PDF Similarity": 1, "CGNS": 2}
        self.assertEqual(METHODS, methods)
        with patch.dict("sys.modules", falcor=SimpleNamespace(RenderGraph=Graph, createPass=Pass)):
            for method, method_id in methods.items():
                for mode in MODES:
                    with self.subTest(method=method, mode=mode):
                        graph, source = build_graph(ROOT, method, mode, 1.0)
                        options = graph["PathTracer"].properties["reSTIRPathTracingOptions"]
                        self.assertEqual(options["labSpatialMethod"], method_id)
                        self.assertTrue(options["useSpatialResampling"])
                        self.assertTrue(options["useTemporalResampling"])
                        self.assertEqual(source, SOURCES[mode])

    def test_raw_and_accumulation_switch_without_modifying_the_graph(self):
        with patch.dict("sys.modules", falcor=SimpleNamespace(RenderGraph=Graph, createPass=Pass)):
            graph, source = build_graph(ROOT, "CGNS", "Accumulation", 1.0)
        accumulate = graph["AccumulatePass"]
        tone_mapper = graph["ToneMapper"]
        accumulate.enabled = False
        accumulate.properties["outputSize"] = "Fixed"
        tone_mapper.properties["exposureCompensation"] = 3.0
        edges = graph.edges.copy()
        outputs = graph.outputs.copy()

        self.assertEqual(source, "AccumulatePass.output")
        self.assertEqual(switch_display(graph, "Accumulation", "Raw", compare_raw=False), "PathTracer.color")
        self.assertEqual(graph.edges["ToneMapper.rawSrc"], "PathTracer.color")
        self.assertTrue(tone_mapper.liveRawInput)
        self.assertTrue(accumulate.liveBypass)
        self.assertEqual(graph.edges, edges)
        self.assertEqual(graph.outputs, outputs)
        self.assertEqual(switch_display(graph, "Raw", "Accumulation", compare_raw=False), "AccumulatePass.output")
        self.assertFalse(tone_mapper.liveRawInput)
        self.assertFalse(accumulate.liveBypass)
        self.assertFalse(accumulate.enabled)
        self.assertEqual(accumulate.properties["outputSize"], "Fixed")
        self.assertEqual(tone_mapper.properties["exposureCompensation"], 3.0)
        self.assertEqual(graph.edges, edges)
        self.assertEqual(graph.outputs, outputs)
        self.assertEqual(accumulate.reset_count, 1)

    def test_switches_leave_display_first_and_keep_color_bound_in_nrd(self):
        with patch.dict("sys.modules", falcor=SimpleNamespace(RenderGraph=Graph, createPass=Pass)):
            graph, first = build_graph(ROOT, "CGNS", "Raw", 1.0, compare_raw=True)
        tracer = graph["PathTracer"]
        self.assertEqual(first, "PathTracer.color")
        self.assertEqual(tracer.properties["reSTIRPathTracingOptions"]["labSpatialMethod"], 2)
        self.assertNotIn("NRDDiffuseSpecular.diffuseRadianceHitDist", graph.edges)
        previous = "Raw"
        for selected in ("Accumulation", "NRD", "NRD", "Accumulation", "Raw"):
            with patch.dict("sys.modules", falcor=SimpleNamespace(createPass=Pass)):
                source = switch_display(graph, previous, selected, compare_raw=True)
            if selected == "NRD":
                self.assertEqual(graph.edges["NRDDiffuseSpecular.diffuseRadianceHitDist"],
                                 "PathTracer.nrdDiffuseRadianceHitDist")
            else:
                self.assertFalse(any(name.startswith("PathTracer.nrd") for name in graph.edges.values()))
            self.assertEqual(source, SOURCES[selected])
            self.assertEqual(graph.edges["ToneMapper.src"],
                             "ModulateIllumination.output" if selected == "NRD" else "AccumulatePass.output")
            self.assertEqual(graph.outputs[0], "ToneMapper.dst")
            self.assertEqual("PathTracer.color" in graph.outputs, selected == "NRD")
            self.assertEqual("RawComparison.dst" in graph.outputs, selected != "NRD")
            self.assertEqual("RawComparison" in graph.passes, selected != "NRD")
            self.assertIs(graph["PathTracer"], tracer)
            previous = selected
        self.assertEqual(graph["AccumulatePass"].reset_count, 2)

    def test_warm_nrd_leaves_resource_edges_intact_and_disables_denoising_outside_nrd(self):
        class RetainedGraph(Graph):
            def setLiveNrdEnabled(self, enabled):
                self.nrd_enabled = enabled

            def hasLiveNrdBranch(self):
                return "ModulateIllumination" in self.passes

        with patch.dict("sys.modules", falcor=SimpleNamespace(RenderGraph=RetainedGraph, createPass=Pass)):
            for initial in ("Raw", "NRD"):
                with self.subTest(initial=initial):
                    graph, source = build_graph(ROOT, "CGNS", initial, 1.0, compare_raw=True)
                    self.assertEqual(graph.hasLiveNrdBranch(), initial == "NRD")
                    if initial == "Raw":
                        source = switch_display(graph, "Raw", "NRD", compare_raw=True)
                    self.assertEqual(source, "ModulateIllumination.output")
                    self.assertEqual(graph.edges["ToneMapper.nrdSrc"], "ModulateIllumination.output")
                    self.assertEqual(graph.edges["ToneMapper.rawSrc"], "PathTracer.color")
                    self.assertEqual(graph.edges["ToneMapper.src"], "AccumulatePass.output")
                    nrd_pass = graph["NRDDiffuseSpecular"]
                    nrd_pass.properties["maxIntensity"] = 17.0
                    edges, outputs = graph.edges.copy(), graph.outputs.copy()

                    previous = "NRD"
                    for selected, display_id, routing in (
                        ("Raw", 0, "PathTracer.color"),
                        ("Accumulation", 1, "AccumulatePass.output"),
                        ("NRD", 2, "ModulateIllumination.output"),
                    ):
                        self.assertEqual(switch_display(graph, previous, selected, compare_raw=True), routing)
                        self.assertEqual(graph["ToneMapper"].liveDisplayMode, display_id)
                        self.assertEqual(graph.nrd_enabled, selected == "NRD")
                        self.assertIs(graph["NRDDiffuseSpecular"], nrd_pass)
                        self.assertEqual(graph["NRDDiffuseSpecular"].properties["maxIntensity"], 17.0)
                        self.assertEqual(graph.edges, edges)
                        self.assertEqual(graph.outputs, outputs)
                        previous = selected

    def test_announces_loading_before_rendering_only_the_selected_scene_method(self):
        from scripts.falcor.live_demo.controller import Session

        events = []
        renderer = MagicMock(scene=None)
        renderer.pollLiveSessionActions.side_effect = [[("Scene", "Classroom")], [("View", "Quit")]]
        renderer.setLiveSessionState.side_effect = lambda *args: events.append(("panel", *args))
        device = object()

        def install(graph):
            graph.get_output = MagicMock(side_effect=lambda _: SimpleNamespace(device=device))
            renderer.graph = graph

        renderer.addGraph.side_effect = install

        def load_scene(renderer, name, root):
            events.append(("load", name))
            renderer.scene = SimpleNamespace(camera=object())
            return 0.0

        def render():
            method = renderer.graph["PathTracer"].properties["reSTIRPathTracingOptions"]["labSpatialMethod"]
            events.append(("frame", method))

        renderer.renderFrame.side_effect = render
        falcor = SimpleNamespace(RenderGraph=Graph, createPass=Pass, exit=lambda _: None,
                                 recreateLiveDevice=lambda: None,
                                 presentLiveSessionStatus=lambda: events.append(("status_frame",)))
        settings = {"root": ROOT, "sequence": None, "scene": None, "method": "PDF Similarity", "mode": "Raw"}
        with (patch.dict("sys.modules", falcor=falcor),
              patch("scripts.falcor.live_demo.scenes.load_scene", load_scene),
              patch("scripts.falcor.live_demo.controller.camera_state", return_value={}),
              patch("scripts.falcor.live_demo.window.WindowIdentity"),
              patch.object(Session, "log")):
            session = Session(renderer, settings, ROOT)
            session.run()

        renderer.graph.get_output.assert_called_once_with("ToneMapper.dst")
        self.assertIsNone(session.scene_device)

        self.assertEqual(events, [
            ("panel", "", "PDF Similarity", "Raw", ""),
            ("panel", "Classroom", "PDF Similarity", "Raw", "Loading Classroom"),
            ("status_frame",),
            ("load", "Classroom"),
            ("frame", 1),
            ("panel", "Classroom", "PDF Similarity", "Raw", ""),
        ])

    def test_sequence_only_disables_live_camera_input_after_load(self):
        from scripts.falcor.live_demo.controller import Session

        def vector(x, y, z):
            return SimpleNamespace(x=x, y=y, z=z)

        for sequence in (None, [{"Scene": "Sun Temple"}]):
            with self.subTest(scripted=sequence is not None):
                events = []
                renderer = MagicMock(scene=None)
                renderer.setLiveCameraInputEnabled.side_effect = lambda enabled: events.append(("camera input", enabled))
                renderer.addGraph.side_effect = lambda graph: events.append(("graph",))

                def load_scene(active_renderer, name, root):
                    events.append(("load", name))
                    active_renderer.scene = SimpleNamespace(camera=SimpleNamespace(
                        position=vector(1.0, 2.0, 3.0), target=vector(4.0, 5.0, 6.0),
                        up=vector(0.0, 1.0, 0.0), focalLength=18.0, nearPlane=0.1, apertureRadius=0.0,
                    ))
                    return 0.0

                settings = {"root": ROOT, "sequence": sequence, "scene": None, "method": "CGNS", "mode": "Raw"}
                falcor = SimpleNamespace(RenderGraph=Graph, createPass=Pass, float3=vector,
                                         recreateLiveDevice=lambda: None, presentLiveSessionStatus=lambda: None)
                with (patch.dict("sys.modules", falcor=falcor),
                      patch("scripts.falcor.live_demo.scenes.load_scene", load_scene),
                      patch("scripts.falcor.live_demo.window.WindowIdentity"),
                      patch.object(Session, "log")):
                    session = Session(renderer, settings, ROOT)
                    session.transition("Scene", "Sun Temple")
                    session.perform("View", "Nudge camera right", 0.0)
                    self.assertEqual(renderer.scene.camera.position.x, 1.25)
                    self.assertEqual(renderer.scene.camera.target.x, 4.25)
                    session.perform("View", "Reset camera", 0.0)
                    self.assertEqual(renderer.scene.camera.position.x, 1.0)
                    self.assertEqual(renderer.scene.camera.target.x, 4.0)

                expected = [("load", "Sun Temple")]
                if sequence is not None:
                    expected.append(("camera input", False))
                self.assertEqual(events, [*expected, ("graph",)])

    def test_releases_previous_scene_with_dirty_graph_before_draining_all_graphics_heaps(self):
        from scripts.falcor.live_demo.controller import Session
        session = Session.__new__(Session)
        trace = MagicMock()
        session.graph, session.renderer = trace.graph, trace.renderer
        session.scene_device = trace.device
        session.graph.get_output.side_effect = RuntimeError("The graph wasn't successfuly compiled yet.")
        session.saved_nrd, session.log = {"NRD": object()}, MagicMock()
        memory = SimpleNamespace(process_commit_bytes=MagicMock(side_effect=[300, 250, 100, 50]))
        def recreate():
            self.assertIsNone(session.scene_device)
            trace.recreate()

        falcor = SimpleNamespace(recreateLiveDevice=recreate)
        with patch.dict("sys.modules", {"falcor": falcor, "scripts.falcor.live_demo.window": memory}):
            session.release_scene()
        self.assertIsNone(session.graph)
        self.assertFalse(session.saved_nrd)
        self.assertEqual([item[0] for item in trace.mock_calls], [
            "device.wait", "renderer.removeGraph", "renderer.unloadScene",
            "device.end_frame", "device.end_frame", "device.end_frame", "device.end_frame", "device.wait", "recreate",
        ])
        session.log.assert_called_once_with("scene_released", before_bytes=300,
                                            detached_bytes=250, drained_bytes=100, fresh_device_bytes=50)

    def test_full_sequence_covers_all_presets_methods_and_outputs_with_returns(self):
        from scripts.falcor.live_demo.scenes import SCENE_NAMES
        rows = acceptance_steps("all")
        validate_sequence(rows)
        self.assertEqual({(r["Scene"], r["Method"], r["Display"]) for r in rows},
                         {(s, m, d) for s in SCENE_NAMES for m in METHODS for d in MODES})
        classroom = acceptance_steps("classroom")
        validate_sequence(classroom)
        self.assertEqual({(r["Scene"], r["Method"], r["Display"]) for r in classroom},
                         {("Classroom", m, d) for m in METHODS for d in MODES})
        for row in (rows[0], classroom[0], classroom[-1]):
            self.assertEqual((row["Scene"], row["Method"], row["Display"]), ("Classroom", "CGNS", "Raw"))
        self.assertEqual([r["label"] for r in rows if r.get("probe")], ["after-accum-method-switch"])
        self.assertEqual([r["Scene"] for r in rows[-2:]], ["Bistro Interior", "Classroom"])
        self.assertEqual([r["camera"] for r in rows if "camera" in r],
                         ["Nudge camera right", "Reset camera", "Nudge camera right", "Reset camera"])
        moved = next(i for i, row in enumerate(rows) if row["label"] == "before-nrd-method-switch")
        self.assertEqual(rows[moved + 1]["Method"], "CGNS")
        self.assertNotIn("camera", rows[moved + 1])
        self.assertEqual(rows[moved + 2]["camera"], "Reset camera")

