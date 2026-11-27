"""Compose the qualified Falcor spatial methods using one private shader layout."""
from pathlib import Path
from textwrap import indent

from ... import cgns_cached_overlay as cgns
from ... import pdf_pt_overlay as pdf


def shader_sources(runtime, settings):
    """Keep the PDF reservoir payload and choose selection and MIS at dispatch."""
    runtime = Path(runtime)
    original = pdf.read_sources(runtime)
    outputs = pdf.build_overlay(original, settings["pdf-similarity"]["shader"], profile="normal")
    cgns_sources = cgns.shader_outputs(runtime, settings["cgns"]["shader"])
    module = "shaders/ReSTIRPathTracing/"

    # The cached selector and decoder are exactly the production CGNS code.
    outputs[module + "ResamplingCommon.slang"] = cgns_sources[module + "ResamplingCommon.slang"]
    for stage in cgns.STAGES:
        name = module + f"cgns_cached_{stage}.cs.slang"
        outputs[name] = cgns_sources[name]
    for name, count in cgns.CONSUMERS.items():
        rel = module + name
        source = outputs.get(rel) or (runtime / rel).read_text(encoding="utf8")
        field = "    Texture1D<float2> neighborOffsets;"
        source = cgns.replace(source, field, field + "\n    Texture2D<uint> cgnsNeighbors;")
        decode = "decodeCgnsNeighbor(cgnsNeighbors[pixel], params.frameDim.x)"
        for index in ("i", "retraceIndex / 2"):
            lookup = f"getNextNeighborPixel(startIndex, neighborOffsets, pixel, {index}, spatialRadius)"
            if lookup in source:
                source = cgns.replace(source, lookup, f"(restirpt.labSpatialMethod == 2u ? {decode} : {lookup})")
        if source.count(decode) != count:
            raise ValueError("Unexpected live neighbor lookup in " + name)
        outputs[rel] = source

    restirpt = module + "ReSTIRPT.slang"
    anchor = "    RWStructuredBuffer<PathReservoir> pathReservoirs;"
    outputs[restirpt] = cgns.replace(outputs[restirpt], anchor, "    uint labSpatialMethod;\n" + anchor)

    # Initial tracing shares the PDF payload, with no extra RNG use in either mode.
    # CGNS and ordinary spatial reuse skip the independent PDF temporal history.
    path_tracer = "shaders/RenderPasses/PathTracer/PathTracer.slang"
    anchor = "        restirpt.pathReservoirs[labOffset].labCamera = restirpt.labCameraStamp(params.frameDim);"
    outputs[path_tracer] = cgns.replace(outputs[path_tracer], anchor,
                                       "        if (restirpt.labSpatialMethod == 1u)\n    " + anchor)
    temporal = module + "TemporalResampling.cs.slang"
    anchor = ("        PathReservoir initial = reservoirs[offset];\n"
              "        labCombineHistory(pixel, initial);")
    source = cgns.replace(outputs[temporal], anchor, """
        bool usePdf = restirpt.labSpatialMethod == 1u;
        PathReservoir initial;
        if (usePdf)
        {
            initial = reservoirs[offset];
            labCombineHistory(pixel, initial);
        }""".lstrip("\n"))
    anchor = ("        reservoirs[offset].labMoment = initial.labMoment;\n"
              "        reservoirs[offset].labCount = initial.labCount;\n"
              "        reservoirs[offset].labCamera = initial.labCamera;")
    outputs[temporal] = cgns.replace(source, anchor, "        if (usePdf)\n        {\n" + indent(anchor, "    ") + "\n        }")

    # Reuse the production PDF acceptance and apply the original native
    # confidence and division expressions to ordinary spatial reuse and CGNS.
    workload = module + "GenerateRetraceWorkload.cs.slang"
    source = outputs[workload]
    start = source.index("                        // LAB_PDF_PT_EFFECTIVE_M_ACCEPT")
    end = source.index("\n\n                        if (ReSTIRPT::ShiftMapping", start)
    accept_pdf = source[start:end]
    accept_native = ("                        neighborValidMask[centralOffset].setValid(i, true);\n\n"
                     "                        cSum += neighborReservoir.M;")
    if accept_native not in original[workload].replace("\r\n", "\n"):
        raise ValueError("Unexpected live native neighbor acceptance")
    outputs[workload] = source[:start] + (
        "                        if (restirpt.labSpatialMethod == 1u)\n"
        "                        {\n" + indent(accept_pdf, "    ") + "\n"
        "                        }\n"
        "                        else\n"
        "                        {\n" + indent(accept_native, "    ") + "\n"
        "                        }"
    ) + source[end:]

    spatial = module + "SpatialResampling.cs.slang"
    source = outputs[spatial]
    anchor = "        PairwiseFactor C = { centralReservoir.M, centralReservoir.M };"
    source = cgns.replace(source, anchor,
                          "        const bool usePdf = restirpt.labSpatialMethod == 1u;\n" + anchor)
    anchor = "            canonicalWeight = C.c_sum > 0.f ? C.c_c / C.c_sum : 0.f;"
    source = cgns.replace(source, anchor,
                          "            canonicalWeight = usePdf && !(C.c_sum > 0.f) ? 0.f : C.c_c / C.c_sum;")
    anchor = ("            neighborReservoir.M = neighborValidMask[centralOffset].labPdfNeighborM;\n"
              "            if (neighborReservoir.M <= 0.f) continue;")
    source = cgns.replace(source, anchor, "            if (usePdf)\n            {\n"
                          + indent(anchor, "    ") + "\n            }")
    anchor = "            float currentWeightTerm = 1;"
    source = cgns.replace(source, anchor,
                          "            float reverseNeighborM = usePdf ? neighborReservoir.M : (C.c_sum - C.c_c);\n" + anchor)
    outputs[spatial] = cgns.replace(source, "canonicalAtOtherPHat * neighborReservoir.M",
                                    "canonicalAtOtherPHat * reverseNeighborM", count=2)
    shift = module + "Shift.slang"
    source = outputs[shift]
    anchor = "    float denom = srcTerm + Jacobian * PathRISState::toScalar(dstIntegrand) * C.c_c;"
    source = cgns.replace(source, "    float srcTerm = PathRISState::toScalar(srcReservoir.integrand) * srcReservoir.M;\n" + anchor,
                          "    const bool usePdf = restirpt.labSpatialMethod == 1u;\n"
                          "    float neighborM = usePdf ? srcReservoir.M : (C.c_sum - C.c_c);\n"
                          "    float srcTerm = PathRISState::toScalar(srcReservoir.integrand) * neighborM;\n" + anchor)
    outputs[shift] = cgns.replace(source, "    float misWeight = denom > 0.f ? srcReservoir.M / C.c_sum * srcTerm / denom : 0.f;",
                                   "    float misWeight = usePdf && !(denom > 0.f) ? 0.f : srcReservoir.M / C.c_sum * srcTerm / denom;")
    use_runtime_output_options(runtime, outputs)
    return outputs


