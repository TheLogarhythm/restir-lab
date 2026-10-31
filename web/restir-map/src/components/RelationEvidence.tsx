import type { Relation } from "../data/types";

export function RelationEvidence({ evidence }: { evidence: Relation["evidence"] }) {
  return evidence.map((item, index) => (
    <div className="evidence" key={index}>
      <p>{item.explanation}</p>
      <a href={item.source_url} target="_blank" rel="noreferrer">
        {item.locator} ↗
      </a>
      <small>
        {item.method === "reference_list_review"
          ? "Reference list checked"
          : "Paper text checked"}{" "}
        · {item.checked}
      </small>
    </div>
  ));
}
