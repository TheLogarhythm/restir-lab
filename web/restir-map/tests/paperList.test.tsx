import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { PaperList } from "../src/components/PaperList";
import { papers } from "../src/data/load";

describe("selected list row visibility", () => {
  it("reveals a selected paper when filters restore its row without changing the selection", () => {
    const selected = papers.find(paper => paper.paper_id === "cgns2026")!;
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) {
      if (this.classList.contains("paper-list")) return { top: 100, bottom: 300, left: 0, right: 300 } as DOMRect;
      return { top: 400, bottom: 500, left: 0, right: 300 } as DOMRect;
    });
    const props = {
      allPapers: papers, selected: selected.paper_id, hovered: null, highlightedIds: null,
      filters: { query: "", tag: "all", year: "all", status: "all" },
      onSelect: vi.fn(), onHover: vi.fn(), onFilters: vi.fn(),
    };
    const { rerender } = render(<PaperList {...props} papers={[]} />);
    const list = screen.getByRole("list");
    expect(list.scrollTop).toBe(0);
    rerender(<PaperList {...props} papers={[selected]} />);
    expect(list.scrollTop).toBe(200);
    expect(document.documentElement.scrollTop).toBe(0);
  });
});