def use_runtime_output_options(runtime, outputs):
    """Share programs across AOV wiring changes, including first NRD use."""
    folder = "shaders/RenderPasses/PathTracer/"
    key = folder + "Params.slang"
    source = (runtime / key).read_text(encoding="utf8")
    anchor = "__exported import Utils.Math.BitTricks;"
    outputs[key] = cgns.replace(source, anchor, anchor + """

struct LabPathOutputOptions
{
    bool guideData;
    bool nrdData;
    bool nrdAdditionalData;
    bool nrdEnabled;
};""")
    fields = (
        ("kOutputGuideData", "guideData"),
        ("kOutputNRDData", "nrdData"),
        ("kOutputNRDAdditionalData", "nrdAdditionalData"),
    )
    for name, counts in (
        ("GeneratePaths.cs.slang", (1, 2, 1)),
        ("PathTracer.slang", (5, 4, 2)),
        ("PathTracerNRD.slang", (0, 2, 7)),
        ("ResolvePass.cs.slang", (1, 1, 0)),
    ):
        key = folder + name
        source = outputs.get(key) or (runtime / key).read_text(encoding="utf8")
        if name != "PathTracerNRD.slang":
            anchor = "    PathTracerParams params;"
            source = cgns.replace(source, anchor, "    LabPathOutputOptions labPathOutputs;\n" + anchor)
        for (old, new), count in zip(fields, counts):
            source = cgns.replace(source, f"if ({old}", f"if (labPathOutputs.{new}", count)
        outputs[key] = source

    tracer_key = folder + "PathTracer.slang"
    generator_key = folder + "GeneratePaths.cs.slang"
    tracer = outputs[tracer_key]
    for helper in ("setBackgroundGuideData", "setPrimarySurfaceGuideData"):
        anchor = f"static void {helper}(inout GuideData"
        tracer = cgns.replace(tracer, anchor, f"static void {helper}(bool writeGuideData, inout GuideData")
        start = tracer.index(f"static void {helper}(")
        test = tracer.index("if (labPathOutputs.guideData)", start)
        tracer = tracer[:test] + tracer[test:].replace("if (labPathOutputs.guideData)", "if (writeGuideData)", 1)
    tracer = cgns.replace(tracer, "setPrimarySurfaceGuideData(path.guideData,",
                          "setPrimarySurfaceGuideData(labPathOutputs.guideData, path.guideData,")
    outputs[generator_key] = cgns.replace(
        outputs[generator_key], "PathTracer::setBackgroundGuideData(sampleGuideData[",
        "PathTracer::setBackgroundGuideData(labPathOutputs.guideData, sampleGuideData[",
    )

    # Delta miss paths also write guides when specular-motion passes are active.
    # Keep their original behavior when NRD is enabled, and skip only the guide stores otherwise.
    miss = tracer.index("    void handleMiss(")
    start = tracer.index("#if defined(DELTA_REFLECTION_PASS)\n", miss)
    next_mode = tracer.index("#elif defined(DELTA_TRANSMISSION_PASS)\n", start)
    end = tracer.index("#endif\n", next_mode)
    for beginning, ending in ((next_mode, end), (start, next_mode)):
        body = tracer.index("\n", beginning) + 1
        tracer = tracer[:body] + ("        if (labPathOutputs.nrdEnabled)\n        {\n"
                                  + indent(tracer[body:ending], "    ") + "        }\n") + tracer[ending:]
    outputs[tracer_key] = tracer


