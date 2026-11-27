"""Build interactive Falcor display graphs from the fixed-view experiment settings."""

import json
from pathlib import Path

METHODS = {"Original": 0, "PDF Similarity": 1, "CGNS": 2}
MODES = ("Raw", "Accumulation", "NRD")
BASE_CONFIG = "experiments/configs/falcor-pt-spatial-comparison/restir-pt-spatial-comparison.json"
SOURCES = {"Raw": "PathTracer.color", "Accumulation": "AccumulatePass.output", "NRD": "ModulateIllumination.output"}
VBUFFER = {"samplePattern": "Center", "sampleCount": 1, "useAlphaTest": True, "useDOF": False}

# NRD bindings from the Classroom showcase, derived from pinned Falcor's
# scripts/PathTracerNRD.py (NVIDIA, see renderers/falcor/upstream/LICENSE.md).
NRD_EDGES = (
    ("PathTracer.nrdDiffuseRadianceHitDist", "NRDDiffuseSpecular.diffuseRadianceHitDist"),
    ("PathTracer.nrdSpecularRadianceHitDist", "NRDDiffuseSpecular.specularRadianceHitDist"),
    ("GBufferRT.mvecW", "NRDDiffuseSpecular.mvec"),
    ("GBufferRT.normWRoughnessMaterialID", "NRDDiffuseSpecular.normWRoughnessMaterialID"),
    ("GBufferRT.linearZ", "NRDDiffuseSpecular.viewZ"),
    ("PathTracer.nrdDeltaReflectionHitDist", "NRDReflectionMotionVectors.specularHitDist"),
    ("GBufferRT.linearZ", "NRDReflectionMotionVectors.viewZ"),
    ("GBufferRT.normWRoughnessMaterialID", "NRDReflectionMotionVectors.normWRoughnessMaterialID"),
    ("GBufferRT.mvec", "NRDReflectionMotionVectors.mvec"),
    ("PathTracer.nrdDeltaReflectionRadianceHitDist", "NRDDeltaReflection.diffuseRadianceHitDist"),
    ("NRDReflectionMotionVectors.reflectionMvec", "NRDDeltaReflection.mvec"),
    ("PathTracer.nrdDeltaReflectionNormWRoughMaterialID", "NRDDeltaReflection.normWRoughnessMaterialID"),
    ("PathTracer.nrdDeltaReflectionPathLength", "NRDDeltaReflection.viewZ"),
    ("GBufferRT.posW", "NRDTransmissionMotionVectors.deltaPrimaryPosW"),
    ("PathTracer.nrdDeltaTransmissionPosW", "NRDTransmissionMotionVectors.deltaSecondaryPosW"),
    ("GBufferRT.mvec", "NRDTransmissionMotionVectors.mvec"),
    ("PathTracer.nrdDeltaTransmissionRadianceHitDist", "NRDDeltaTransmission.diffuseRadianceHitDist"),
    ("NRDTransmissionMotionVectors.deltaMvec", "NRDDeltaTransmission.mvec"),
    ("PathTracer.nrdDeltaTransmissionNormWRoughMaterialID", "NRDDeltaTransmission.normWRoughnessMaterialID"),
    ("PathTracer.nrdDeltaTransmissionPathLength", "NRDDeltaTransmission.viewZ"),
    ("PathTracer.nrdEmission", "ModulateIllumination.emission"),
    ("PathTracer.nrdDiffuseReflectance", "ModulateIllumination.diffuseReflectance"),
    ("NRDDiffuseSpecular.filteredDiffuseRadianceHitDist", "ModulateIllumination.diffuseRadiance"),
    ("PathTracer.nrdSpecularReflectance", "ModulateIllumination.specularReflectance"),
    ("NRDDiffuseSpecular.filteredSpecularRadianceHitDist", "ModulateIllumination.specularRadiance"),
    ("PathTracer.nrdDeltaReflectionEmission", "ModulateIllumination.deltaReflectionEmission"),
    ("PathTracer.nrdDeltaReflectionReflectance", "ModulateIllumination.deltaReflectionReflectance"),
    ("NRDDeltaReflection.filteredDiffuseRadianceHitDist", "ModulateIllumination.deltaReflectionRadiance"),
    ("PathTracer.nrdDeltaTransmissionEmission", "ModulateIllumination.deltaTransmissionEmission"),
    ("PathTracer.nrdDeltaTransmissionReflectance", "ModulateIllumination.deltaTransmissionReflectance"),
    ("NRDDeltaTransmission.filteredDiffuseRadianceHitDist", "ModulateIllumination.deltaTransmissionRadiance"),
    ("PathTracer.nrdResidualRadianceHitDist", "ModulateIllumination.residualRadiance"),
)


