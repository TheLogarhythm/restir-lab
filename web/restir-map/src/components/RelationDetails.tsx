import type { Paper, Relation } from "../data/types";
import { RelationEvidence } from "./RelationEvidence";

export function RelationDetails({
  relations,
  papers,
  selected,
  onSelect,
}: {
  relations: Relation[];
  papers: Paper[];
  selected: string;
  onSelect: (id: string) => void;
}) {
  const verified = relations.filter(
    (r) =>
      r.verification === "verified" &&
      (r.predecessor === selected || r.successor === selected),
  );
  const groups = new Map<string, Relation[]>();
  for (const relation of verified) {
    const key = `${relation.predecessor}--${relation.successor}`;
    groups.set(key, [...(groups.get(key) || []), relation]);
  }
  return (
    <section className="relation-details">
      <h3>
        Connections & evidence <span>{groups.size}</span>
      </h3>
      {!groups.size && (
        <p className="muted">
          No connections have been verified yet. Other connections may exist.
        </p>
      )}
      {[...groups.entries()].map(([id, items]) => {
        const first = items[0],
          other =
            first.predecessor === selected
              ? first.successor
              : first.predecessor,
          paper = papers.find((p) => p.paper_id === other);
        return (
          <details key={id} className="relation-item">
            <summary>
              <span className="relation-direction">
                {first.successor === selected ? "Earlier work" : "Later work"}
              </span>
              <span>{paper?.short_title || other}</span>
              <span className="relation-kind">
                {items.some((r) => r.type === "inheritance")
                  ? "Method lineage"
                  : "Citation"}
                {items.length > 1 ? " + Citation" : ""}
              </span>
            </summary>
            <div className="relation-body">
              <button className="text-button" onClick={() => onSelect(other)}>
                Read {paper?.short_title} <span aria-hidden="true">↗</span>
              </button>
              {items.map((relation) => (
                <div key={relation.id}>
                  <div className="evidence-type">
                    {relation.type === "inheritance"
                      ? "Evidence of method reuse"
                      : "Citation evidence"}
                  </div>
                  <RelationEvidence evidence={relation.evidence} />
                </div>
              ))}
            </div>
          </details>
        );
      })}
    </section>
  );
}
