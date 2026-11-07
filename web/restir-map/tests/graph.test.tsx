import { beforeAll, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { StrictMode } from "react";
import { PaperGraph } from "../src/components/PaperGraph";
import type { GraphEdge, Paper } from "../src/data/types";
import { edgePath, visibleLabelIds } from "../src/graph/layout";
import { papers as atlasPapers } from "../src/data/load";

const resizeCallbacks = new Set<() => void>();
beforeAll(() => {
  globalThis.ResizeObserver = class {
    private callback: () => void;
    constructor(callback: ResizeObserverCallback) { this.callback = () => callback([], this); }
    observe(element: Element) {
      Object.defineProperties(element, { clientWidth: { value: 900, configurable: true }, clientHeight: { value: 660, configurable: true } });
      resizeCallbacks.add(this.callback);
      this.callback();
    }
    unobserve() { resizeCallbacks.delete(this.callback); }
    disconnect() { resizeCallbacks.delete(this.callback); }
  };
});

const papers: Paper[] = Array.from({ length: 9 }, (_, index) => ({
  paper_id: `paper-${index}`, short_title: `Paper ${index}`, title: `Paper ${index}`,
  authors: ["Author"], year: 2020 + index, venue: "TOG", publication_status: "published",
  doi: null, tags: ["foundations"], role: "branch", problem: "A sampling problem",
  contributions: [], changes: "", limitations: [], links: { paper: "https://example.org/paper", pdf: null, code: null },
  sources: [], verification: { metadata: "verified", content: "full_text", notes: "" },
  pdf: { status: "missing", local_file: null, sha256: null, version: "", source_url: null },
}));
const defaults = {
  papers, allPapers: papers, edges: [], selected: null, hovered: null,
  onSelect: vi.fn(), onHover: vi.fn(), onEdge: vi.fn(),
  connectionCounts: { "paper-0": 0, "paper-1": 4, "paper-2": 10 }, highlightedIds: null,
};
const graph = () => screen.getByRole("group", { name: "ReSTIR research network" });
const viewport = () => graph().querySelector("g")!;
const viewTransform = () => viewport().getAttribute("transform");
const viewValues = () => {
  const match = viewTransform()!.match(/translate\(([-\d.]+),([-\d.]+)\) scale\(([-\d.]+)\)/)!;
  return { x: Number(match[1]), y: Number(match[2]), scale: Number(match[3]) };
};
function pointer(target: Element | Window, type: string, pointerId: number, clientX: number, clientY: number, pointerType = "mouse", buttons = type === "pointerup" || type === "pointercancel" ? 0 : 1) {
  const event = new Event(type, { bubbles: true });
  Object.assign(event, { pointerId, clientX, clientY, pointerType, button: 0, buttons });
  fireEvent(target, event);
}
function touch(type: string, pointerId: number, clientX: number, clientY: number) {
  pointer(graph(), type, pointerId, clientX, clientY, "touch");
}

describe("manual graph navigation", () => {
  it("keeps transparent mobile hit areas clear of other paper centers in the real layout", () => {
    render(<PaperGraph {...defaults} papers={atlasPapers} allPapers={atlasPapers} />);
    Object.defineProperties(graph().parentElement, { clientWidth: { value: 375, configurable: true }, clientHeight: { value: 440, configurable: true } });
    act(() => resizeCallbacks.forEach(callback => callback()));
    fireEvent.click(screen.getByRole("button", { name: "Center" }));
    const nodes = [...graph().querySelectorAll(".paper-node")].map(node => {
      const point = node.getAttribute("transform")!.match(/translate\(([-\d.]+),([-\d.]+)\)/)!;
      return { node, x: Number(point[1]), y: Number(point[2]), radius: Number(node.querySelector(".node-hit")!.getAttribute("r")) };
    });
    for (const current of nodes) {
      for (const other of nodes.filter(node => node !== current)) {
        expect(current.radius).toBeLessThan(Math.hypot(current.x - other.x, current.y - other.y));
      }
    }
    for (const { node } of nodes) expect(node.querySelector(".node-halo")!.getAttribute("pointer-events")).toBe("none");
  });
  it("declutters labels at intermediate zoom and offsets edge ends for the enlarged nodes", () => {
    expect(visibleLabelIds(papers.slice(0, 2), { "paper-0": { x: 0, y: 0 }, "paper-1": { x: 10, y: 0 } }, 0.6, "paper-1", defaults.connectionCounts).size).toBe(1);
    expect(edgePath({ x: 0, y: 0 }, { x: 100, y: 0 }, 18, 26, 0.5)).toMatch(/^M 22 0 Q .* 66 0$/);
  });
  it("fits the complete collection on entry even when a paper is already selected", () => {
    const first = render(<PaperGraph {...defaults} />);
    const fullView = viewTransform();
    first.unmount();
    render(<PaperGraph {...defaults} papers={[papers[0]]} selected={papers[0].paper_id} />);
    expect(viewTransform()).toBe(fullView);
    expect(viewValues().scale).toBeLessThan(1);
  });

  it("preserves a manual view across selection, filters, edge modes, legend focus, and resizing", () => {
    const { rerender } = render(<PaperGraph {...defaults} />);
    fireEvent.wheel(graph(), { deltaY: -200, clientX: 180, clientY: 160 });
    fireEvent.keyDown(graph(), { key: "ArrowRight" });
    const manual = viewTransform();
    rerender(<PaperGraph {...defaults} selected="paper-1" />);
    expect(viewTransform()).toBe(manual);
    rerender(<PaperGraph {...defaults} papers={[papers[0]]} allPapers={[...papers]} selected="paper-1" highlightedIds={new Set(["paper-0"])} />);
    expect(viewTransform()).toBe(manual);
    Object.defineProperty(graph().parentElement, "clientWidth", { value: 600, configurable: true });
    act(() => resizeCallbacks.forEach(callback => callback()));
    expect(viewTransform()).toBe(manual);
  });

  it("centers visible papers without restoring their dragged coordinates", async () => {
    const user = userEvent.setup();
    const { rerender } = render(<PaperGraph {...defaults} />);
    const node = screen.getByRole("button", { name: "Paper 0, 2020, Branch" });
    const original = node.getAttribute("transform");
    await user.pointer([
      { target: node, keys: "[MouseLeft>]", coords: { clientX: 100, clientY: 100 } },
      { target: graph(), coords: { clientX: 350, clientY: 200 } },
      { keys: "[/MouseLeft]" },
    ]);
    const dragged = node.getAttribute("transform");
    expect(dragged).not.toBe(original);
    rerender(<PaperGraph {...defaults} papers={[papers[0]]} />);
    fireEvent.keyDown(graph(), { key: "ArrowLeft" });
    const before = viewTransform();
    await user.click(screen.getByRole("button", { name: "Center" }));
    expect(viewTransform()).not.toBe(before);
    expect(node.getAttribute("transform")).toBe(dragged);
    const coordinate = dragged!.match(/translate\(([-\d.]+),([-\d.]+)\)/)!;
    const centered = viewValues();
    expect(centered.x + Number(coordinate[1]) * centered.scale).toBeCloseTo(450);
    expect(centered.y + Number(coordinate[2]) * centered.scale).toBeGreaterThan(280);
    expect(centered.y + Number(coordinate[2]) * centered.scale).toBeLessThan(350);
  });

  it("adds paper coordinates before rendering while preserving dragged positions and the view", () => {
    const { rerender } = render(<PaperGraph {...defaults} papers={[papers[0]]} allPapers={[papers[0]]} />);
    const node = screen.getByRole("button", { name: "Paper 0, 2020, Branch" });
    pointer(node, "pointerdown", 1, 100, 100);
    pointer(graph(), "pointermove", 1, 160, 130);
    pointer(graph(), "pointerup", 1, 160, 130);
    fireEvent.keyDown(graph(), { key: "ArrowLeft" });
    const dragged = node.getAttribute("transform"), manualView = viewTransform();

    expect(() => rerender(<PaperGraph {...defaults} papers={papers.slice(0, 2)} allPapers={papers.slice(0, 2)} />)).not.toThrow();
    expect(screen.getByRole("button", { name: "Paper 1, 2021, Branch" }).getAttribute("transform")).toBe("translate(320,130)");
    expect(node.getAttribute("transform")).toBe(dragged);
    expect(viewTransform()).toBe(manualView);
  });

  it("ends a gesture released outside the graph before it captures the pointer", () => {
    render(<PaperGraph {...defaults} />);
    const before = viewTransform();
    pointer(graph(), "pointerdown", 1, 1, 100);
    pointer(document.body, "pointerup", 1, -10, 100);
    pointer(graph(), "pointermove", 1, 100, 100, "mouse", 0);
    expect(viewTransform()).toBe(before);

    pointer(graph(), "pointerdown", 1, 100, 100);
    pointer(graph(), "pointermove", 1, 145, 100);
    expect(viewTransform()).not.toBe(before);
  });

  it("discards a mouse drag when the browser no longer reports a pressed button", () => {
    render(<PaperGraph {...defaults} />);
    pointer(graph(), "pointerdown", 1, 100, 100);
    pointer(graph(), "pointermove", 1, 145, 100);
    const dragged = viewTransform();
    pointer(graph(), "pointermove", 1, 200, 100, "mouse", 0);
    expect(viewTransform()).toBe(dragged);
  });

  it.each(["lostpointercapture", "pointercancel"])("ends a paper drag on %s without moving or selecting it afterward", (endEvent) => {
    const onSelect = vi.fn();
    render(<PaperGraph {...defaults} onSelect={onSelect} />);
    const node = screen.getByRole("button", { name: "Paper 0, 2020, Branch" });
    pointer(node, "pointerdown", 1, 100, 100);
    pointer(graph(), "pointermove", 1, 160, 100);
    const dragged = node.getAttribute("transform");
    pointer(graph(), endEvent, 1, 160, 100);
    pointer(graph(), "pointermove", 1, 220, 100);
    fireEvent.click(node);
    expect(node.getAttribute("transform")).toBe(dragged);
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("cancels both sides of a pinch when one pointer is canceled", () => {
    render(<PaperGraph {...defaults} />);
    touch("pointerdown", 1, 100, 100);
    touch("pointerdown", 2, 200, 100);
    touch("pointermove", 2, 250, 100);
    const pinched = viewTransform();
    touch("pointercancel", 1, 100, 100);
    touch("pointermove", 2, 300, 100);
    expect(viewTransform()).toBe(pinched);
    touch("pointerup", 2, 300, 100);
    touch("pointerdown", 3, 100, 100);
    touch("pointermove", 3, 145, 100);
    expect(viewTransform()).not.toBe(pinched);
  });

  it("keeps pinching when implicit touch capture transfers from a paper to the SVG", () => {
    render(<PaperGraph {...defaults} />);
    const initial = viewValues();
    const node = screen.getByRole("button", { name: "Paper 0, 2020, Branch" });
    pointer(node, "pointerdown", 1, 100, 100, "touch");
    touch("pointerdown", 2, 200, 100);
    pointer(node, "lostpointercapture", 1, 100, 100, "touch");
    touch("pointermove", 2, 300, 100);
    expect(viewValues().scale).toBeCloseTo(initial.scale * 2);
  });

  it("ends the whole pinch when the SVG itself loses pointer capture", () => {
    render(<PaperGraph {...defaults} />);
    touch("pointerdown", 1, 100, 100);
    touch("pointerdown", 2, 200, 100);
    touch("pointermove", 2, 250, 100);
    const pinched = viewTransform();
    touch("lostpointercapture", 1, 100, 100);
    touch("pointermove", 2, 300, 100);
    expect(viewTransform()).toBe(pinched);
  });

  it("clears an interrupted gesture when the window loses focus", () => {
    render(<PaperGraph {...defaults} />);
    pointer(graph(), "pointerdown", 1, 100, 100);
    pointer(graph(), "pointermove", 1, 145, 100);
    const dragged = viewTransform();
    fireEvent.blur(window);
    pointer(graph(), "pointermove", 1, 200, 100);
    expect(viewTransform()).toBe(dragged);
  });

  it.each(["mouse", "touch"])("keeps ordinary %s taps on papers and edges clickable", (pointerType) => {
    const onSelect = vi.fn(), onEdge = vi.fn();
    const edge: GraphEdge = { id: "paper-0--paper-1", source: "paper-0", target: "paper-1", type: "inheritance", relations: [] };
    render(<PaperGraph {...defaults} edges={[edge]} onSelect={onSelect} onEdge={onEdge} />);
    const node = screen.getByRole("button", { name: "Paper 0, 2020, Branch" });
    const edgeHit = graph().querySelector(".edge-hit")!;
    for (const target of [node, edgeHit]) {
      pointer(target, "pointerdown", 1, 100, 100, pointerType);
      pointer(target, "pointerup", 1, 100, 100, pointerType);
      fireEvent.click(target);
    }
    expect(onSelect).toHaveBeenCalledExactlyOnceWith("paper-0");
    expect(onEdge).toHaveBeenCalledExactlyOnceWith(edge);
  });

  it("keeps keyboard selection available after StrictMode replays effect cleanup", () => {
    const onSelect = vi.fn();
    render(<StrictMode><PaperGraph {...defaults} onSelect={onSelect} /></StrictMode>);
    fireEvent.keyDown(screen.getByRole("button", { name: "Paper 0, 2020, Branch" }), { key: "Enter" });
    expect(onSelect).toHaveBeenCalledExactlyOnceWith("paper-0");
  });

  it("pinches around the moving two-pointer midpoint without moving paper coordinates", () => {
    render(<PaperGraph {...defaults} />);
    const initial = viewValues();
    const node = screen.getByRole("button", { name: "Paper 0, 2020, Branch" });
    const position = node.getAttribute("transform");
    touch("pointerdown", 1, 100, 100);
    touch("pointerdown", 2, 200, 100);
    touch("pointermove", 2, 300, 100);
    const pinched = viewValues();
    expect(pinched.scale).toBeCloseTo(initial.scale * 2);
    expect(pinched.x + ((150 - initial.x) / initial.scale) * pinched.scale).toBeCloseTo(200);
    expect(pinched.y + ((100 - initial.y) / initial.scale) * pinched.scale).toBeCloseTo(100);
    expect(node.getAttribute("transform")).toBe(position);
    touch("pointerup", 1, 100, 100);
    touch("pointerup", 2, 300, 100);
  });

  it("applies legend emphasis without hiding the selected ring or changing size tiers", () => {
    const { rerender } = render(<PaperGraph {...defaults} selected="paper-0" highlightedIds={new Set(["paper-1"])} />);
    const small = screen.getByRole("button", { name: "Paper 0, 2020, Branch" });
    const medium = screen.getByRole("button", { name: "Paper 1, 2021, Branch" });
    const large = screen.getByRole("button", { name: "Paper 2, 2022, Branch" });
    expect(small.classList.contains("selected")).toBe(true);
    expect(small.querySelector(".node-selection-ring")).not.toBeNull();
    const instructions = document.getElementById(graph().getAttribute("aria-describedby") ?? "");
    expect(instructions?.textContent).toMatch(/pinch/i);
    expect(instructions?.textContent).toMatch(/Enter/);
    expect(small.classList.contains("dimmed")).toBe(true);
    expect(medium.classList.contains("highlighted")).toBe(true);
    expect([small, medium, large].map(node => node.querySelector(".node-shape")!.getAttribute("r"))).toEqual(["18", "22", "26"]);
    rerender(<PaperGraph {...defaults} papers={[papers[2]]} edges={[]} />);
    expect(large.querySelector(".node-shape")!.getAttribute("r")).toBe("26");
  });
});
