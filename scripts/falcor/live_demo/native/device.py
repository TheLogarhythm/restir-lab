"""Patch device rotation into the private, single-window Falcor live runtime."""

from pathlib import Path

from . import panel, retained_nrd

ROOT = Path(__file__).resolve().parents[4] / "renderers/falcor/upstream/Source"
SOURCES = {
    "SampleApp.cpp": ROOT / "Falcor/Core/SampleApp.cpp",
    "Gui.cpp": ROOT / "Falcor/Utils/UI/Gui.cpp",
    "RenderGraph.cpp": ROOT / "Falcor/RenderGraph/RenderGraph.cpp",
    "RenderGraphExe.cpp": ROOT / "Falcor/RenderGraph/RenderGraphExe.cpp",
    "Mogwai.cpp": ROOT / "Mogwai/Mogwai.cpp",
    "MogwaiSettings.cpp": ROOT / "Mogwai/MogwaiSettings.cpp",
    "MogwaiSettings.h": ROOT / "Mogwai/MogwaiSettings.h",
    "MogwaiScripting.cpp": ROOT / "Mogwai/MogwaiScripting.cpp",
    "FrameCapture.cpp": ROOT / "Mogwai/Extensions/Capture/FrameCapture.cpp",
}


def replace_once(text, anchor, replacement):
    if text.count(anchor) != 1:
        raise ValueError(f"Unexpected Falcor source anchor: {anchor}")
    return text.replace(anchor, replacement, 1)


