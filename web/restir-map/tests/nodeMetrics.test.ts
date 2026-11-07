import { describe, expect, it } from "vitest";
import type { Paper, Relation } from "../src/data/types";
import { methodConnectionCounts, nodeLabelOffset, nodeOuterRadius, nodeRadius } from "../src/graph/nodeMetrics";

const papers = ["a", "b", "c", "isolated"].map((paper_id) => ({ paper_id }) as Paper);
const relation = (
  predecessor: string,
  successor: string,
  type: Relation["type"] = "inheritance",
  verification: Relation["verification"] = "verified",
): Relation => ({
  id: `${predecessor}-${successor}-${type}-${verification}`,
  predecessor,
  successor,
  type,
  verification,
  citing_paper: successor,
  cited_paper: predecessor,
  evidence: [],
});

describe("node metrics", () => {
  it("counts unique method neighbors at both ends without duplicate or reversed inflation", () => {
    const counts = methodConnectionCounts(papers, [
      relation("a", "b"),
      relation("a", "b"),
      relation("b", "a"),
      relation("c", "a"),
    ]);
    expect(counts).toEqual({ a: 2, b: 1, c: 1, isolated: 0 });
  });

  it("excludes citations, unverified inheritance, self links, and unknown endpoints", () => {
    const counts = methodConnectionCounts(papers, [
      relation("a", "b", "citation"),
      relation("b", "c", "inheritance", "pending"),
      relation("c", "c"),
      relation("a", "unknown"),
      relation("unknown", "b"),
    ]);
    expect(counts).toEqual({ a: 0, b: 0, c: 0, isolated: 0 });
  });

  it.each([
    [0, 18],
    [2, 18],
    [3, 22],
    [7, 22],
    [8, 26],
    [100, 26],
  ])("uses the expected radius for %i method neighbors", (count, radius) => {
    expect(nodeRadius(count)).toBe(radius);
  });

  it("limits the largest node to less than one and a half times the smallest", () => {
    expect(nodeRadius(100) / nodeRadius(0)).toBeLessThanOrEqual(1.5);
  });

  it("places labels beyond enlarged nodes while retaining readable spacing at low zoom", () => {
    expect(nodeLabelOffset(18, 1)).toBe(33);
    expect(nodeLabelOffset(26, 1)).toBe(41);
    expect(nodeLabelOffset(26, 0.25)).toBe(82);
  });

  it.each(["mainline", "branch"] as const)("keeps the circular %s boundary at its nominal radius", (role) => {
    expect(nodeOuterRadius(22, role)).toBe(22);
  });

  it("clears the resource square's corners instead of only its sides", () => {
    const boundary = nodeOuterRadius(18, "resource");
    expect(boundary).toBeCloseTo(25.4558441227);
    expect(boundary).toBeGreaterThan(18);
    expect(boundary * boundary).toBeCloseTo(18 * 18 + 18 * 18);
  });

  it("clears the optimization diamond's outer tips at every node size", () => {
    expect(nodeOuterRadius(18, "optimization")).toBeCloseTo(21.6374675043);
    expect(nodeOuterRadius(22, "optimization")).toBeCloseTo(26.4457936164);
    expect(nodeOuterRadius(26, "optimization")).toBeCloseTo(31.2541197284);
  });
});
