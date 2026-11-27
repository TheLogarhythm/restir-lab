"""Keep live NRD resources resident and skip inactive downstream passes."""

from functools import partial


def patch_graph(text, replace_once):
    anchor = '    renderGraph.def_property("name", &RenderGraph::getName, &RenderGraph::setName);'
    return replace_once(text, anchor, anchor + """
    renderGraph.def("setLiveNrdEnabled", [](RenderGraph& graph, bool enabled)
    {
        graph.getPassesDictionary()["labLiveNrdEnabled"] = enabled;
    });
    renderGraph.def("getLiveNrdEnabled", [](RenderGraph& graph)
    {
        return graph.getPassesDictionary().getValue("labLiveNrdEnabled", false);
    });
    renderGraph.def("hasLiveNrdBranch", [](const RenderGraph& graph)
    {
        return graph.doesPassExist("ModulateIllumination");
    });""")


def patch_execution(text, replace_once):
    anchor = """    for (const auto& pass : mExecutionList)
    {
        FALCOR_PROFILE(ctx.pRenderContext, pass.name);"""
    return replace_once(text, anchor, """    const bool liveSession = ctx.passesDictionary.keyExists("labLiveNrdEnabled");
    const bool nrdEnabled = ctx.passesDictionary.getValue("labLiveNrdEnabled", false);
    for (const auto& pass : mExecutionList)
    {
        if (liveSession)
        {
            const bool nrdPass =
                pass.name.compare(0, 3, "NRD") == 0 || pass.name == "GBufferRT" || pass.name == "ModulateIllumination";
            if ((nrdPass && !nrdEnabled) || (nrdEnabled && pass.name == "RawComparison")) continue;
        }

        FALCOR_PROFILE(ctx.pRenderContext, pass.name);""")


def patch_capture(text, replace_once):
    anchor = """        for (uint32_t i = 0 ; i < pGraph->getOutputCount() ; i++)
        {
            captureOutput(pRenderContext, pGraph, i);
        }"""
    return replace_once(text, anchor, """        auto& dictionary = pGraph->getPassesDictionary();
        const bool liveSession = dictionary.keyExists("labLiveNrdEnabled");
        const bool nrdEnabled = dictionary.getValue("labLiveNrdEnabled", false);
        for (uint32_t i = 0 ; i < pGraph->getOutputCount() ; i++)
        {
            if (liveSession)
            {
                const auto output = pGraph->getOutputName(i);
                if ((output == "PathTracer.color" && !nrdEnabled) || (output == "RawComparison.dst" && nrdEnabled)) continue;
            }
            captureOutput(pRenderContext, pGraph, i);
        }""")


def patches(replace_once):
    return {
        "RenderGraph.cpp": partial(patch_graph, replace_once=replace_once),
        "RenderGraphExe.cpp": partial(patch_execution, replace_once=replace_once),
    }
