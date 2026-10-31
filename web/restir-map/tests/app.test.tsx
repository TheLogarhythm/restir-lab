import { describe, expect, it, beforeAll } from "vitest";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "../src/App";
import type { Paper, Relation } from "../src/data/types";

const resizeCallbacks = new Set<() => void>();
const notifyResize = () => resizeCallbacks.forEach((callback) => callback());
beforeAll(() => {
  globalThis.ResizeObserver = class {
    private callback: () => void;
    constructor(callback: ResizeObserverCallback) {
      this.callback = () => callback([], this);
    }
    observe() {
      resizeCallbacks.add(this.callback);
    }
    unobserve() {
      resizeCallbacks.delete(this.callback);
    }
    disconnect() {
      resizeCallbacks.delete(this.callback);
    }
  };
});
const papers: Paper[] = [
  {
    paper_id: "di",
    short_title: "ReSTIR DI",
    title: "Direct lighting",
    authors: ["Bitterli"],
    year: 2020,
    venue: "TOG",
    publication_status: "published",
    doi: null,
    tags: ["foundations"],
    role: "mainline",
    problem: "Direct-light sampling",
    contributions: ["Spatiotemporal reuse"],
    changes: "Reservoir reuse",
    limitations: ["Direct lighting"],
    links: { paper: "https://example.org/di", pdf: null, code: null },
    sources: [],
    verification: { metadata: "verified", content: "full_text", notes: "" },
    pdf: {
      status: "missing",
      local_file: null,
      sha256: null,
      version: "",
      source_url: null,
    },
  },
  {
    paper_id: "gi",
    short_title: "ReSTIR GI",
    title: "Indirect paths",
    authors: ["Ouyang"],
    year: 2021,
    venue: "CGF",
    publication_status: "published",
    doi: null,
    tags: ["transport"],
    role: "branch",
    problem: "Indirect-path sampling",
    contributions: ["Multiple bounces"],
    changes: "Extends reuse to indirect lighting",
    limitations: ["Reprojection"],
    links: {
      paper: "https://example.org/gi",
      pdf: "https://example.org/gi.pdf",
      code: null,
    },
    sources: [],
    verification: { metadata: "verified", content: "full_text", notes: "" },
    pdf: {
      status: "missing",
      local_file: null,
      sha256: null,
      version: "",
      source_url: null,
    },
  },
];
const evidence = {
  source_url: "https://example.org/gi.pdf",
  locator: "§1 Introduction",
  explanation: "Extends direct-light reuse to indirect paths.",
  checked: "2026-10-30",
  method: "full_text_review",
};
const relations: Relation[] = [
  {
    id: "di-gi",
    predecessor: "di",
    successor: "gi",
    type: "inheritance",
    citing_paper: "gi",
    cited_paper: "di",
    verification: "verified",
    evidence: [evidence],
  },
];

