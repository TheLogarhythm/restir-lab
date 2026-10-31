import { useId, useState } from "react";
import type { PaperFigure, PaperFigureRecord } from "../data/types";
import { Modal } from "./Modal";
import "../styles/paper-figures.css";

export function PaperFigures({ title, record }: { title: string; record?: PaperFigureRecord }) {
  const headingId = useId();
  const [expanded, setExpanded] = useState<number | null>(null);
  const [failed, setFailed] = useState<Set<string>>(() => new Set());
  if (!record) return null;
  if (record.status === "unavailable") {
    return <p className="figure-unavailable">{record.reason}</p>;
  }
  const current = expanded === null ? null : record.images[expanded];
  const src = (figure: PaperFigure) => `${import.meta.env.BASE_URL}${figure.src}`;
  return (
    <section className="paper-figures" aria-label="Representative figures">
      <h3>At a glance</h3>
      {record.images.map((figure, index) => (
        <figure key={figure.id}>
          {failed.has(figure.id) ? (
            <a className="figure-fallback" href={figure.source_url} target="_blank" rel="noreferrer">View figure at source ↗</a>
          ) : (
            <button className="figure-preview" aria-label={`Enlarge image ${index + 1} for ${title}`} onClick={() => setExpanded(index)}>
              <img src={src(figure)} alt={figure.alt} width={figure.width} height={figure.height} loading="lazy" decoding="async"
                onError={() => setFailed(previous => new Set(previous).add(figure.id))} />
              <span className="figure-enlarge" aria-hidden="true">Enlarge ↗</span>
            </button>
          )}
          <figcaption>
            <p>{figure.caption}</p>
            <FigureCredit figure={figure} />
          </figcaption>
        </figure>
      ))}
      {current && expanded !== null && (
        <Modal titleId={headingId} className="figure-dialog" onClose={() => setExpanded(null)}>
          <button className="dialog-close icon-button" aria-label="Close enlarged figure" onClick={() => setExpanded(null)}>×</button>
          <h2 id={headingId}>{title} — Image {expanded + 1}</h2>
          <img className="figure-full" src={src(current)} alt={current.alt} width={current.width} height={current.height} />
          <p>{current.caption}</p>
          <FigureCredit figure={current} />
        </Modal>
      )}
    </section>
  );
}

function FigureCredit({ figure }: { figure: PaperFigure }) {
  return <div className="figure-credit">
    <a href={figure.source_url} target="_blank" rel="noreferrer">{figure.source_locator} ↗</a>
    <span>{figure.credit}</span>
  </div>;
}
