"""Falcor PathTracer graph for per-seed reference rendering."""


def build_graph(validation=False):
    from falcor import RenderGraph, createPass

    graph = RenderGraph('LabReference')
    graph.addPass(createPass('VBufferRT', {
        'samplePattern': 'Center', 'sampleCount': 1, 'useAlphaTest': True,
    }), 'VBufferRT')
    graph.addPass(createPass('PathTracer', {
        'samplesPerPixel': 1,
        'sampleGenerator': 1,
        'tracePassMode': 'MinimalPayload',
        'useReSTIRPT': False,
        'useRTXDI': False,
        'emissiveSampler': 'Power',
        'maxSurfaceBounces': 10,
        'maxDiffuseBounces': 10,
        'maxSpecularBounces': 10,
        'maxTransmissionBounces': 10,
        'useRussianRoulette': True,
    }), 'PathTracer')
    graph.addPass(createPass('AccumulatePass', {
        'enabled': True, 'precisionMode': 'SingleCompensated',
    }), 'AccumulatePass')
    for name in ('vbuffer', 'viewW', 'mvec'):
        graph.addEdge('VBufferRT.' + name, 'PathTracer.' + name)
    graph.addEdge('PathTracer.color', 'AccumulatePass.input')
    graph.markOutput('AccumulatePass.output')
    if validation:
        graph.markOutput('PathTracer.color')
    return graph