def patch_sample_app(text):
    text = replace_once(text, '#include "SampleApp.h"', '#include "SampleApp.h"\n#include "GlobalState.h"')
    text = replace_once(text, "namespace Falcor\n{\n", """namespace Falcor
{
namespace
{
thread_local uint32_t gLiveFrameDepth = 0;

struct LiveFrameGuard
{
    LiveFrameGuard() { ++gLiveFrameDepth; }
    ~LiveFrameGuard() { --gLiveFrameDepth; }
};
} // namespace

""")
    text = replace_once(text, "void SampleApp::renderFrame()\n{",
                        "void SampleApp::renderFrame()\n{\n    const LiveFrameGuard liveFrameGuard;")
    text = replace_once(text, "    mpProfilerUI.reset();\n\n    mpDevice->wait();",
                        "    mpProfilerUI.reset();\n\n    if (mpDevice) mpDevice->wait();")
    return replace_once(text, '    m.def("renderFrame", renderFrame);', """    m.def("renderFrame", renderFrame);

    m.def("presentLiveSessionStatus", [this]()
    {
        FALCOR_CHECK(gLiveFrameDepth == 0, "Live status can only be presented between render frames");
        const LiveFrameGuard liveFrameGuard;
        if (!mpSwapchain || mpSwapchain->isOccluded()) return;

        mProgressBar.close();
        auto* context = mpDevice->getRenderContext();
        context->clearFbo(mpTargetFBO.get(), float4(0.03f, 0.03f, 0.03f, 1.f), 1.f, 0, FboAttachmentType::Color);
        renderUI();
#if FALCOR_ENABLE_PROFILER
        mpDevice->getProfiler()->endFrame(context);
#endif
        const int imageIndex = mpSwapchain->acquireNextImage();
        FALCOR_CHECK(imageIndex >= 0, "Failed to acquire the live status back buffer");
        const Texture* image = mpSwapchain->getImage(imageIndex).get();
        context->copyResource(image, mpTargetFBO->getColorTexture(0).get());
        context->resourceBarrier(image, Resource::State::Present);
        context->submit();
        mpSwapchain->present();
        mpDevice->endFrame();
        mInputState.endFrame();
    });

    m.def("recreateLiveDevice", [this]()
    {
        FALCOR_CHECK(gLiveFrameDepth == 0, "The live device can only be recreated between render frames");
        FALCOR_CHECK(mpDevice && mpWindow && mpSwapchain, "The live device requires a window and swapchain");
        FALCOR_CHECK(getActivePythonRenderGraphDevice() == mpDevice, "The live device requires an active Mogwai session");

        const auto deviceDesc = mpDevice->getDesc();
        auto swapchainDesc = mpSwapchain->getDesc();
        swapchainDesc.enableVSync = mVsyncOn;
        const auto fboDesc = mpTargetFBO->getDesc();
        auto* programs = mpDevice->getProgramManager();
        const auto debugShaderInfo = programs->isGenerateDebugInfoEnabled();
        const auto compilerFlags = programs->getForcedCompilerFlags();
        const auto compilerArgs = programs->getGlobalCompilerArguments();

        auto restorePresenter = [&]()
        {
            const auto size = mpWindow->getClientAreaSize();
            swapchainDesc.width = size.x;
            swapchainDesc.height = size.y;
            mpSwapchain = make_ref<Swapchain>(mpDevice, swapchainDesc, mpWindow->getApiHandle());
            mpTargetFBO = Fbo::create2D(mpDevice, size.x, size.y, fboDesc);
            initUI();
            mpPixelZoom = std::make_unique<PixelZoom>(mpDevice, mpTargetFBO.get());
            setActivePythonRenderGraphDevice(mpDevice);
        };

        mpDevice->wait();
        mpPausedRenderOutput.reset();
        mpProfilerUI.reset();
        mpPixelZoom.reset();
        mpGui.reset();
        mpTextRenderer.reset();
        mpTargetFBO.reset();
        mpSwapchain.reset();
        setActivePythonRenderGraphDevice(nullptr);

        // A surviving external resource would keep the device and its caches alive.
        // Restore the current presenter before reporting that the caller must release it.
        const int oldReferences = mpDevice->refCount();
        if (oldReferences != 1)
        {
            // Retire the previous swapchain images before restoring the presenter.
            mpDevice->wait();
            mpDevice->wait();
            restorePresenter();
            FALCOR_THROW("Cannot recreate the live device while {} other Falcor references remain", oldReferences - 1);
        }

        mpDevice.reset();
        mpDevice = make_ref<Device>(deviceDesc);
        auto* newPrograms = mpDevice->getProgramManager();
        newPrograms->setGenerateDebugInfoEnabled(debugShaderInfo);
        newPrograms->setForcedCompilerFlags(compilerFlags);
        newPrograms->setGlobalCompilerArguments(compilerArgs);
        restorePresenter();
        logInfo("Recreated the graphics device for the existing live window.");
    });""")


def patch_mogwai(text):
    text = replace_once(
        text,
        "        getDevice()->wait(); // Need to do that because clearing the graphs will try to release some state objects which might be in use",
        "        if (getDevice()) getDevice()->wait();",
    )
    text = replace_once(
        text, "    void Renderer::unloadScene()\n    {\n        setScene(nullptr);\n    }",
        "    void Renderer::unloadScene()\n    {\n        setScene(nullptr);\n        mpSampler.reset();\n    }",
    )
    return panel.patch_renderer(text, replace_once)


def patch_capture(text):
    text = retained_nrd.patch_capture(text, replace_once)
    text = replace_once(text, "        mpImageProcessing = std::make_unique<ImageProcessing>(pRenderer->getDevice());\n", "")
    return replace_once(
        text, "                mpImageProcessing->copyColorChannel(",
        "                ImageProcessing imageProcessing(mpRenderer->getDevice());\n"
        "                imageProcessing.copyColorChannel(",
    )


def patched_sources():
    patches = {
        "SampleApp.cpp": patch_sample_app,
        "Mogwai.cpp": patch_mogwai,
        "FrameCapture.cpp": patch_capture,
        **panel.patches(replace_once),
        **retained_nrd.patches(replace_once),
    }
    return {name: patch(SOURCES[name].read_text(encoding="utf8")) for name, patch in patches.items()}
