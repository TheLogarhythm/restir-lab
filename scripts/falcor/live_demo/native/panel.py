"""Place managed live-session controls in Mogwai's existing Graphs window."""

from functools import partial


def patch_renderer(text, replace_once):
    anchor = "    void Renderer::onDroppedFile(const std::filesystem::path& path)\n    {\n"
    text = replace_once(text, anchor, anchor + """        if (auto* settings = MogwaiSettings::get(this); settings && settings->isLiveSessionPanelEnabled())
            return;

""")
    return replace_once(
        text,
        "        const float4 clearColor(0.38f, 0.52f, 0.10f, 1);",
        """        const auto* settings = mGraphs.empty() ? MogwaiSettings::get(this) : nullptr;
        const float4 clearColor = settings && settings->isLiveSessionPanelEnabled()
            ? float4(0.03f, 0.03f, 0.03f, 1.f)
            : float4(0.38f, 0.52f, 0.10f, 1.f);""",
    )


def patch_gui(text, replace_once):
    text = replace_once(text, """    // This struct is used to cache the mouse events
    struct MouseEvents
    {
        bool buttonPressed[3] = {0};
        bool buttonReleased[3] = {0};
    };

    MouseEvents mMouseEvents;
    void setIoMouseEvents();
    void resetMouseEvents();

""", "")
    text = replace_once(text, """void GuiImpl::setIoMouseEvents()
{
    ImGuiIO& io = ImGui::GetIO();
    memcpy(io.MouseDown, mMouseEvents.buttonPressed, sizeof(mMouseEvents.buttonPressed));
}

void GuiImpl::resetMouseEvents()
{
    for (size_t i = 0; i < std::size(mMouseEvents.buttonPressed); i++)
    {
        if (mMouseEvents.buttonReleased[i])
        {
            mMouseEvents.buttonPressed[i] = mMouseEvents.buttonReleased[i] = false;
        }
    }
}

""", "")
    text = replace_once(text, "    // Set the mouse state\n    mpWrapper->setIoMouseEvents();\n\n", "")
    text = replace_once(text, "    mpWrapper->resetMouseEvents();\n\n", "")
    # ImGui's queue separates successive edges across frames when needed.
    for index in range(3):
        text = replace_once(text, f"mpWrapper->mMouseEvents.buttonPressed[{index}] = isDown;",
                            f"io.AddMouseButtonEvent({index}, isDown);")
    text = replace_once(text, """        io.MousePos.x = event.pos.x * io.DisplaySize.x;
        io.MousePos.y = event.pos.y * io.DisplaySize.y;""",
                        "        io.AddMousePosEvent(event.pos.x * io.DisplaySize.x, event.pos.y * io.DisplaySize.y);")
    return replace_once(text, "        io.MouseWheel += event.wheelDelta.y;",
                        "        io.AddMouseWheelEvent(0.f, event.wheelDelta.y);")


def patch_settings_header(text, replace_once):
    anchor = "        void onOptionsChange(const Settings::Options& settings) override;\n"
    text = replace_once(text, anchor, anchor + """
        using LiveActions = std::vector<std::pair<std::string, std::string>>;
        static MogwaiSettings* get(Renderer* pRenderer);
        bool isLiveSessionPanelEnabled() const { return mLiveSessionPanelEnabled; }
        void setLiveSessionPanel(
            const std::vector<std::string>& scenes,
            const std::vector<std::string>& methods,
            const std::vector<std::string>& displays
        );
        void setLiveSessionState(
            const std::string& scene, const std::string& method, const std::string& display, const std::string& status
        );
        void queueLiveSessionAction(const std::string& group, const std::string& label);
        LiveActions pollLiveSessionActions();
""")
    anchor = "        void renderGraphs(Gui* pGui);\n"
    return replace_once(text, anchor, anchor + """        void renderLiveSessionPanel(Gui::Widgets& widgets);

        struct LiveSelector
        {
            const char* group;
            const char* title;
            Gui::DropdownList choices;
            uint32_t selected = 0;
        };
        static uint32_t findLiveChoice(const LiveSelector& selector, const std::string& label);

        bool mLiveSessionPanelEnabled = false;
        LiveSelector mLiveScene{"Scene", "Scene##LabLiveSession"};
        LiveSelector mLiveMethod{"Method", "Spatial reuse##LabLiveSession"};
        LiveSelector mLiveDisplay{"Display", "Display##LabLiveSession"};
        std::string mLiveStatus;
        LiveActions mLiveActions;
""")


