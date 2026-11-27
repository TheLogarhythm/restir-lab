"""One visible Mogwai process, with switching performed between rendered frames."""

from collections import deque
import gc
import json
import os
from pathlib import Path
import time
import traceback

from .graph import METHODS, MODES, build_graph, display_controls, reset_nrd, switch_display


def write_json(path, data):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf8")
    temporary.replace(path)


def camera_state(camera):
    def vector(v):
        return [float(v.x), float(v.y), float(v.z)]
    return {"position": vector(camera.position), "target": vector(camera.target),
            "up": vector(camera.up), "focal_length": float(camera.focalLength),
            "near_plane": float(camera.nearPlane), "aperture_radius": float(camera.apertureRadius)}


def apply_pose(camera, pose):
    from falcor import float3
    camera.position = float3(*pose["position"])
    camera.target = float3(*pose["target"])
    camera.up = float3(*pose["up"])


class Session:
    def __init__(self, renderer, config, output):
        from .scenes import SCENE_NAMES
        from .window import WindowIdentity
        self.renderer = renderer
        self.config, self.output = config, Path(output)
        self.root = Path(config["root"])
        self.sequence = config["sequence"]
        self.steps = deque(self.sequence or [])
        self.issued_camera = False
        self.camera_ready = False
        self.commands = deque()
        self.records, self.visits = [], {}
        self.reset_probes = []
        self.probe_next_reset = None
        self.graph_revision = 0
        self.saved_nrd = {}
        self.graph = None
        self.scene_device = None
        self.finished = False
        self.frame = self.age = 0
        self.settled_render_seconds = 0.0
        self.changed_at = None
        self.nrd_ready = False
        self.awaiting_loaded_frame = False
        self.capture_index = 0
        self.state = {"Scene": None, "Method": config["method"], "Display": config["mode"]}
        self.window = WindowIdentity()
        renderer.setLiveSessionPanel(SCENE_NAMES, tuple(METHODS), MODES)
        renderer.ui = True
        renderer.frameCapture.outputDir = str(self.output)
        renderer.frameCapture.captureAllOutputs = False
        self.update_panel()
        if "width" in config and "height" in config:
            requested = (config["width"], config["height"])
            actual = self.window.resize_client(renderer.resizeFrameBuffer, self.poll_actions, *requested)
            self.log("launch_resolution", requested=requested, client=actual)
            if config.get("precompile_shaders") and actual != requested:
                raise RuntimeError(f"Mogwai client size {actual} could not be set to {requested} before precompilation")
        self.log("selector_ready")
        if config["scene"] and not self.finished:
            renderer.queueLiveSessionAction("Scene", config["scene"])

    def update_panel(self, status="", *, selections=None):
        scene, method, display = (self.state if selections is None else selections).values()
        self.renderer.setLiveSessionState(scene or "", method, display, status)
        title = status or " | ".join((scene or "Choose a scene", method, display))
        self.window.title(self.window.hwnd, "ReSTIR PT | " + title)

    def log(self, event, **fields):
        record = {"event": event, "monotonic_s": time.perf_counter(), "pid": os.getpid(),
                  "hwnd": self.window.hwnd, "visible": bool(self.window.visible(self.window.hwnd)),
                  "frame": self.frame, **self.state, **fields}
        with (self.output / "events.jsonl").open("a", encoding="utf8") as out:
            out.write(json.dumps(record) + "\n")
        return record

    def poll_actions(self):
        for group, label in self.renderer.pollLiveSessionActions():
            if (group, label) == ("View", "Quit"):
                self.close()
                break
            self.commands.append((group, label, time.perf_counter()))

    def run(self):
        # Process native actions between frames. The first render after changing
        # the graph uses the selected method and starts the new output's history.
        while not self.finished:
            try:
                self.poll_actions()
                if self.finished:
                    break
                if self.commands:
                    self.perform(*self.commands.popleft())
                if self.finished:
                    break
                render_started = time.perf_counter() if self.sequence is not None else None
                self.renderer.renderFrame()
                if self.graph is None or not self.remember_scene_device():
                    time.sleep(0.005)
                    continue
                if self.age == 0:
                    self.settled_render_seconds = 0.0
                elif render_started is not None:
                    self.settled_render_seconds += time.perf_counter() - render_started
                self.frame += 1
                self.age += 1
                if self.changed_at is not None:
                    self.log("first_presented_frame", elapsed_ms=1000 * (time.perf_counter() - self.changed_at),
                             visit=self.visits[tuple(self.state.values())], method_id=self.method_id,
                             camera=camera_state(self.renderer.scene.camera))
                    self.changed_at = None
                    self.nrd_ready |= self.state["Display"] == "NRD"
                    if self.awaiting_loaded_frame:
                        self.update_panel()
                        self.awaiting_loaded_frame = False
                if self.sequence is not None:
                    self.drive_acceptance()
            except Exception:
                self.scene_device = None
                # A failed active graph can throw on every subsequent frame.
                # Drop it on error so the selector returns to a usable viewport.
                if self.sequence is None and self.graph is not None:
                    self.renderer.removeGraph(self.graph)
                    self.graph = None
                    self.saved_nrd.clear()
                self.fail()

    def remember_scene_device(self):
        import falcor

        if self.scene_device is None:
            try:
                self.scene_device = self.graph.get_output("ToneMapper.dst").device
            except falcor.RuntimeError as error:
                # Mogwai can skip rendering while occluded, leaving a new graph uncompiled.
                if "The graph wasn't successfuly compiled yet." not in str(error):
                    raise
                return False
        return True

    def release_scene(self):
        from falcor import recreateLiveDevice
        from .window import process_commit_bytes
        # Status UI and display changes can invalidate the graph's output lookup.
        # The device from its first completed frame remains usable for draining.
        device, self.scene_device = self.scene_device, None
        if device is None:
            if self.graph is not None:
                self.renderer.removeGraph(self.graph)
                self.graph = None
                self.saved_nrd.clear()
            if self.renderer.scene is not None:
                self.renderer.unloadScene()
                gc.collect()
                recreateLiveDevice()
            return
        before = process_commit_bytes()
        device.wait()
        self.renderer.removeGraph(self.graph)
        self.graph = None
        self.saved_nrd.clear()
        self.renderer.unloadScene()
        gc.collect()
        detached = process_commit_bytes()
        # Falcor 9 has three in-flight command heaps. Cycle all three and cross
        # another fence before the next import allocates textures and geometry.
        for _ in range(4):
            device.end_frame()
        device.wait()
        drained = process_commit_bytes()
        del device
        # GFX caches reflection layouts and pipelines by device. Give the next
        # scene a fresh device while Mogwai keeps its existing GLFW window.
        recreateLiveDevice()
        self.log("scene_released", before_bytes=before, detached_bytes=detached,
                 drained_bytes=drained, fresh_device_bytes=process_commit_bytes())

    def transition(self, group, label, requested_at=None):
        from .scenes import load_scene
        if self.state[group] == label and self.graph is not None:
            return
        self.changed_at = time.perf_counter() if requested_at is None else requested_at
        self.age = 0
        self.log("selection", group=group, label=label, initial=self.state["Scene"] is None)
        wanted = {**self.state, group: label}
        if wanted["Scene"] is None:
            self.state = wanted
            self.update_panel()
            return
        replace_scene = group == "Scene" or self.graph is None
        compare_raw = self.uses_raw_comparison(wanted["Scene"])
        status = None
        if replace_scene:
            self.nrd_ready = False
            status = "Loading " + wanted["Scene"]
        elif group == "Display" and wanted["Display"] == "NRD" and not self.nrd_ready:
            status = "Preparing NRD for " + wanted["Scene"]
        if status is not None:
            from falcor import presentLiveSessionStatus

            self.update_panel(status, selections=wanted)
            self.awaiting_loaded_frame = True
            presentLiveSessionStatus()
        if replace_scene:
            self.release_scene()
            self.exposure = load_scene(self.renderer, wanted["Scene"], self.root)
            if self.sequence is not None:
                self.renderer.setLiveCameraInputEnabled(False)
            self.preset_camera = camera_state(self.renderer.scene.camera)
            graph, source = build_graph(self.root, wanted["Method"], wanted["Display"], self.exposure,
                                        compare_raw=compare_raw)
            self.renderer.addGraph(graph)
            self.graph = graph
            self.graph_revision += 1
        else:
            graph, source = self.graph, self.source
            tracer = graph["PathTracer"]
            if group == "Method":
                tracer.setLiveSpatialMethod(METHODS[wanted["Method"]])
                if compare_raw and self.steps and self.steps[0].get("probe") == "method-reset":
                    self.probe_next_reset = "method-switch-" + wanted["Method"]
                if wanted["Display"] == "Accumulation":
                    graph["AccumulatePass"].reset()
            elif "NRD" in (wanted["Display"], self.state["Display"]):
                tracer.resetLiveHistory()
            if group == "Display":
                source = switch_display(graph, self.state["Display"], wanted["Display"],
                                        compare_raw=compare_raw, saved_nrd=self.saved_nrd)
            if wanted["Display"] == "NRD":
                self.log("nrd_reset", mechanism=reset_nrd(graph))
        method_id = graph["PathTracer"].properties["reSTIRPathTracingOptions"]["labSpatialMethod"]
        if method_id != METHODS[wanted["Method"]]:
            raise RuntimeError(f"Runtime returned spatial method {method_id} for {wanted['Method']}")
        self.graph, self.source, self.method_id = graph, source, method_id
        self.state = wanted
        if not self.awaiting_loaded_frame:
            self.update_panel()
        signature = tuple(self.state.values())
        self.visits[signature] = self.visits.get(signature, 0) + 1
        self.log("graph_installed", method_id=self.method_id, display_input=self.source, graph_revision=self.graph_revision,
                 camera=camera_state(self.renderer.scene.camera), exposure_ev=graph["ToneMapper"].exposureCompensation,
                 **display_controls(graph))

    def perform(self, group, label, requested_at):
        if group in self.state:
            self.transition(group, label, requested_at=requested_at)
        elif label == "Quit":
            self.close()
        elif self.graph is None:
            return
        elif label == "Save image":
            self.capture("manual")
        else:
            pose = dict(self.preset_camera)
            if label == "Nudge camera right":
                # Translate the same position and look-at vector so direction is preserved.
                for key in ("position", "target"):
                    pose[key] = list(pose[key])
                    pose[key][0] += 0.25
            apply_pose(self.renderer.scene.camera, pose)
            self.age = 0
            self.camera_ready = True
            if self.uses_raw_comparison(self.state["Scene"]) and self.state["Display"] == "Accumulation":
                self.probe_next_reset = label
            self.log("camera_command", label=label, camera=camera_state(self.renderer.scene.camera))

    def uses_raw_comparison(self, scene):
        return self.sequence is not None and scene == "Classroom"

    def capture(self, name, *, save_image=True):
        if save_image:
            self.capture_index += 1
            base = f"{self.capture_index:03d}-{name}"
            self.renderer.frameCapture.baseFilename = base
            self.renderer.frameCapture.capture()
        frame = int(self.renderer.clock.frame)
        texture = self.graph.get_output("ToneMapper.dst")
        raw_file = None
        if save_image and self.uses_raw_comparison(self.state["Scene"]) and self.state["Display"] != "NRD":
            raw_file = f"{base}.RawComparison.dst.{frame}.png"
        mean_frame_ms = None
        if self.sequence is not None and self.age > 1:
            mean_frame_ms = 1000 * self.settled_render_seconds / (self.age - 1)
        file = f"{base}.ToneMapper.dst.{frame}.png" if save_image else None
        record = self.log("capture" if save_image else "rendered_frame", label=name, file=file, raw_file=raw_file,
                          resolution=[int(texture.width), int(texture.height)], clock_frame=frame,
                          settled_frames=self.age, mean_settled_render_ms=mean_frame_ms,
                          samples_per_pixel=self.graph["PathTracer"].properties["samplesPerPixel"],
                          method_id=self.method_id, display_input=self.source,
                          camera=camera_state(self.renderer.scene.camera), preset_camera=self.preset_camera,
                          **display_controls(self.graph))
        return record

    def record_step(self, step):
        return self.capture(step["label"])

    def drive_acceptance(self):
        if self.probe_next_reset and self.age == 1:
            label = self.probe_next_reset.lower().replace(" ", "-")
            self.reset_probes.append(self.capture("first-" + label))
            self.probe_next_reset = None
        if not self.steps:
            write_json(self.output / "renderer-complete.json", {"pid": os.getpid(), "hwnd": self.window.hwnd,
                       "captures": self.records, "reset_probes": self.reset_probes, "total_frames": self.frame})
            self.close()
            return
        step = self.steps[0]
        for group in self.state:
            if self.state[group] != step[group]:
                self.renderer.queueLiveSessionAction(group, step[group])
                return
        if step.get("camera") and not self.issued_camera:
            self.issued_camera = True
            self.camera_ready = False
            self.renderer.queueLiveSessionAction("View", step["camera"])
            return
        if self.issued_camera and not self.camera_ready:
            return
        if self.age < step["frames"]:
            return
        self.records.append(self.record_step(step))
        self.steps.popleft()
        self.issued_camera = False
        self.camera_ready = False
        self.age = 0

    def close(self, code=0):
        from falcor import exit as close_renderer
        self.finished = True
        self.scene_device = None
        close_renderer(code)

    def fail(self):
        message = traceback.format_exc()
        fatal = self.sequence is not None
        write_json(self.output / ("error.json" if fatal else "last-error.json"),
                   {"pid": os.getpid(), "error": message, "state": self.state})
        self.changed_at = None
        self.awaiting_loaded_frame = False
        if fatal:
            self.close(1)
        else:
            if self.graph is None:
                self.state["Scene"] = None
            self.update_panel("Selection failed. Choose another item or see last-error.json.")
            self.log("selection_failed", error=message)


def start(renderer, settings):
    output = Path(settings).parent
    try:
        config = json.loads(Path(settings).read_text(encoding="utf8"))
        session_type = Session
        if config.get("precompile_shaders"):
            from .precompile import PrecompileSession

            session_type = PrecompileSession
        session = session_type(renderer, config, output)
        session.run()
        return session
    except Exception:
        from falcor import exit as close_renderer
        write_json(output / "error.json", {"pid": os.getpid(), "error": traceback.format_exc()})
        close_renderer(1)
        return None