def host_sources(upstream):
    module = upstream / "Source/Modules/ReSTIRPathTracing"
    generated = cgns.host_sources(module)
    header = generated["ReSTIRPathTracing.h"]
    header = cgns.replace(header, "            bool useSpatialResampling = true;",
                         "            uint32_t labSpatialMethod = 0; // 0 ordinary, 1 PDF, 2 CGNS\n"
                         "            bool useSpatialResampling = true;")
    key = '                ar("useSpatialResampling", useSpatialResampling);'
    header = cgns.replace(header, key, key + '\n                ar("labSpatialMethod", labSpatialMethod);')
    key = "        void setOptions(const Options& options);"
    generated["ReSTIRPathTracing.h"] = cgns.replace(header, key, key + """
        void resetLiveHistory() { mResetTemporalReservoirs = true; }
        void setLiveSpatialMethod(uint32_t method)
        {
            mOptions.labSpatialMethod = method;
            resetLiveHistory();
        }""")

    cpp = generated["ReSTIRPathTracing.cpp"]
    anchor = '        var["numSpatialRounds"] = mOptions.spatialIterations;'
    cpp = cgns.replace(cpp, anchor, anchor + """
        if (var.findMember("labSpatialMethod").isValid())
            var["labSpatialMethod"] = mOptions.labSpatialMethod;""")
    cpp = cgns.replace(cpp, "const bool spatial = mOptions.useSpatialResampling;",
                       "const bool spatial = mOptions.useSpatialResampling && mOptions.labSpatialMethod == 2;")
    # Reflect the dedicated CGNS passes up front for eligible live graphs.
    # Only CGNS executes them or allocates their shading caches.
    first = cpp.index("        if (mOptions.useAreaReservoirs || mOptions.usePairedNeighbors ||")
    create = cpp.index("        createComputePass(mpCgnsAttributes,", first)
    last = cpp.index("        createComputePass(mpSpatialRetrace,", create)
    block = cpp[create:last]
    cpp = cpp[:first] + """
        if (!mOptions.useAreaReservoirs && !mOptions.usePairedNeighbors &&
            mOptions.spatialNeighborCount == 1 && useCompactRetraceSchedule() && !mOptions.useDoFReconnectionShift)
        {
""" + indent(block, "    ") + "        }\n" + cpp[last:]
    cpp = cgns.replace(cpp, "if (mOptions.spatialIterations) cacheCgnsAttributes",
                       """if (mOptions.labSpatialMethod > 2)
            FALCOR_THROW("Unknown live spatial method");
        if (mOptions.labSpatialMethod != 0 && !mpCgnsAttributes)
            FALCOR_THROW("Live spatial methods require point reservoirs, one unpaired neighbor, compact retrace and no DoF shift");
        if (mOptions.labSpatialMethod == 2 && mOptions.spatialIterations) cacheCgnsAttributes""")
    cpp = cgns.replace(cpp, "            selectCgnsNeighbors(pRenderContext, pVBuffer, iteration);",
                       "            if (mOptions.labSpatialMethod == 2) selectCgnsNeighbors(pRenderContext, pVBuffer, iteration);")
    anchor = '        var["splatSampleInfo"] = mpReservoirSplatInfo;\n\n        const uint32_t tileSize'
    cpp = cgns.replace(cpp, anchor, '        var["cgnsNeighbors"] = mpCgnsNeighbors;\n' + anchor)
    generated["ReSTIRPathTracing.cpp"] = cpp

    tracer = (upstream / "Source/RenderPasses/PathTracer/PathTracer.cpp").read_text(encoding="utf8")
    anchor = '    pass.def("reset", &PathTracer::reset);'
    tracer = cgns.replace(tracer, anchor, anchor + """
    auto resetLiveHistory = [](PathTracer& tracer)
    {
        tracer.mParams.frameCount = 0;
        tracer.mParams.seed = 0;
        tracer.mOptionsChanged = true;
        if (tracer.mpReSTIRPathTracing) tracer.mpReSTIRPathTracing->resetLiveHistory();
    };
    pass.def("resetLiveHistory", resetLiveHistory);
    pass.def("setLiveSpatialMethod", [resetLiveHistory](PathTracer& tracer, uint32_t method)
    {
        if (method > 2) FALCOR_THROW("Invalid spatial method {}", method);
        if (tracer.mReSTIRPathTracingOptions.labSpatialMethod == method) return;
        tracer.mReSTIRPathTracingOptions.labSpatialMethod = method;
        if (tracer.mpReSTIRPathTracing) tracer.mpReSTIRPathTracing->setLiveSpatialMethod(method);
        resetLiveHistory(tracer);
    });""")
    anchor = "const std::string kGeneratePathsFilename"
    tracer = cgns.replace(tracer, anchor, """bool liveNrdEnabled(const Falcor::RenderData& renderData)
{
    return renderData.getDictionary().getValue("labLiveNrdEnabled", true);
}

void bindPathOutputOptions(
    const Falcor::ShaderVar& var, bool enableNrd, bool guideData, bool nrdData, bool nrdAdditionalData)
{
    const auto outputs = var["labPathOutputs"];
    outputs["guideData"] = guideData;
    outputs["nrdData"] = enableNrd && nrdData;
    outputs["nrdAdditionalData"] = enableNrd && nrdAdditionalData;
    outputs["nrdEnabled"] = enableNrd;
}

""" + anchor)
    anchor = "    // Launch separate passes to trace delta reflection and transmission paths."
    tracer = cgns.replace(tracer, anchor, "    const bool enableNrd = liveNrdEnabled(renderData);\n\n" + anchor)
    anchor = "    if (mOutputNRDAdditionalData || specularMVecEnabled)\n    {\n        FALCOR_ASSERT"
    tracer = cgns.replace(tracer, anchor,
                          "    if ((enableNrd && mOutputNRDAdditionalData) || specularMVecEnabled)\n    {\n        FALCOR_ASSERT")
    anchor = "        if (mOutputGuideData || mOutputNRDData)"
    tracer = cgns.replace(tracer, anchor, "        if (mOutputGuideData || (enableNrd && mOutputNRDData))")
    anchor = "    const ref<Texture>& pInputVBuffer = renderData.getTexture(kInputVBuffer);"
    tracer = cgns.replace(tracer, anchor,
                          "    bindPathOutputOptions(var, liveNrdEnabled(renderData), mOutputGuideData, mOutputNRDData, mOutputNRDAdditionalData);\n\n"
                          + anchor)
    anchor = "    if (!mOutputGuideData && !mOutputNRDData && mFixedSampleCount && mStaticParams.samplesPerPixel == 1)"
    tracer = cgns.replace(tracer, anchor,
                          "    const bool enableNrd = liveNrdEnabled(renderData);\n"
                          "    if (!mOutputGuideData && !(enableNrd && mOutputNRDData) && mFixedSampleCount && mStaticParams.samplesPerPixel == 1)")
    anchor = '    var["sampleCount"] = renderData.getTexture(kInputSampleCount); // Can be nullptr'
    tracer = cgns.replace(
        tracer, anchor, "    bindPathOutputOptions(var, enableNrd, mOutputGuideData, mOutputNRDData, false);\n" + anchor,
    )
    # The defaults remain available to imported, unrelated shader modules.
    # Dispatch options no longer change these program keys on graph promotion.
    for program in ("mpGeneratePaths", "tracePass.pProgram", "mpResolvePass"):
        for define, option in (("OUTPUT_GUIDE_DATA", "mOutputGuideData"), ("OUTPUT_NRD_DATA", "mOutputNRDData")):
            tracer = cgns.replace(tracer, f'    {program}->addDefine("{define}", {option} ? "1" : "0");\n', "")
    for program in ("mpGeneratePaths", "tracePass.pProgram"):
        tracer = cgns.replace(tracer, f'    {program}->addDefine("OUTPUT_NRD_ADDITIONAL_DATA", mOutputNRDAdditionalData ? "1" : "0");\n', "")
    generated["PathTracer.cpp"] = tracer
    return generated


