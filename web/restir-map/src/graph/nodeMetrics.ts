import type { Paper, Relation } from "../data/types";

export function methodConnectionCounts(papers: Paper[], relations: Relation[]): Record<string, number> {
  const neighbors = new Map(papers.map((paper) => [paper.paper_id, new Set<string>()]));
  for (const relation of relations) {
    const { predecessor, successor } = relation;
    if (
      relation.type !== "inheritance" ||
      relation.verification !== "verified" ||
      predecessor === successor ||
      !neighbors.has(predecessor) ||
      !neighbors.has(successor)
    ) continue;
    neighbors.get(predecessor)!.add(successor);
    neighbors.get(successor)!.add(predecessor);
  }
  return Object.fromEntries([...neighbors].map(([id, connected]) => [id, connected.size]));
}

export function nodeRadius(connectionCount: number): number {
  if (connectionCount >= 8) return 26;
  if (connectionCount >= 3) return 22;
  return 18;
}

export function nodeLabelOffset(radius: number, scale: number): number {
  return radius + Math.max(15, 14 / scale);
}

export function nodeOuterRadius(radius: number, role: Paper["role"]): number {
  if (role === "resource") return radius * Math.SQRT2;
  if (role === "optimization") return radius * 0.85 * Math.SQRT2;
  return radius;
}