describe("reading workflow", () => {
  it("resizes the desktop details from the measured collection and releases the override below desktop", async () => {
    const originalWidth = window.innerWidth;
    Object.defineProperty(window, "innerWidth", { value: 1920, configurable: true });
    try {
      render(<App papers={papers} relations={relations} />);
      const sidebar = screen.getByRole("complementary", { name: "Paper collection" });
      const workspace = sidebar.parentElement!;
      sidebar.getBoundingClientRect = () => ({ width: 450 }) as DOMRect;
      act(() => notifyResize());
      expect(workspace.style.getPropertyValue("--paper-details-width")).toBe("450px");
      sidebar.getBoundingClientRect = () => ({ width: 500 }) as DOMRect;
      act(() => notifyResize());
      expect(workspace.style.getPropertyValue("--paper-details-width")).toBe("500px");
      Object.defineProperty(window, "innerWidth", { value: 1000, configurable: true });
      fireEvent(window, new Event("resize"));
      expect(workspace.style.getPropertyValue("--paper-details-width")).toBe("");
    } finally {
      Object.defineProperty(window, "innerWidth", { value: originalWidth, configurable: true });
    }
  });
  it.each(["inheritance", "citation"] as const)("opens %s evidence from a focused edge without changing the paper selection", async (type) => {
    const user = userEvent.setup();
    render(<App papers={papers} relations={[{ ...relations[0], type }]} />);
    if (type === "citation") await user.click(screen.getByRole("button", { name: "All connections" }));
    await user.click(screen.getByRole("button", { name: "ReSTIR DI, 2020, Mainline" }));
    const edge = screen.getByRole("button", { name: /ReSTIR DI → ReSTIR GI.*evidence/i });
    const hit = edge.querySelector(".edge-hit")!;
    expect(hit.getAttribute("vector-effect")).toBe("non-scaling-stroke");
    await user.hover(hit);
    expect(window.location.hash).toBe("#paper=di");
    expect(screen.queryByRole("dialog")).toBeNull();
    await user.click(hit);
    expect(screen.getByRole("dialog").textContent).toContain(evidence.explanation);
    await user.keyboard("{Escape}");
    act(() => edge.focus());
    for (const key of ["{Enter}", " "]) {
      await user.keyboard(key);
      expect(screen.getByRole("dialog").textContent).toContain(evidence.explanation);
      expect(window.location.hash).toBe("#paper=di");
      await user.keyboard("{Escape}");
      expect(document.activeElement).toBe(edge);
    }
  });
  it("does not replay a previous zoom action after the graph resizes", async () => {
    const user = userEvent.setup();
    render(<App papers={papers} relations={relations} />);
    const di = screen.getByRole("button", { name: "ReSTIR DI, 2020, Mainline" });
    await user.click(di);
    const getScale = () =>
      Number(
        di
          .parentElement!.getAttribute("transform")!
          .match(/scale\(([-\d.]+)\)/)![1],
      );
    const fitted = getScale();
    await user.click(screen.getByRole("button", { name: "Zoom in" }));
    expect(getScale()).toBeGreaterThan(fitted);
    const container = screen.getByRole("group", {
      name: "ReSTIR research network",
    }).parentElement!;
    Object.defineProperty(container, "clientWidth", {
      value: 700,
      configurable: true,
    });
    act(() => notifyResize());
    expect(getScale()).toBeCloseTo(fitted);
  });
  it("links list, network, persistent details and share state, including keyboard selection", async () => {
    const user = userEvent.setup();
    render(<App papers={papers} relations={relations} />);
    await user.click(
      within(screen.getByRole("complementary", { name: "Paper collection" })).getByRole(
        "button",
        { name: /ReSTIR DI/ },
      ),
    );
    expect(window.location.hash).toBe("#paper=di");
    expect(
      screen
        .getByRole("button", { name: "ReSTIR DI, 2020, Mainline" })
        .getAttribute("aria-pressed"),
    ).toBe("true");
    expect(
      within(screen.getByRole("complementary", { name: "Paper details" })).getByRole(
        "heading",
        { name: "ReSTIR DI" },
      ),
    ).toBeTruthy();
    const gi = screen.getByRole("button", {
      name: "ReSTIR GI, 2021, Branch",
    });
    gi.focus();
    await user.keyboard("{Enter}");
    expect(window.location.hash).toBe("#paper=gi");
    expect(
      within(screen.getByRole("complementary", { name: "Paper collection" }))
        .getByRole("button", { name: /ReSTIR GI/ })
        .getAttribute("aria-pressed"),
    ).toBe("true");
    await user.click(screen.getByRole("button", { name: "Share selected paper" }));
    expect(await navigator.clipboard.readText()).toContain(
      "/restir-lab/#paper=gi",
    );
    await user.click(screen.getByRole("button", { name: /Clear selection/ }));
    expect(
      screen.queryByRole("complementary", { name: "Paper details" }),
    ).toBeNull();
    expect(window.location.hash).toBe("");
  });
  it("restores a shared selection and filters both views without losing the reading panel", async () => {
    window.history.replaceState(null, "", "/restir-lab/#paper=gi");
    const user = userEvent.setup();
    render(<App papers={papers} relations={relations} />);
    expect(
      screen.getByRole("complementary", { name: "Paper details" }).textContent,
    ).toContain("ReSTIR GI");
    await user.type(
      screen.getByRole("searchbox", { name: "Search papers" }),
      "Bitterli",
    );
    expect(
      screen.getByRole("button", { name: "ReSTIR DI, 2020, Mainline" }),
    ).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: "ReSTIR GI, 2021, Branch" }),
    ).toBeNull();
    expect(
      screen.getByRole("complementary", { name: "Paper details" }).textContent,
    ).toContain("ReSTIR GI");
    await user.click(screen.getByRole("button", { name: "Clear filters" }));
    await user.selectOptions(
      screen.getByRole("combobox", { name: "Research area" }),
      "transport",
    );
    expect(
      screen.queryByRole("button", { name: "ReSTIR DI, 2020, Mainline" }),
    ).toBeNull();
    expect(
      screen.getByRole("button", { name: "ReSTIR GI, 2021, Branch" }),
    ).toBeTruthy();
  });
  it("shows evidence separately from its relation label", async () => {
    const user = userEvent.setup();
    render(<App papers={papers} relations={relations} />);
    await user.click(
      screen.getByRole("button", { name: "ReSTIR GI, 2021, Branch" }),
    );
    await user.click(screen.getByRole("button", { name: "Connections" }));
    await user.click(screen.getByText("Earlier work"));
    const detail = screen.getByRole("complementary", { name: "Paper details" });
    expect(
      within(detail).getByText("Extends direct-light reuse to indirect paths."),
    ).toBeTruthy();
    expect(
      within(detail)
        .getByRole("link", { name: /§1 Introduction/ })
        .getAttribute("href"),
    ).toBe("https://example.org/gi.pdf");
    await user.click(
      within(detail).getByRole("button", { name: /Read ReSTIR DI/ }),
    );
    expect(window.location.hash).toBe("#paper=di");
  });
  it("traps dialog focus and restores it to its trigger on Escape", async () => {
    const user = userEvent.setup();
    render(<App papers={papers} relations={relations} />);
    const trigger = screen.getByRole("button", { name: /About this map/ });
    await user.click(trigger);
    const dialog = screen.getByRole("dialog"),
      close = within(dialog).getByRole("button", { name: "Close about dialog" });
    expect(document.activeElement).toBe(close);
    await user.keyboard('/');
    expect(dialog.contains(document.activeElement)).toBe(true);
    await user.tab({ shift: true });
    expect(document.activeElement).toBe(
      within(dialog).getByRole("button", { name: "Start exploring" }),
    );
    await user.tab();
    expect(document.activeElement).toBe(close);
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });
  it("centers the current position when a dragged node is selected again", async () => {
    const user = userEvent.setup();
    render(<App papers={papers} relations={relations} />);
    const di = screen.getByRole("button", { name: "ReSTIR DI, 2020, Mainline" }),
      gi = screen.getByRole("button", { name: "ReSTIR GI, 2021, Branch" });
    const original = di.getAttribute("transform");
    const graph = screen.getByRole("group", { name: "ReSTIR research network" });
    await user.pointer([
      {
        target: di,
        keys: "[MouseLeft>]",
        coords: { clientX: 100, clientY: 100 },
      },
      { target: graph, coords: { clientX: 600, clientY: 300 } },
      { keys: "[/MouseLeft]" },
    ]);
    expect(di.getAttribute("transform")).not.toBe(original);
    gi.focus();
    await user.keyboard("{Enter}");
    di.focus();
    await user.keyboard("{Enter}");
    const nodePosition = di
      .getAttribute("transform")!
      .match(/translate\(([-\d.]+),([-\d.]+)\)/)!;
    const viewport = di
      .parentElement!.getAttribute("transform")!
      .match(/translate\(([-\d.]+),([-\d.]+)\) scale\(([-\d.]+)\)/)!;
    expect(
      Number(viewport[1]) + Number(nodePosition[1]) * Number(viewport[3]),
    ).toBeCloseTo(450);
    expect(
      Number(viewport[2]) + Number(nodePosition[2]) * Number(viewport[3]),
    ).toBeCloseTo(330);
  });
});
