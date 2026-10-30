"""Native Falcor graphs: unaccumulated linear PathTracer output."""


def build_graph(mode):
    if mode not in ("path-tracer", "restir-pt"):
        raise ValueError("Unknown Falcor mode")
    from falcor import RenderGraph, createPass

    graph = RenderGraph("LabPathTracer")
    graph.addPass(
        createPass(
            "VBufferRT",
            {"samplePattern": "Center", "sampleCount": 1, "useAlphaTest": True},
        ),
        "VBufferRT",
    )
    options = {
        "samplesPerPixel": 1,
        "tracePassMode": "MinimalPayload",
        "useReSTIRPT": mode == "restir-pt",
        "emissiveSampler": "Power",
        "maxSurfaceBounces": 10,
        "maxDiffuseBounces": 10,
        "maxSpecularBounces": 10,
        "useRussianRoulette": True,
        "reSTIRPathTracingOptions": {"useAreaReservoirs": False},
    }
    graph.addPass(createPass("PathTracer", options), "PathTracer")
    for name in ("vbuffer", "viewW", "mvec"):
        graph.addEdge("VBufferRT." + name, "PathTracer." + name)
    graph.markOutput("PathTracer.color")
    return graph