def patch_settings(text, replace_once):
    text = replace_once(text, "#include <iomanip>", "#include <algorithm>\n#include <iomanip>\n#include <utility>")
    anchor = "    void MogwaiSettings::renderGraphs(Gui* pGui)\n"
    text = replace_once(text, anchor, """    MogwaiSettings* MogwaiSettings::get(Renderer* pRenderer)
    {
        const auto& extensions = pRenderer->getExtensions();
        // Renderer::onLoad installs MogwaiSettings before the optional extensions.
        return extensions.empty() ? nullptr : static_cast<MogwaiSettings*>(extensions.front().get());
    }

    void MogwaiSettings::setLiveSessionPanel(
        const std::vector<std::string>& scenes,
        const std::vector<std::string>& methods,
        const std::vector<std::string>& displays
    )
    {
        FALCOR_CHECK(mpRenderer->getWindow(), "The live session requires a Mogwai window");
        FALCOR_CHECK(!scenes.empty() && !methods.empty() && !displays.empty(), "The live selectors require choices");
        const auto assignChoices = [](LiveSelector& selector, const std::vector<std::string>& options)
        {
            for (const auto& label : options)
                selector.choices.push_back({static_cast<uint32_t>(selector.choices.size()), label});
            selector.selected = 0;
        };
        mLiveScene.choices = {{0, "Choose a scene..."}};
        mLiveMethod.choices.clear();
        mLiveDisplay.choices.clear();
        assignChoices(mLiveScene, scenes);
        assignChoices(mLiveMethod, methods);
        assignChoices(mLiveDisplay, displays);
        mLiveActions.clear();
        mLiveStatus.clear();
        mLiveSessionPanelEnabled = true;
        mShowGraphUI = true;
        mpRenderer->toggleUI(true);
    }

    uint32_t MogwaiSettings::findLiveChoice(const LiveSelector& selector, const std::string& label)
    {
        const auto& choices = selector.choices;
        const auto choice = std::find_if(choices.begin(), choices.end(), [&](const auto& item) { return item.label == label; });
        FALCOR_CHECK(choice != choices.end(), "Unknown live {} choice '{}'", selector.group, label);
        return choice->value;
    }

    void MogwaiSettings::setLiveSessionState(
        const std::string& scene, const std::string& method, const std::string& display, const std::string& status
    )
    {
        FALCOR_CHECK(isLiveSessionPanelEnabled(), "The live session panel has not been configured");
        const uint32_t sceneChoice = scene.empty() ? 0 : findLiveChoice(mLiveScene, scene);
        const uint32_t methodChoice = findLiveChoice(mLiveMethod, method);
        const uint32_t displayChoice = findLiveChoice(mLiveDisplay, display);
        mLiveScene.selected = sceneChoice;
        mLiveMethod.selected = methodChoice;
        mLiveDisplay.selected = displayChoice;
        mLiveStatus = status;
    }

    void MogwaiSettings::queueLiveSessionAction(const std::string& group, const std::string& label)
    {
        FALCOR_CHECK(isLiveSessionPanelEnabled(), "The live session panel has not been configured");
        for (const auto* selector : {&mLiveScene, &mLiveMethod, &mLiveDisplay})
        {
            if (group == selector->group)
            {
                const uint32_t value = findLiveChoice(*selector, label);
                if (selector != &mLiveScene || value != 0)
                    mLiveActions.emplace_back(group, label);
                return;
            }
        }
        FALCOR_CHECK(
            group == "View" && (label == "Reset camera" || label == "Nudge camera right" || label == "Save image" || label == "Quit"),
            "Unknown live session action '{}: {}'",
            group,
            label
        );
        mLiveActions.emplace_back(group, label);
    }

    MogwaiSettings::LiveActions MogwaiSettings::pollLiveSessionActions()
    {
        FALCOR_CHECK(isLiveSessionPanelEnabled(), "The live session panel has not been configured");
        auto* window = mpRenderer->getWindow();
        window->pollForEvents();
        if (window->shouldClose())
        {
            mLiveActions.clear();
            queueLiveSessionAction("View", "Quit");
        }
        return std::exchange(mLiveActions, {});
    }

    void MogwaiSettings::renderLiveSessionPanel(Gui::Widgets& widgets)
    {
        for (const auto* selector : {&mLiveScene, &mLiveMethod, &mLiveDisplay})
        {
            auto selected = selector->selected;
            if (widgets.dropdown(selector->title, selector->choices, selected))
                queueLiveSessionAction(selector->group, selector->choices[selected].label);
        }
        if (!mLiveStatus.empty())
            widgets.textWrapped(mLiveStatus);
        if (mpRenderer->getActiveGraph())
        {
            if (widgets.button("Reset camera"))
                queueLiveSessionAction("View", "Reset camera");
            if (widgets.button("Save image", true))
                queueLiveSessionAction("View", "Save image");
        }
        widgets.separator();
    }

""" + anchor)
    text = replace_once(text, "        if (!mShowGraphUI || mpRenderer->mGraphs.empty()) return;",
                        "        if (!mShowGraphUI || (!isLiveSessionPanelEnabled() && mpRenderer->mGraphs.empty())) return;")
    anchor = "        if (!mShowGraphUI) return;\n\n        if (mpRenderer->mEditorProcess == 0)"
    text = replace_once(text, anchor, """        if (!mShowGraphUI) return;

        if (isLiveSessionPanelEnabled()) renderLiveSessionPanel(w);
        if (mpRenderer->mGraphs.empty()) return;

        if (!isLiveSessionPanelEnabled() && mpRenderer->mEditorProcess == 0)""")
    text = replace_once(text, """        // Active graph output
        mpRenderer->graphOutputsGui(w); // MOGWAI shouldn't be here
        w.separator();""", """        if (!isLiveSessionPanelEnabled())
        {
            // The live Display selector owns the active graph output.
            mpRenderer->graphOutputsGui(w);
            w.separator();
        }""")
    text = replace_once(text, '            if (file.item("Load Script", "Ctrl+O"))',
                        '            if (!isLiveSessionPanelEnabled() && file.item("Load Script", "Ctrl+O"))')
    text = replace_once(text, '            if (file.item("Load Scene", "Ctrl+Shift+O"))',
                        '            if (!isLiveSessionPanelEnabled() && file.item("Load Scene", "Ctrl+Shift+O"))')
    text = replace_once(text, "            file.separator();", "            if (!isLiveSessionPanelEnabled()) file.separator();")
    for kind in ("Scripts", "Scenes"):
        anchor = f"""            {{
                auto &appData = mpRenderer->getAppData();
                auto recent{kind} = file.menu("Recent {kind}");"""
        text = replace_once(text, anchor, "            if (!isLiveSessionPanelEnabled())\n" + anchor)
    anchor = "                if (e.key == Input::Key::O)\n                {\n"
    return replace_once(text, anchor, anchor + "                    if (isLiveSessionPanelEnabled()) return true;\n")


