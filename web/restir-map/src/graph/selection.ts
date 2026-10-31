import type {
  EdgeMode,
  Filters,
  GraphEdge,
  LegendHighlight,
  Paper,
  Relation,
} from "../data/types";
import { directions } from "../data/labels";
import { readingEntries } from "../data/readingEntries";

export function matchesLegend(paper: Paper, highlight: LegendHighlight): boolean {
  return !highlight || (highlight.kind === "direction"
    ? paper.tags.includes(highlight.value)
    : paper.role === highlight.value);
}

export function legendReadingSelection(
  papers: Paper[], selected: string | null, highlight: LegendHighlight,
): string | null {
  if (!highlight || papers.some(paper => paper.paper_id === selected && matchesLegend(paper, highlight))) return selected;
  const candidates = papers.filter(paper => matchesLegend(paper, highlight));
  const entry = highlight.kind === "direction"
    ? readingEntries.direction[highlight.value]
    : readingEntries.role[highlight.value];
  // Reduced collections still work; fallback order is independent of array order.
  return candidates.find(paper => paper.paper_id === entry)?.paper_id
    ?? candidates.sort((a, b) => a.year - b.year || a.paper_id.localeCompare(b.paper_id))[0]?.paper_id
    ?? selected;
}

export function filterPapers(papers: Paper[], filters: Filters): Paper[] {
  const terms = filters.query
    .trim()
    .toLocaleLowerCase()
    .split(/\s+/)
    .filter(Boolean);
  return papers
    .filter((paper) => {
      const text = [
        paper.title,
        paper.short_title,
        ...paper.authors,
        paper.problem,
        paper.venue,
        ...paper.tags.map((tag) => `${tag} ${directions[tag]?.label || ""}`),
      ]
        .join(" ")
        .toLocaleLowerCase();
      return (
        terms.every((term) => text.includes(term)) &&
        (filters.tag === "all" || paper.tags.includes(filters.tag)) &&
        (filters.year === "all" || paper.year === Number(filters.year)) &&
        (filters.status === "all" ||
          paper.publication_status === filters.status)
      );
    })
    .sort((a, b) => a.year - b.year || a.title.localeCompare(b.title));
}
export function coalesceRelations(
  relations: Relation[],
  mode: EdgeMode,
): GraphEdge[] {
  const groups = new Map<string, GraphEdge>();
  for (const relation of relations) {
    if (
      relation.verification !== "verified" ||
      (mode !== "all" && relation.type !== mode)
    )
      continue;
    const id = `${relation.predecessor}--${relation.successor}`;
    const edge = groups.get(id);
    if (edge) {
      edge.relations.push(relation);
      if (relation.type === "inheritance") edge.type = "inheritance";
    } else
      groups.set(id, {
        id,
        source: relation.predecessor,
        target: relation.successor,
        type: relation.type,
        relations: [relation],
      });
  }
  return [...groups.values()];
}
export function readSelection(hash: string, papers: Paper[]): string | null {
  const value = new URLSearchParams(hash.replace(/^#/, "")).get("paper");
  return papers.some((paper) => paper.paper_id === value) ? value :
    papers.find(paper => paper.paper_id === "restir_di2020")?.paper_id ?? papers[0]?.paper_id ?? null;
}
export function shareHash(id: string | null): string {
  return id ? `#paper=${encodeURIComponent(id)}` : "";
}
export function relatedIds(id: string, edges: GraphEdge[]): Set<string> {
  const result = new Set([id]);
  for (const edge of edges) {
    if (edge.source === id) result.add(edge.target);
    if (edge.target === id) result.add(edge.source);
  }
  return result;
}
