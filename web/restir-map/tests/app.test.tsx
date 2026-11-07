import { describe, expect, it, beforeAll, vi } from "vitest";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "../src/App";
import type { Paper, Relation } from "../src/data/types";
import { papers as atlasPapers } from "../src/data/load";
import { directions, roleNames } from "../src/data/labels";
import { readingEntries } from "../src/data/readingEntries";

const resizeCallbacks = new Set<() => void>();
const notifyResize = () => resizeCallbacks.forEach((callback) => callback());
beforeAll(() => {
  globalThis.ResizeObserver = class {
    private callback: () => void;
    constructor(callback: ResizeObserverCallback) {
      this.callback = () => callback([], this);
    }
    observe(element: Element) {
      if (element.classList.contains("graph-canvas")) {
        Object.defineProperty(element, "clientWidth", {
          value: 900,
          configurable: true,
        });
        Object.defineProperty(element, "clientHeight", {
          value: 660,
          configurable: true,
        });
      }
      resizeCallbacks.add(this.callback);
      this.callback();
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
    tags: ["transport", "foundations"],
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
  const entryCases = [
    ["direction", "foundations", "Research area: Foundations", "restir_di2020"],
    ["direction", "reuse_quality", "Research area: Reuse quality", "production2021"],
    ["direction", "camera_dynamics", "Research area: Cameras & motion", "area2024"],
    ["direction", "transport", "Research area: Light transport", "restir_gi2021"],
    ["direction", "estimators", "Research area: Estimator extensions", "inverse2023"],
    ["direction", "supporting", "Research area: Learning & implementation", "course2023"],
    ["role", "mainline", "Classification: Mainline", "restir_di2020"],
    ["role", "branch", "Classification: Branch", "volume2021"],
    ["role", "optimization", "Classification: Optimization", "production2021"],
    ["role", "resource", "Classification: Resource", "course2023"],
  ] as const;
  it("covers every available legend facet with a valid editorial reading entry", () => {
    expect(Object.keys(readingEntries.direction).sort()).toEqual(Object.keys(directions).sort());
    expect(Object.keys(readingEntries.role).sort()).toEqual(Object.keys(roleNames).sort());
    expect(entryCases.filter(([kind]) => kind === "direction").map(([, value]) => value).sort()).toEqual(Object.keys(directions).sort());
    expect(entryCases.filter(([kind]) => kind === "role").map(([, value]) => value).sort()).toEqual(Object.keys(roleNames).sort());
    for (const [kind, entries] of Object.entries(readingEntries)) {
      for (const [value, id] of Object.entries(entries)) {
        const entry = atlasPapers.find(paper => paper.paper_id === id)!;
        expect(entry).toBeDefined();
        if (kind === "direction") expect(entry.tags).toContain(value);
        else expect(entry.role).toBe(value);
      }
    }
  });
  it.each(entryCases)("opens the curated entry for %s %s", async (_kind, value, label, id) => {
    const user = userEvent.setup();
    const start = ["foundations", "mainline"].includes(value) ? "area2024" : "restir_di2020";
    window.history.replaceState(null, "", `/restir-lab/#paper=${start}`);
    render(<App papers={atlasPapers} relations={[]} />);
    const graph = screen.getByRole("group", { name: "ReSTIR research network" });
    fireEvent.keyDown(graph, { key: "+" });
    fireEvent.keyDown(graph, { key: "ArrowLeft" });
    const view = graph.querySelector(".paper-node")!.parentElement!.getAttribute("transform");
    await user.click(screen.getByRole("button", { name: label }));
    expect(document.activeElement).toBe(screen.getByRole("button", { name: label }));
    expect(window.location.hash).toBe(`#paper=${id}`);
    const entry = atlasPapers.find(paper => paper.paper_id === id)!;
    expect(within(screen.getByRole("complementary", { name: "Paper details" })).getByRole("heading", { name: entry.short_title })).toBeTruthy();
    expect(graph.querySelectorAll(".paper-node")).toHaveLength(atlasPapers.length);
    expect(graph.querySelector(".paper-node")!.parentElement!.getAttribute("transform")).toBe(view);
    await user.click(screen.getByRole("button", { name: "Share selected paper" }));
    expect(await navigator.clipboard.readText()).toBe(`${window.location.origin}/restir-lab/#paper=${id}`);
  });
  it("resizes the desktop details from the measured collection and releases the override below desktop", async () => {
    const originalWidth = window.innerWidth;
    Object.defineProperty(window, "innerWidth", {
      value: 1920,
      configurable: true,
    });
    try {
      render(<App papers={papers} relations={relations} />);
      const sidebar = screen.getByRole("complementary", {
        name: "Paper collection",
      });
      const workspace = sidebar.parentElement!;
      sidebar.getBoundingClientRect = () => ({ width: 450 }) as DOMRect;
      act(() => notifyResize());
      expect(workspace.style.getPropertyValue("--paper-details-width")).toBe(
        "450px",
      );
      sidebar.getBoundingClientRect = () => ({ width: 500 }) as DOMRect;
      act(() => notifyResize());
      expect(workspace.style.getPropertyValue("--paper-details-width")).toBe(
        "500px",
      );
      Object.defineProperty(window, "innerWidth", {
        value: 1000,
        configurable: true,
      });
      fireEvent(window, new Event("resize"));
      expect(workspace.style.getPropertyValue("--paper-details-width")).toBe(
        "",
      );
    } finally {
      Object.defineProperty(window, "innerWidth", {
        value: originalWidth,
        configurable: true,
      });
    }
  });
  it.each(["inheritance", "citation"] as const)(
    "opens %s evidence from a focused edge without changing the paper selection",
    async (type) => {
      const user = userEvent.setup();
      render(<App papers={papers} relations={[{ ...relations[0], type }]} />);
      if (type === "citation")
        await user.click(
          screen.getByRole("button", { name: "All connections" }),
        );
      await user.click(
        screen.getByRole("button", { name: "ReSTIR DI, 2020, Mainline" }),
      );
      const edge = screen.getByRole("button", {
        name: /ReSTIR DI → ReSTIR GI.*evidence/i,
      });
      const hit = edge.querySelector(".edge-hit")!;
      expect(hit.getAttribute("vector-effect")).toBe("non-scaling-stroke");
      await user.hover(hit);
      expect(window.location.hash).toBe("#paper=di");
      expect(screen.queryByRole("dialog")).toBeNull();
      await user.click(hit);
      expect(screen.getByRole("dialog").textContent).toContain(
        evidence.explanation,
      );
      await user.keyboard("{Escape}");
      act(() => edge.focus());
      for (const key of ["{Enter}", " "]) {
        await user.keyboard(key);
        expect(screen.getByRole("dialog").textContent).toContain(
          evidence.explanation,
        );
        expect(window.location.hash).toBe("#paper=di");
        await user.keyboard("{Escape}");
        expect(document.activeElement).toBe(edge);
      }
    },
  );
  it.each(["", "#paper=missing", "#paper=%E0%A4%A"])(
    "opens a persistent default paper for hash %s",
    (hash) => {
      window.history.replaceState(null, "", `/restir-lab/${hash}`);
      render(<App papers={papers} relations={relations} />);
      expect(
        screen
          .getByRole("button", { name: "ReSTIR DI, 2020, Mainline" })
          .getAttribute("aria-pressed"),
      ).toBe("true");
      expect(
        within(
          screen.getByRole("complementary", { name: "Paper details" }),
        ).getByRole("heading", { name: "ReSTIR DI" }),
      ).toBeTruthy();
      expect(
        screen.queryByRole("button", {
          name: /Clear selection|Close paper details/i,
        }),
      ).toBeNull();
    },
  );
  it("links list, network, persistent details and share state, including keyboard selection", async () => {
    const user = userEvent.setup();
    render(<App papers={papers} relations={relations} />);
    await user.click(
      within(
        screen.getByRole("complementary", { name: "Paper collection" }),
      ).getByRole("button", { name: /ReSTIR DI/ }),
    );
    expect(window.location.hash).toBe("#paper=di");
    expect(
      screen
        .getByRole("button", { name: "ReSTIR DI, 2020, Mainline" })
        .getAttribute("aria-pressed"),
    ).toBe("true");
    expect(
      within(
        screen.getByRole("complementary", { name: "Paper details" }),
      ).getByRole("heading", { name: "ReSTIR DI" }),
    ).toBeTruthy();
    const gi = screen.getByRole("button", {
      name: "ReSTIR GI, 2021, Branch",
    });
    gi.focus();
    await user.keyboard("{Enter}");
    expect(window.location.hash).toBe("#paper=gi");
    expect(document.activeElement).toBe(gi);
    expect(
      within(screen.getByRole("complementary", { name: "Paper collection" }))
        .getByRole("button", { name: /ReSTIR GI/ })
        .getAttribute("aria-pressed"),
    ).toBe("true");
    await user.click(
      screen.getByRole("button", { name: "Share selected paper" }),
    );
    expect(await navigator.clipboard.readText()).toContain(
      "/restir-lab/#paper=gi",
    );
    await user.keyboard("{Escape}");
    expect(
      screen.getByRole("complementary", { name: "Paper details" }).textContent,
    ).toContain("ReSTIR GI");
    expect(window.location.hash).toBe("#paper=gi");
    expect(gi.getAttribute("aria-pressed")).toBe("true");
  });
  it("restores a shared selection and filters both views without losing the reading panel", async () => {
    window.history.replaceState(null, "", "/restir-lab/#paper=gi");
    const user = userEvent.setup();
    render(<App papers={papers} relations={relations} />);
    expect(
      screen.getByRole("complementary", { name: "Paper details" }).textContent,
    ).toContain("ReSTIR GI");
    const di = screen.getByRole("button", {
      name: "ReSTIR DI, 2020, Mainline",
    });
    const view = di.parentElement!.getAttribute("transform");
    const brand = screen.getByRole("link", { name: "ReSTIR Atlas home" });
    expect(brand.textContent).toContain("2 papers");
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
    expect(brand.textContent).toContain("2 papers");
    expect(di.parentElement!.getAttribute("transform")).toBe(view);
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
  it("makes the address-bar fallback share the selected paper when clipboard access fails", async () => {
    const user = userEvent.setup();
    window.history.replaceState(null, "", "/restir-lab/?source=reading#paper=missing");
    const historyLength = window.history.length;
    const clipboard = vi.spyOn(navigator.clipboard, "writeText").mockRejectedValue(new Error("Clipboard unavailable"));
    try {
      render(<App papers={papers} relations={relations} />);
      await user.click(screen.getByRole("button", { name: "Share selected paper" }));
      expect(screen.getByRole("status").textContent).toContain("Copy the URL in your address bar");
      expect(window.location.pathname).toBe("/restir-lab/");
      expect(window.location.search).toBe("?source=reading");
      expect(window.location.hash).toBe("#paper=di");
      expect(window.history.length).toBe(historyLength);
    } finally {
      clipboard.mockRestore();
    }
  });
  it("keeps a newer paper URL when an earlier clipboard request rejects", async () => {
    const user = userEvent.setup();
    window.history.replaceState(null, "", "/restir-lab/#paper=di");
    let rejectClipboard!: (reason: Error) => void;
    const clipboard = vi.spyOn(navigator.clipboard, "writeText").mockImplementation(() =>
      new Promise<void>((_resolve, reject) => { rejectClipboard = reject; }),
    );
    try {
      render(<App papers={papers} relations={relations} />);
      await user.click(screen.getByRole("button", { name: "Share selected paper" }));
      await user.click(screen.getByRole("button", { name: "ReSTIR GI, 2021, Branch" }));
      await act(async () => rejectClipboard(new Error("Clipboard unavailable")));
      expect(window.location.hash).toBe("#paper=gi");
      expect(within(screen.getByRole("complementary", { name: "Paper details" }))
        .getByRole("heading", { name: "ReSTIR GI" })).toBeTruthy();
      expect(screen.getByRole("status").textContent).toContain("Copy the URL in your address bar");
    } finally {
      clipboard.mockRestore();
    }
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
  it.each(["related work", "connection dialog", "connection dialog for the current paper"])(
    "continues keyboard reading at the new details heading from %s without scrolling",
    async (source) => {
      const user = userEvent.setup();
      if (source === "connection dialog for the current paper")
        window.history.replaceState(null, "", "/restir-lab/#paper=gi");
      render(<App papers={papers} relations={relations} />);
      const graph = screen.getByRole("group", { name: "ReSTIR research network" });
      fireEvent.keyDown(graph, { key: "ArrowRight" });
      const view = graph.querySelector(".paper-node")!.parentElement!.getAttribute("transform");
      let trigger: HTMLElement;
      if (source === "related work") {
        await user.click(screen.getByRole("button", { name: "Connections" }));
        const detail = screen.getByRole("complementary", { name: "Paper details" });
        await user.click(within(detail).getByText("Later work"));
        trigger = within(detail).getByRole("button", { name: /Read ReSTIR GI/ });
      } else {
        await user.click(screen.getByRole("button", { name: /ReSTIR DI → ReSTIR GI.*evidence/i }));
        trigger = screen.getByRole("button", { name: "Read later paper" });
      }
      trigger.focus();
      const focus = vi.spyOn(HTMLElement.prototype, "focus");
      try {
        await user.keyboard("{Enter}");
        const heading = within(screen.getByRole("complementary", { name: "Paper details" }))
          .getByRole("heading", { name: "ReSTIR GI" });
        expect(document.activeElement).toBe(heading);
        expect(focus).toHaveBeenLastCalledWith({ preventScroll: true });
        expect(window.location.hash).toBe("#paper=gi");
        expect(screen.queryByRole("dialog")).toBeNull();
        expect(graph.querySelector(".paper-node")!.parentElement!.getAttribute("transform")).toBe(view);
      } finally {
        focus.mockRestore();
      }
    },
  );
  it("traps dialog focus and restores it to its trigger on Escape", async () => {
    const user = userEvent.setup();
    render(<App papers={papers} relations={relations} />);
    const trigger = screen.getByRole("button", { name: /About this map/ });
    await user.click(trigger);
    const dialog = screen.getByRole("dialog"),
      close = within(dialog).getByRole("button", {
        name: "Close about dialog",
      });
    expect(document.activeElement).toBe(close);
    await user.keyboard("/");
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
  it("keeps the camera and dragged positions stable when selecting through graph, list or related work", async () => {
    const user = userEvent.setup();
    render(<App papers={papers} relations={relations} />);
    const di = screen.getByRole("button", {
      name: "ReSTIR DI, 2020, Mainline",
    });
    const gi = screen.getByRole("button", { name: "ReSTIR GI, 2021, Branch" });
    const graph = screen.getByRole("group", {
      name: "ReSTIR research network",
    });
    const original = di.getAttribute("transform");
    await user.pointer([
      {
        target: di,
        keys: "[MouseLeft>]",
        coords: { clientX: 100, clientY: 100 },
      },
      { target: graph, coords: { clientX: 600, clientY: 300 } },
      { keys: "[/MouseLeft]" },
    ]);
    const dragged = di.getAttribute("transform");
    expect(dragged).not.toBe(original);
    fireEvent.wheel(graph, { deltaY: -120, clientX: 450, clientY: 330 });
    const view = di.parentElement!.getAttribute("transform");
    gi.focus();
    await user.keyboard("{Enter}");
    expect(di.parentElement!.getAttribute("transform")).toBe(view);
    expect(di.getAttribute("transform")).toBe(dragged);
    await user.click(
      within(
        screen.getByRole("complementary", { name: "Paper collection" }),
      ).getByRole("button", { name: /ReSTIR DI/ }),
    );
    expect(di.parentElement!.getAttribute("transform")).toBe(view);
    await user.click(screen.getByRole("button", { name: "Connections" }));
    const detail = screen.getByRole("complementary", { name: "Paper details" });
    await user.click(within(detail).getByText("Later work"));
    await user.click(
      within(detail).getByRole("button", { name: /Read ReSTIR GI/ }),
    );
    expect(window.location.hash).toBe("#paper=gi");
    expect(di.parentElement!.getAttribute("transform")).toBe(view);
    expect(di.getAttribute("transform")).toBe(dragged);
  });
  it("opens a matching reading entry from the legend without hiding nodes or moving the camera", async () => {
    const user = userEvent.setup();
    const collection: Paper[] = [
      ...papers,
      {
        ...papers[1],
        paper_id: "mcmc",
        short_title: "MCMC",
        tags: ["reuse_quality"],
        role: "optimization",
      },
    ];
    render(<App papers={collection} relations={relations} />);
    const mcmc = screen.getByRole("button", {
      name: "MCMC, 2021, Optimization",
    });
    await user.click(mcmc);
    const di = screen.getByRole("button", {
      name: "ReSTIR DI, 2020, Mainline",
    });
    const gi = screen.getByRole("button", { name: "ReSTIR GI, 2021, Branch" });
    fireEvent.wheel(mcmc.closest("svg")!, { deltaY: -120, clientX: 450, clientY: 330 });
    const view = mcmc.parentElement!.getAttribute("transform");
    const coordinates = [di, gi, mcmc].map((node) =>
      node.getAttribute("transform"),
    );
    const foundations = screen.getByRole("button", {
      name: "Research area: Foundations",
    });
    await user.click(foundations);
    expect(foundations.getAttribute("aria-pressed")).toBe("true");
    expect(di.classList.contains("highlighted")).toBe(true);
    expect(gi.classList.contains("highlighted")).toBe(true);
    expect(mcmc.classList.contains("dimmed")).toBe(true);
    expect(
      screen.getByRole("complementary", { name: "Paper details" }).textContent,
    ).toContain("ReSTIR DI");
    expect(window.location.hash).toBe("#paper=di");
    expect(
      screen
        .getByRole("group", { name: "ReSTIR research network" })
        .querySelectorAll(".paper-node"),
    ).toHaveLength(3);
    expect(
      [di, gi, mcmc].map((node) => node.getAttribute("transform")),
    ).toEqual(coordinates);
    expect(mcmc.parentElement!.getAttribute("transform")).toBe(view);
    const branches = screen.getByRole("button", {
      name: "Classification: Branch",
    });
    await user.click(branches);
    expect(foundations.getAttribute("aria-pressed")).toBe("false");
    expect(branches.getAttribute("aria-pressed")).toBe("true");
    expect(di.classList.contains("dimmed")).toBe(true);
    expect(gi.classList.contains("highlighted")).toBe(true);
    expect(gi.getAttribute("aria-pressed")).toBe("true");
    expect(window.location.hash).toBe("#paper=gi");
    await user.click(branches);
    expect(branches.getAttribute("aria-pressed")).toBe("false");
    expect(gi.getAttribute("aria-pressed")).toBe("true");
    expect(window.location.hash).toBe("#paper=gi");
    expect(mcmc.parentElement!.getAttribute("transform")).toBe(view);
  });
  it("retains a matching paper across legend activation, including a secondary tag", async () => {
    const user = userEvent.setup();
    window.history.replaceState(null, "", "/restir-lab/#paper=gi");
    render(<App papers={papers} relations={relations} />);
    const foundations = screen.getByRole("button", { name: "Research area: Foundations" });
    foundations.focus();
    await user.keyboard("{Enter}");
    expect(foundations.getAttribute("aria-pressed")).toBe("true");
    expect(window.location.hash).toBe("#paper=gi");
    expect(screen.getByRole("button", { name: "ReSTIR GI, 2021, Branch" }).getAttribute("aria-pressed")).toBe("true");
    await user.click(screen.getByRole("button", { name: "ReSTIR DI, 2020, Mainline" }));
    expect(foundations.getAttribute("aria-pressed")).toBe("true");
    expect(window.location.hash).toBe("#paper=di");
    foundations.focus();
    await user.keyboard(" ");
    expect(foundations.getAttribute("aria-pressed")).toBe("false");
    expect(window.location.hash).toBe("#paper=di");
  });
  it.each(["graph", "list", "related paper"])("clears the active legend when selecting an outside paper through %s", async (source) => {
    const user = userEvent.setup();
    render(<App papers={papers} relations={relations} />);
    const transport = screen.getByRole("button", { name: "Research area: Light transport" });
    await user.click(transport);
    expect(window.location.hash).toBe("#paper=gi");
    const graph = screen.getByRole("group", { name: "ReSTIR research network" });
    fireEvent.keyDown(graph, { key: "ArrowRight" });
    const view = graph.querySelector(".paper-node")!.parentElement!.getAttribute("transform");
    if (source === "graph") {
      await user.click(screen.getByRole("button", { name: "ReSTIR DI, 2020, Mainline" }));
    } else if (source === "list") {
      await user.click(within(screen.getByRole("complementary", { name: "Paper collection" })).getByRole("button", { name: /ReSTIR DI/ }));
    } else {
      await user.click(screen.getByRole("button", { name: "Connections" }));
      const detail = screen.getByRole("complementary", { name: "Paper details" });
      await user.click(within(detail).getByText("Earlier work"));
      await user.click(within(detail).getByRole("button", { name: /Read ReSTIR DI/ }));
    }
    expect(window.location.hash).toBe("#paper=di");
    expect(transport.getAttribute("aria-pressed")).toBe("false");
    expect(graph.querySelector(".paper-node")!.parentElement!.getAttribute("transform")).toBe(view);
  });
  it("keeps search filters when the legend opens an entry outside the filtered results", async () => {
    const user = userEvent.setup();
    render(<App papers={papers} relations={relations} />);
    await user.selectOptions(screen.getByRole("combobox", { name: "Research area" }), "foundations");
    await user.type(screen.getByRole("searchbox", { name: "Search papers" }), "direct lighting");
    const graph = screen.getByRole("group", { name: "ReSTIR research network" });
    const view = graph.querySelector(".paper-node")!.parentElement!.getAttribute("transform");
    await user.click(screen.getByRole("button", { name: "Research area: Light transport" }));
    expect(window.location.hash).toBe("#paper=gi");
    expect((screen.getByRole("searchbox", { name: "Search papers" }) as HTMLInputElement).value).toBe("direct lighting");
    expect((screen.getByRole("combobox", { name: "Research area" }) as HTMLSelectElement).value).toBe("foundations");
    expect(graph.querySelectorAll(".paper-node")).toHaveLength(1);
    expect(graph.querySelector(".paper-node")!.parentElement!.getAttribute("transform")).toBe(view);
    expect(screen.getByText("The selected paper is hidden by your filters.")).toBeTruthy();
  });
  it("reconciles the legend when browser history restores an outside paper", async () => {
    const user = userEvent.setup();
    render(<App papers={papers} relations={relations} />);
    const transport = screen.getByRole("button", { name: "Research area: Light transport" });
    await user.click(transport);
    window.history.replaceState(null, "", "/restir-lab/#paper=di");
    fireEvent.popState(window);
    expect(transport.getAttribute("aria-pressed")).toBe("false");
    expect(screen.getByRole("button", { name: "ReSTIR DI, 2020, Mainline" }).getAttribute("aria-pressed")).toBe("true");
  });
  it("centers the visible network on explicit request without undoing dragged positions", async () => {
    const user = userEvent.setup();
    render(<App papers={papers} relations={relations} />);
    const di = screen.getByRole("button", {
      name: "ReSTIR DI, 2020, Mainline",
    });
    const graph = screen.getByRole("group", {
      name: "ReSTIR research network",
    });
    await user.pointer([
      {
        target: di,
        keys: "[MouseLeft>]",
        coords: { clientX: 100, clientY: 100 },
      },
      { target: graph, coords: { clientX: 600, clientY: 300 } },
      { keys: "[/MouseLeft]" },
    ]);
    const dragged = di.getAttribute("transform");
    await user.pointer([
      {
        target: graph,
        keys: "[MouseLeft>]",
        coords: { clientX: 100, clientY: 100 },
      },
      { target: graph, coords: { clientX: 800, clientY: 600 } },
      { keys: "[/MouseLeft]" },
    ]);
    const panned = di.parentElement!.getAttribute("transform");
    await user.click(screen.getByRole("button", { name: "Center" }));
    expect(di.getAttribute("transform")).toBe(dragged);
    expect(di.parentElement!.getAttribute("transform")).not.toBe(panned);
    const view = di
      .parentElement!.getAttribute("transform")!
      .match(/translate\(([-\d.]+),([-\d.]+)\) scale\(([-\d.]+)\)/)!;
    for (const node of graph.querySelectorAll(".paper-node")) {
      const position = node
        .getAttribute("transform")!
        .match(/translate\(([-\d.]+),([-\d.]+)\)/)!;
      const x = Number(view[1]) + Number(position[1]) * Number(view[3]);
      const y = Number(view[2]) + Number(position[2]) * Number(view[3]);
      expect(x).toBeGreaterThan(0);
      expect(x).toBeLessThan(900);
      expect(y).toBeGreaterThan(0);
      expect(y).toBeLessThan(660);
    }
  });
});