NRD_PASSES = ("GBufferRT", "NRDDiffuseSpecular", "NRDDeltaReflection", "NRDDeltaTransmission",
              "NRDReflectionMotionVectors", "NRDTransmissionMotionVectors", "ModulateIllumination")


def add_nrd(graph, create_pass, saved=None):
    if saved and len(saved) == len(NRD_PASSES):
        for name in NRD_PASSES:
            graph.addPass(saved[name], name)
        for source, target in NRD_EDGES:
            graph.addEdge(source, target)
        return "ModulateIllumination.output"
    graph.addPass(create_pass("GBufferRT", VBUFFER), "GBufferRT")
    relax = {"method": "RelaxDiffuse", "maxIntensity": 250.0, "worldSpaceMotion": False,
             "enableReprojectionTestSkippingWithoutMotion": True}
    for name, options in (
        ("NRDDiffuseSpecular", {"maxIntensity": 250.0}),
        ("NRDDeltaReflection", {**relax, "spatialVarianceEstimationHistoryThreshold": 1}),
        ("NRDDeltaTransmission", relax),
        ("NRDReflectionMotionVectors", {"method": "SpecularReflectionMv", "worldSpaceMotion": False}),
        ("NRDTransmissionMotionVectors", {"method": "SpecularDeltaMv", "worldSpaceMotion": False}),
    ):
        graph.addPass(create_pass("NRD", options), name)
    graph.addPass(create_pass("ModulateIllumination", {"useResidualRadiance": False}), "ModulateIllumination")
    for source, target in NRD_EDGES:
        graph.addEdge(source, target)
    return "ModulateIllumination.output"


def connect_color_display(graph, create_pass, *, compare_raw):
    graph.addEdge(SOURCES["Raw"], "ToneMapper.rawSrc")
    graph.addEdge(SOURCES["Accumulation"], "ToneMapper.src")
    if compare_raw:
        # Both probe signals use the same stochastic sample and display settings.
        graph.addPass(create_pass("ToneMapper", graph["ToneMapper"].properties), "RawComparison")
        graph.addEdge(SOURCES["Raw"], "RawComparison.src")
        graph.markOutput("RawComparison.dst")


def connect_nrd_display(graph, create_pass):
    graph.addEdge(add_nrd(graph, create_pass), "ToneMapper.nrdSrc")
    graph.markOutput(SOURCES["Raw"])


def select_display(graph, mode):
    tone_mapper = graph["ToneMapper"]
    if hasattr(graph, "setLiveNrdEnabled"):
        graph.setLiveNrdEnabled(mode == "NRD")
        tone_mapper.liveDisplayMode = MODES.index(mode)
    else:
        tone_mapper.liveRawInput = mode == "Raw"
    accumulation = graph["AccumulatePass"]
    accumulation.liveBypass = mode != "Accumulation"
    return SOURCES[mode]


def display_controls(graph):
    tone_mapper = graph["ToneMapper"]
    fields = {"tone_mapper_raw_input": tone_mapper.liveRawInput,
              "accumulation_bypassed": graph["AccumulatePass"].liveBypass}
    if hasattr(graph, "setLiveNrdEnabled"):
        fields.update(tone_mapper_display_mode=tone_mapper.liveDisplayMode,
                      nrd_passes_enabled=graph.getLiveNrdEnabled(),
                      nrd_branch_retained=graph.hasLiveNrdBranch())
    return fields