def patch_scripting(text, replace_once):
    text = replace_once(text, '#include "Mogwai.h"', '#include "Mogwai.h"\n#include "MogwaiSettings.h"')
    text = replace_once(text, "#include <pybind11/pybind11.h>", "#include <pybind11/pybind11.h>\n#include <pybind11/stl.h>")
    anchor = '        pybind11::class_<Renderer> renderer(m, "Renderer");\n'
    return replace_once(text, anchor, anchor + """        renderer.def("setLiveSessionPanel", [](Renderer* pRenderer,
            const std::vector<std::string>& scenes, const std::vector<std::string>& methods, const std::vector<std::string>& displays)
        {
            MogwaiSettings::get(pRenderer)->setLiveSessionPanel(scenes, methods, displays);
        });
        renderer.def("setLiveSessionState", [](Renderer* pRenderer,
            const std::string& scene, const std::string& method, const std::string& display, const std::string& status)
        {
            MogwaiSettings::get(pRenderer)->setLiveSessionState(scene, method, display, status);
        });
        renderer.def("queueLiveSessionAction", [](Renderer* pRenderer, const std::string& group, const std::string& label)
        {
            MogwaiSettings::get(pRenderer)->queueLiveSessionAction(group, label);
        });
        renderer.def("pollLiveSessionActions", [](Renderer* pRenderer)
        {
            return MogwaiSettings::get(pRenderer)->pollLiveSessionActions();
        });
        renderer.def("setLiveCameraInputEnabled", [](Renderer* pRenderer, bool enabled)
        {
            const auto scene = pRenderer->getScene();
            FALCOR_CHECK(scene, "Live camera input requires a loaded scene");
            scene->setCameraControlsEnabled(enabled);
        }, "enabled"_a);

""")


def patches(replace_once):
    return {
        "Gui.cpp": partial(patch_gui, replace_once=replace_once),
        "MogwaiSettings.cpp": partial(patch_settings, replace_once=replace_once),
        "MogwaiSettings.h": partial(patch_settings_header, replace_once=replace_once),
        "MogwaiScripting.cpp": partial(patch_scripting, replace_once=replace_once),
    }
