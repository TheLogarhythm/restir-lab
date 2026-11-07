import type { GraphEdge, Paper } from "../data/types";
import { Modal } from "./Modal";
import { RelationEvidence } from "./RelationEvidence";

export function ConnectionDialog({ edge, papers, onClose, onRead }: {
  edge: GraphEdge;
  papers: Paper[];
  onClose: () => void;
  onRead: (id: string) => void;
}) {
  return (
    <Modal titleId="edge-title" onClose={onClose}>
      <button
        className="dialog-close icon-button"
        aria-label="Close connection evidence"
        onClick={onClose}
      >
        ×
      </button>
      <span className="eyebrow">VERIFIED RELATION</span>
      <h2 id="edge-title">
        {papers.find((paper) => paper.paper_id === edge.source)?.short_title}{" "}
        →{" "}
        {papers.find((paper) => paper.paper_id === edge.target)?.short_title}
      </h2>
      {edge.relations.map((relation) => (
        <section key={relation.id}>
          <h3>{relation.type === "inheritance" ? "Method lineage" : "Citation"}</h3>
          <RelationEvidence evidence={relation.evidence} />
        </section>
      ))}
      <button className="primary-button" onClick={() => onRead(edge.target)}>
        Read later paper
      </button>
    </Modal>
  );
}
