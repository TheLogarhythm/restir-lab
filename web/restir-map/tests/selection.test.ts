import { describe, expect, it } from "vitest";
import {
  coalesceRelations,
  filterPapers,
  readSelection,
  shareHash,
  relatedIds,
  legendReadingSelection,
} from "../src/graph/selection";
import type { Paper, Relation } from "../src/data/types";
import { fitView, visibleLabelIds, zoomAt } from "../src/graph/layout";
import { detailsPanelWidth } from "../src/graph/panelWidth";

const paper = (id: string, title: string, tags: string[], year = 2024): Paper =>
  ({
    paper_id: id,
    title,
    short_title: id,
    authors: ["Ada Smith"],
    year,
    venue: "SIGGRAPH",
    tags,
    role: "branch",
    publication_status: "published",
  }) as Paper;
const papers = [
  paper("a", "Camera reuse", ["camera_dynamics"]),
  paper("b", "Indirect paths", ["transport"], 2021),
];
const relation = (
  id: string,
  type: "citation" | "inheritance",
  verification: "verified" | "pending" = "verified",
): Relation => ({
  id,
  predecessor: "a",
  successor: "b",
  type,
  verification,
  citing_paper: "b",
  cited_paper: "a",
  evidence: [],
});

describe("research exploration", () => {
  it("uses a stable matching fallback when a curated entry is absent from a reduced collection", () => {
    const collection = [
      paper("z", "Later", ["transport"], 2024),
      paper("b", "Earlier B", ["transport"], 2021),
      paper("a", "Earlier A", ["transport"], 2021),
      paper("outside", "Outside", ["foundations"], 2005),
    ];
    expect(legendReadingSelection(collection, "outside", { kind: "direction", value: "transport" })).toBe("a");
    expect(legendReadingSelection([...collection].reverse(), "outside", { kind: "direction", value: "transport" })).toBe("a");
    expect(collection.map(p => p.paper_id)).toEqual(["z", "b", "a", "outside"]);
  });
  it("keeps the reading selection when a facet has no papers or is toggled off", () => {
    expect(legendReadingSelection(papers, "a", { kind: "direction", value: "supporting" })).toBe("a");
    expect(legendReadingSelection(papers, "b", null)).toBe("b");
    expect(legendReadingSelection([], null, { kind: "role", value: "mainline" })).toBeNull();
  });
  it.each([
    [1440, 400, 400],
    [1599, 500, 500],
    [1600, 400, 400],
    [1920, 450, 450],
    [2560, 700, 700],
    [1001, 270, 270],
    [1200, 270, 270],
  ])(
    "sizes details at viewport %i from the measured %ipx collection",
    (viewport, sidebar, expected) => {
      expect(detailsPanelWidth(viewport, sidebar)).toBe(expected);
    },
  );
  it.each([375, 740, 800, 999, 1000])(
    "leaves the existing %ipx stacked layout unchanged",
    (viewport) => {
      expect(detailsPanelWidth(viewport, 800)).toBeNull();
    },
  );
  it("never enlarges a fitted mobile overview when zooming out", () => {
    const view = fitView(
      { a: { x: -200, y: 0 }, b: { x: 1400, y: 800 } },
      375,
      440,
    );
    const smaller = zoomAt(view, 1 / 1.2, { x: 187.5, y: 220 });
    expect(smaller.scale).toBeLessThan(view.scale);
    expect(
      zoomAt({ x: 0, y: 0, scale: 0.04 }, 0.5, { x: 0, y: 0 }).scale,
    ).toBeLessThanOrEqual(0.04);
  });
  it("keeps readable edge labels inside a narrow overview", () => {
    const points = { a: { x: -200, y: 0 }, b: { x: 1400, y: 800 } };
    const view = fitView(points, 375, 440);
    for (const point of Object.values(points)) {
      const x = view.x + point.x * view.scale;
      expect(x).toBeGreaterThanOrEqual(65);
      expect(x).toBeLessThanOrEqual(310);
    }
  });
  it("declutters an overview without hiding the actively explored label", () => {
    const points = { a: { x: 0, y: 0 }, b: { x: 10, y: 0 } };
    expect([...visibleLabelIds(papers, points, 0.2, "b")]).toEqual(["b"]);
    expect([...visibleLabelIds(papers, points, 0.2, "a")]).toEqual(["a"]);
    expect(visibleLabelIds(papers, points, 0.8, null).size).toBe(1);
    expect(
      visibleLabelIds(
        papers,
        { a: { x: 0, y: 0 }, b: { x: 400, y: 0 } },
        0.8,
        null,
      ).size,
    ).toBe(2);
  });
  it("combines text, direction, publication and year filters", () => {
    expect(
      filterPapers(papers, {
        query: "smith",
        tag: "transport",
        year: "2021",
        status: "published",
      }).map((p) => p.paper_id),
    ).toEqual(["b"]);
    expect(
      filterPapers(papers, {
        query: "camera",
        tag: "transport",
        year: "all",
        status: "all",
      }),
    ).toEqual([]);
  });
  it("merges citation and inheritance of a pair without losing their evidence", () => {
    const edges = coalesceRelations(
      [
        relation("cite", "citation"),
        relation("inherit", "inheritance"),
        relation("unverified", "citation", "pending"),
      ],
      "all",
    );
    expect(edges).toHaveLength(1);
    expect(edges[0].type).toBe("inheritance");
    expect(edges[0].relations.map((r) => r.id)).toEqual(["cite", "inherit"]);
    expect(
      coalesceRelations([relation("cite", "citation")], "inheritance"),
    ).toEqual([]);
  });
  it("keeps predecessor-to-successor direction and symmetric neighborhood highlighting", () => {
    const edges = coalesceRelations(
      [relation("inherit", "inheritance")],
      "all",
    );
    expect(edges[0].source).toBe("a");
    expect(edges[0].target).toBe("b");
    expect([...relatedIds("b", edges)]).toEqual(["b", "a"]);
  });
  it("round trips sharing and keeps a persistent fallback for missing or invalid selections", () => {
    expect(readSelection(shareHash("a"), papers)).toBe("a");
    expect(readSelection(shareHash("b"), papers)).toBe("b");
    expect(readSelection("", papers)).toBe("a");
    expect(readSelection("#paper=missing", papers)).toBe("a");
    expect(readSelection("#paper=%E0%A4%A", papers)).toBe("a");
    expect(shareHash(null)).toBe("");
  });
  it("prefers ReSTIR DI as the default regardless of collection order", () => {
    const collection = [
      ...papers,
      paper("restir_di2020", "Original ReSTIR", ["foundations"], 2020),
    ];
    expect(readSelection("", collection)).toBe("restir_di2020");
    expect(readSelection("#paper=unknown", collection)).toBe("restir_di2020");
    expect(readSelection("#paper=b", collection)).toBe("b");
    expect(readSelection("", [])).toBeNull();
  });
});