def nrd_host_sources(upstream):
    """Manage the pinned NRD pass lifetime and history in the private runtime."""
    folder = upstream / "Source/RenderPasses/NRDPass"
    header = (folder / "NRDPass.h").read_text(encoding="utf8")
    header = cgns.replace(header, "#include <NRD.h>", "#include <NRD.h>\n#include <memory>\n#include <optional>")
    header = cgns.replace(header, "    nrd::Denoiser* mpDenoiser = nullptr;", """    struct DenoiserDeleter
    {
        void operator()(nrd::Denoiser* denoiser) const { nrd::DestroyDenoiser(*denoiser); }
    };
    std::unique_ptr<nrd::Denoiser, DenoiserDeleter> mpDenoiser;
    std::optional<DenoisingMethod> mInitializedMethod;""")
    header = cgns.replace(header, "    bool mRecreateDenoiser = false;\n", "")
    anchor = "    virtual void setScene(RenderContext* pRenderContext, const ref<Scene>& pScene) override;"
    header = cgns.replace(header, anchor, anchor + "\n    void resetLiveHistory() { mResetLiveHistory = true; }")
    anchor = "    uint32_t mFrameIndex = 0;"
    header = cgns.replace(header, anchor, anchor + "\n    bool mResetLiveHistory = false;")

    source = (folder / "NRDPass.cpp").read_text(encoding="utf8")
    anchor = '#include "Core/API/NativeHandleTraits.h"'
    source = cgns.replace(source, anchor, anchor + '\n#include "Utils/Scripting/ScriptBindings.h"')
    anchor = "    mScreenSize = RenderPassHelpers::calculateIOSize(mOutputSizeSelection, mScreenSize, compileData.defaultTexDims);"
    source = cgns.replace(source, anchor, "    const uint2 previousSize = mScreenSize;\n" + anchor)
    source = cgns.replace(source, "    mFrameIndex = 0;\n    reinit();", """    if (mInitializedMethod == mDenoisingMethod && mScreenSize.x == previousSize.x && mScreenSize.y == previousSize.y)
    {
        resetLiveHistory();
        return;
    }
    reinit();""")
    source = cgns.replace(source, 'mRecreateDenoiser = widget.dropdown("Denoising method"',
                         'widget.dropdown("Denoising method"')
    source = cgns.replace(source, "    if (mRecreateDenoiser)", "    if (mInitializedMethod != mDenoisingMethod)")
    source = cgns.replace(source, """    // Create a new denoiser instance.
    mpDenoiser = nullptr;

    const nrd::LibraryDesc& libraryDesc = nrd::GetLibraryDesc();""", """    mInitializedMethod.reset();
    mpDenoiser.reset();""")
    source = cgns.replace(source, "    nrd::Result res = nrd::CreateDenoiser(denoiserCreationDesc, mpDenoiser);",
                         "    nrd::Denoiser* denoiser = nullptr;\n"
                         "    nrd::Result res = nrd::CreateDenoiser(denoiserCreationDesc, denoiser);")
    source = cgns.replace(source, """    createResources();
    createPipelines();""", """    mpDenoiser.reset(denoiser);
    createResources();
    createPipelines();
    mInitializedMethod = mDenoisingMethod;
    mFrameIndex = 0;
    resetLiveHistory();""")
    source = cgns.replace(source, "    if (mFrameIndex == 0)", "    if (mFrameIndex == 0 || mResetLiveHistory)")
    anchor = "    mCommonSettings.frameIndex = mFrameIndex;"
    source = cgns.replace(source, anchor, anchor + """
    // Clear NRD's history for one dispatch while preserving consecutive frame indices.
    mCommonSettings.accumulationMode =
        mResetLiveHistory ? nrd::AccumulationMode::CLEAR_AND_RESTART : nrd::AccumulationMode::CONTINUE;""")
    anchor = "    pRenderContext->submit();"
    source = cgns.replace(source, anchor, anchor + "\n    mResetLiveHistory = false;")
    anchor = "    registry.registerClass<RenderPass, NRDPass>();"
    source = cgns.replace(source, anchor, anchor + """
    ScriptBindings::registerBinding([](pybind11::module& m)
    {
        pybind11::class_<NRDPass, RenderPass, ref<NRDPass>> pass(m, "NRDPass");
        pass.def("resetLiveHistory", &NRDPass::resetLiveHistory);
    });""")
    return {"NRDPass.h": header, "NRDPass.cpp": source}