def build_graph(root, method, mode, exposure, *, compare_raw=False):
    from falcor import RenderGraph, createPass

    if mode not in MODES:
        raise ValueError(f"Unknown post-processing mode: {mode}")
    options = json.loads((Path(root) / BASE_CONFIG).read_text(encoding="utf8"))["graph"]
    options["reSTIRPathTracingOptions"].update(useTemporalResampling=True, labSpatialMethod=METHODS[method])
    graph = RenderGraph("Live ReSTIR PT")
    graph.addPass(createPass("VBufferRT", VBUFFER), "VBufferRT")
    graph.addPass(createPass("PathTracer", options), "PathTracer")
    for channel in ("vbuffer", "viewW", "mvec"):
        graph.addEdge("VBufferRT." + channel, "PathTracer." + channel)
    graph.addPass(createPass("AccumulatePass", {
        "enabled": True, "autoReset": True, "precisionMode": "Single",
    }), "AccumulatePass")
    graph.addEdge(SOURCES["Raw"], "AccumulatePass.input")
    tone_options = {"useSceneMetadata": False, "operator": "Aces", "autoExposure": False,
                    "exposureCompensation": float(exposure), "outputFormat": "RGBA8UnormSrgb"}
    graph.addPass(createPass("ToneMapper", tone_options), "ToneMapper")
    graph.markOutput("ToneMapper.dst")
    if hasattr(graph, "setLiveNrdEnabled"):
        connect_color_display(graph, createPass, compare_raw=compare_raw)
        if mode == "NRD":
            connect_nrd_display(graph, createPass)
    elif mode == "NRD":
        add_nrd(graph, createPass)
        graph.addEdge(SOURCES["NRD"], "ToneMapper.src")
        # The pinned PathTracer reads the color output's dimensions even when
        # only the NRD AOVs feed the displayed output. Keep this allocation live.
        graph.markOutput(SOURCES["Raw"])
    else:
        connect_color_display(graph, createPass, compare_raw=compare_raw)
    return graph, select_display(graph, mode)


def switch_display(graph, previous, selected, *, compare_raw, saved_nrd=None):
    if hasattr(graph, "setLiveNrdEnabled"):
        if selected == "NRD" and not graph.hasLiveNrdBranch():
            from falcor import createPass
            connect_nrd_display(graph, createPass)
    elif previous == "NRD" and selected != "NRD":
        from falcor import createPass

        graph.removeEdge(SOURCES["NRD"], "ToneMapper.src")
        graph.unmarkOutput(SOURCES["Raw"])
        # Inactive NRD edges still influence optional PathTracer AOV allocation
        # in Falcor 9. Detach all consumers and retain their settings for a revisit.
        for name in NRD_PASSES:
            if saved_nrd is not None:
                saved_nrd[name] = graph[name]
            graph.removePass(name)
        connect_color_display(graph, createPass, compare_raw=compare_raw)
    elif selected == "NRD" and previous != "NRD":
        from falcor import createPass

        graph.removeEdge(SOURCES["Accumulation"], "ToneMapper.src")
        graph.removeEdge(SOURCES["Raw"], "ToneMapper.rawSrc")
        if compare_raw:
            graph.removePass("RawComparison")
        add_nrd(graph, createPass, saved_nrd)
        graph.addEdge(SOURCES["NRD"], "ToneMapper.src")
        graph.markOutput(SOURCES["Raw"])
    source = select_display(graph, selected)
    if selected == "Accumulation":
        graph["AccumulatePass"].reset()
    return source


def reset_nrd(graph):
    passes = [graph[name] for name in NRD_PASSES if name.startswith("NRD")]
    if all(hasattr(render_pass, "resetLiveHistory") for render_pass in passes):
        for render_pass in passes:
            render_pass.resetLiveHistory()
        return "native"
    target = "ToneMapper.nrdSrc" if hasattr(graph, "setLiveNrdEnabled") else "ToneMapper.src"
    graph.removeEdge(SOURCES["NRD"], target)
    graph.addEdge(SOURCES["NRD"], target)
    return "recompile"
