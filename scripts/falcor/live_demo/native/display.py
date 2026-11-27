"""Select Raw or Accumulation on the live graph without copying raw radiance."""

from .device import replace_once


DISPLAY_PASSES = ("AccumulatePass", "ToneMapper")


def accumulate_sources(path):
    header = path.with_suffix(".h").read_text(encoding="utf8")
    header = replace_once(
        header, "    void reset();",
        """    void reset();
    bool getLiveBypass() const { return mLiveBypass; }
    void setLiveBypass(bool bypass) { mLiveBypass = bypass; }""",
    )
    header = replace_once(header, "    bool mEnabled = true;",
                          "    bool mEnabled = true;\n    bool mLiveBypass = false;")
    cpp = path.read_text(encoding="utf8")
    cpp = replace_once(
        cpp, '    pass.def("reset", &AccumulatePass::reset);',
        '    pass.def("reset", &AccumulatePass::reset);\n'
        '    pass.def_property("liveBypass", &AccumulatePass::getLiveBypass, &AccumulatePass::setLiveBypass);',
    )
    cpp = replace_once(
        cpp, "void AccumulatePass::execute(RenderContext* pRenderContext, const RenderData& renderData)\n{",
        """void AccumulatePass::execute(RenderContext* pRenderContext, const RenderData& renderData)
{
    if (mLiveBypass)
    {
        mUpdateFlags = IScene::UpdateFlags::None;
        return;
    }
""",
    )
    return {path.name: cpp, path.with_suffix(".h").name: header}


def tone_mapper_sources(path):
    header = path.with_suffix(".h").read_text(encoding="utf8")
    header = replace_once(
        header, "    // Scripting functions",
        """    // Scripting functions
    enum class LiveInput : uint32_t { Raw, Accumulation, NRD };
    bool getLiveRawInput() const { return mLiveInput == LiveInput::Raw; }
    void setLiveRawInput(bool enabled) { mLiveInput = enabled ? LiveInput::Raw : LiveInput::Accumulation; }
    uint32_t getLiveDisplayMode() const { return static_cast<uint32_t>(mLiveInput); }
    void setLiveDisplayMode(uint32_t mode)
    {
        FALCOR_CHECK(mode <= static_cast<uint32_t>(LiveInput::NRD), "Unknown live display mode {}", mode);
        mLiveInput = static_cast<LiveInput>(mode);
    }""",
    )
    header = replace_once(header, "    bool mAutoExposure = false;",
                          "    bool mAutoExposure = false;\n    LiveInput mLiveInput = LiveInput::Accumulation;")
    cpp = path.read_text(encoding="utf8")
    cpp = replace_once(cpp, 'const char kSrc[] = "src";',
                       'const char kSrc[] = "src";\nconst char kRawSrc[] = "rawSrc";\nconst char kNrdSrc[] = "nrdSrc";')
    cpp = replace_once(
        cpp, '    pybind11::class_<ToneMapper, RenderPass, ref<ToneMapper>> pass(m, "ToneMapper");',
        '    pybind11::class_<ToneMapper, RenderPass, ref<ToneMapper>> pass(m, "ToneMapper");\n'
        '    pass.def_property("liveRawInput", &ToneMapper::getLiveRawInput, &ToneMapper::setLiveRawInput);\n'
        '    pass.def_property("liveDisplayMode", &ToneMapper::getLiveDisplayMode, &ToneMapper::setLiveDisplayMode);',
    )
    cpp = replace_once(
        cpp, '    reflector.addInput(kSrc, "Source texture");',
        '    reflector.addInput(kSrc, "Source texture");\n'
        '    reflector.addInput(kRawSrc, "Direct path-tracer radiance").flags(RenderPassReflection::Field::Flags::Optional);\n'
        '    reflector.addInput(kNrdSrc, "NRD reconstruction").flags(RenderPassReflection::Field::Flags::Optional);',
    )
    cpp = replace_once(cpp, "    auto pSrc = renderData.getTexture(kSrc);",
                       """    const char* input = kSrc;
    if (mLiveInput == LiveInput::Raw) input = kRawSrc;
    if (mLiveInput == LiveInput::NRD) input = kNrdSrc;
    auto pSrc = renderData.getTexture(input);""")
    return {path.name: cpp, path.with_suffix(".h").name: header}


def display_sources(upstream, pass_name):
    source = upstream / "Source/RenderPasses" / pass_name / (pass_name + ".cpp")
    return {"AccumulatePass": accumulate_sources, "ToneMapper": tone_mapper_sources}[pass_name](source)
