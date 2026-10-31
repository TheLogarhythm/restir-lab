import { useState, type Ref } from "react";
import { colorFor, directions, roleNames, statusNames } from "../data/labels";
import type { Paper, Relation } from "../data/types";
import { RelationDetails } from "./RelationDetails";
import { PaperFigures } from "./PaperFigures";
import { figureRecords } from "../data/load";

export function PaperDetails({
  paper,
  papers,
  relations,
  onSelect,
  onShare,
  headingRef,
}: {
  paper: Paper;
  papers: Paper[];
  relations: Relation[];
  onSelect: (id: string) => void;
  onShare: () => void;
  headingRef?: Ref<HTMLHeadingElement>;
}) {
  const [tab, setTab] = useState<"overview" | "relations" | "sources">(
    "overview",
  );
  return (
    <aside
      className="paper-details"
      aria-label="Paper details"
      style={{ "--direction": colorFor(paper.tags) } as React.CSSProperties}
    >
      <div className="detail-header">
        <div className="eyebrow">PAPER DETAILS</div>
        <div>
          <button
            className="icon-button"
            title="Share selected paper"
            aria-label="Share selected paper"
            onClick={onShare}
          >
            ↗
          </button>
        </div>
      </div>
      <div className="detail-scroll">
        <div className="paper-labels">
          <span className="status-pill">
            {statusNames[paper.publication_status]}
          </span>
          <span>{roleNames[paper.role]}</span>
          <span>{paper.year}</span>
        </div>
        <h2 ref={headingRef} tabIndex={-1}>{paper.short_title}</h2>
        <p className="detail-full-title">{paper.title}</p>
        <p className="authors">
          {paper.authors.length ? paper.authors.join(" · ") : "Author information not yet verified"}
        </p>
        <p className="venue">{paper.venue}</p>
        <div className="tag-list">
          {paper.tags.map((tag) => (
            <span key={tag} style={{ color: directions[tag]?.color }}>
              {directions[tag]?.label || tag}
            </span>
          ))}
        </div>
        <div className="paper-links">
          <a href={paper.links.paper} target="_blank" rel="noreferrer">
            Paper page ↗
          </a>
          {paper.links.pdf && (
            <a href={paper.links.pdf} target="_blank" rel="noreferrer">
              Public PDF ↗
            </a>
          )}
          {paper.links.code && (
            <a href={paper.links.code} target="_blank" rel="noreferrer">
              Code ↗
            </a>
          )}
        </div>
        {(paper.verification.metadata === "partial" ||
          !paper.links.pdf ||
          !paper.links.code) && (
          <p className="verification-note">
            {paper.verification.metadata === "partial" && (
              <span>Some bibliographic details still need verification.</span>
            )}
            {!paper.links.pdf && <span>No verified public PDF link.</span>}
            {!paper.links.code && <span>No verified code link.</span>}
          </p>
        )}
        <div className="detail-tabs" role="group" aria-label="Paper detail sections">
          <button
            aria-pressed={tab === "overview"}
            onClick={() => setTab("overview")}
          >
            Overview
          </button>
          <button
            aria-pressed={tab === "relations"}
            onClick={() => setTab("relations")}
          >
            Connections
          </button>
          <button
            aria-pressed={tab === "sources"}
            onClick={() => setTab("sources")}
          >
            Sources
          </button>
        </div>
        {tab === "overview" && (
          <div className="detail-content">
            <PaperFigures title={paper.short_title} record={figureRecords[paper.paper_id]} />
            <section>
              <h3>Research question</h3>
              <p className="problem">{paper.problem}</p>
            </section>
            <section>
              <h3>Key contributions</h3>
              <ul>
                {paper.contributions.map((text, index) => (
                  <li key={index}>{text}</li>
                ))}
              </ul>
            </section>
            <section>
              <h3>What changed</h3>
              <p>{paper.changes}</p>
            </section>
            <section>
              <h3>Scope & limitations</h3>
              <ul>
                {paper.limitations.map((text, index) => (
                  <li key={index}>{text}</li>
                ))}
              </ul>
            </section>
            <RelationDetails
              relations={relations}
              papers={papers}
              selected={paper.paper_id}
              onSelect={onSelect}
            />
          </div>
        )}
        {tab === "relations" && (
          <RelationDetails
            relations={relations}
            papers={papers}
            selected={paper.paper_id}
            onSelect={onSelect}
          />
        )}
        {tab === "sources" && (
          <div className="source-details">
            <h3>Verification</h3>
            <p>
              {paper.verification.metadata === "verified"
                ? "Metadata verified"
                : "Metadata partially verified"}{" "}
              ·{" "}
              {paper.verification.content === "full_text"
                ? "Based on the paper text"
                : "Based on the abstract only"}
            </p>
            <p>{paper.verification.notes}</p>
            {paper.doi && (
              <p className="doi">
                DOI{" "}
                <a
                  href={`https://doi.org/${paper.doi}`}
                  target="_blank"
                  rel="noreferrer"
                >
                  {paper.doi} ↗
                </a>
              </p>
            )}
            <h3>Public sources</h3>
            {paper.sources.map((source, index) => (
              <div className="source-item" key={index}>
                <a href={source.url} target="_blank" rel="noreferrer">
                  {source.kind === "publisher"
                    ? "Publisher"
                    : source.kind === "author"
                      ? "Author"
                      : "Research institution"}{" "}
                  ↗
                </a>
                <p>{source.note}</p>
                <small>Checked {source.checked}</small>
              </div>
            ))}
            {!paper.links.pdf && (
              <p>
                A public full-text link has not yet been verified. Check the paper page for available versions.
              </p>
            )}
            <p className="muted">
              This site links to public sources and does not redistribute PDFs. Connections were checked with research assistance tools; this does not record whether you have read a paper.
            </p>
          </div>
        )}
      </div>
    </aside>
  );
}
