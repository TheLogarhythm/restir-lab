import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties } from "react";
import {
  papers as sourcePapers,
  relations as sourceRelations,
  cutoffDate,
} from "./data/load";
import { directions } from "./data/labels";
import type {
  EdgeMode,
  Filters,
  GraphEdge,
  Paper,
  Relation,
} from "./data/types";
import {
  coalesceRelations,
  filterPapers,
  readSelection,
  shareHash,
} from "./graph/selection";
import { PaperList } from "./components/PaperList";
import { PaperGraph } from "./components/PaperGraph";
import { PaperDetails } from "./components/PaperDetails";
import { GraphControls } from "./components/GraphControls";
import { Modal } from "./components/Modal";
import { detailsPanelWidth } from "./graph/panelWidth";
import "./styles/graph-interactions.css";

const emptyFilters: Filters = {
  query: "",
  tag: "all",
  year: "all",
  status: "all",
};
export default function App({
  papers = sourcePapers,
  relations = sourceRelations,
}: {
  papers?: Paper[];
  relations?: Relation[];
}) {
  const workspace = useRef<HTMLDivElement>(null);
  const [detailsWidth, setDetailsWidth] = useState<number | null>(null);
  const [filters, setFilters] = useState<Filters>(emptyFilters);
  const [selected, setSelected] = useState<string | null>(() =>
    readSelection(window.location.hash, papers),
  );
  const [hovered, setHovered] = useState<string | null>(null),
    [mode, setMode] = useState<EdgeMode>("inheritance");
  const [resetToken, setResetToken] = useState(0),
    [zoom, setZoom] = useState(1),
    [zoomAction, setZoomAction] = useState({ factor: 1, token: 0 });
  const [notice, setNotice] = useState(""),
    [about, setAbout] = useState(false),
    [edgeDetail, setEdgeDetail] = useState<GraphEdge | null>(null);
  const visible = useMemo(
    () => filterPapers(papers, filters),
    [papers, filters],
  );
  const edges = useMemo(
    () => coalesceRelations(relations, mode),
    [relations, mode],
  );
  const selectedPaper = papers.find((paper) => paper.paper_id === selected);
  useLayoutEffect(() => {
    const sidebar = workspace.current?.querySelector<HTMLElement>(".paper-sidebar");
    if (!sidebar) return;
    const update = () => {
      setDetailsWidth(detailsPanelWidth(window.innerWidth, sidebar.getBoundingClientRect().width));
    };
    update();
    const observer = new ResizeObserver(update);
    observer.observe(sidebar);
    window.addEventListener("resize", update);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", update);
    };
  }, []);
  const onSelect = useCallback(
    (id: string) => {
      setSelected(id);
      setEdgeDetail(null);
      setHovered(null);
      if (!visible.some((p) => p.paper_id === id)) {
        setFilters(emptyFilters);
        setNotice("Filters cleared to show the related paper.");
      }
      window.history.pushState(
        null,
        "",
        `${window.location.pathname}${window.location.search}${shareHash(id)}`,
      );
    },
    [visible],
  );
  const clear = useCallback(() => {
    setSelected(null);
    setHovered(null);
    setEdgeDetail(null);
    window.history.pushState(
      null,
      "",
      `${window.location.pathname}${window.location.search}`,
    );
  }, []);
  useEffect(() => {
    const sync = () => {
      setSelected(readSelection(window.location.hash, papers));
      setFilters(emptyFilters);
      setHovered(null);
      setEdgeDetail(null);
    };
    window.addEventListener("hashchange", sync);
    window.addEventListener("popstate", sync);
    return () => {
      window.removeEventListener("hashchange", sync);
      window.removeEventListener("popstate", sync);
    };
  }, [papers]);
  useEffect(() => {
    const keyboard = (event: KeyboardEvent) => {
      if (about || edgeDetail) return;
      const target = event.target as HTMLElement;
      if (event.key === "Escape") {
        setAbout(false);
        if (edgeDetail) setEdgeDetail(null);
        else clear();
      }
      if (
        event.key === "/" &&
        !["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)
      ) {
        event.preventDefault();
        document
          .querySelector<HTMLInputElement>('[aria-label="Search papers"]')
          ?.focus();
      }
    };
    window.addEventListener("keydown", keyboard);
    return () => window.removeEventListener("keydown", keyboard);
  }, [clear, edgeDetail, about]);
  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(""), 5000);
    return () => clearTimeout(timer);
  }, [notice]);
  async function share() {
    try {
      await navigator.clipboard.writeText(window.location.href);
      setNotice("Paper link copied.");
    } catch {
      setNotice("Copy the URL in your address bar to share this paper.");
    }
  }
  return (
    <div className="app-shell">
      <a className="skip-link" href="#explore">
        Skip to research network
      </a>
      <header className="site-header">
        <a
          className="brand"
          href={import.meta.env.BASE_URL}
          aria-label="ReSTIR Atlas home"
        >
          <svg viewBox="0 0 36 36" aria-hidden="true">
            <path d="M7 27 18 7 29 26" />
            <circle cx="7" cy="27" r="3" />
            <circle cx="18" cy="7" r="4" />
            <circle cx="29" cy="26" r="3" />
          </svg>
          <strong>
            ReSTIR <span>Atlas</span>
          </strong>
        </a>
        <div className="header-right">
          <span className="cutoff">Literature through {cutoffDate}</span>
          <button className="about-button" onClick={() => setAbout(true)}>
            About this map <span>↗</span>
          </button>
        </div>
      </header>
      <div
        className="workspace"
        ref={workspace}
        style={detailsWidth === null ? undefined : { "--paper-details-width": `${detailsWidth}px` } as CSSProperties}
      >
        <PaperList
          papers={visible}
          allPapers={papers}
          filters={filters}
          onFilters={setFilters}
          selected={selected}
          hovered={hovered}
          onSelect={onSelect}
          onHover={setHovered}
        />
        <main className="exploration" id="explore">
          <h1 className="sr-only">ReSTIR research network</h1>
          <GraphControls
            mode={mode}
            onMode={setMode}
            onReset={() => {
              setResetToken((n) => n + 1);
              setNotice("View and node positions reset.");
            }}
            onClear={clear}
            selected={!!selected}
            zoom={zoom}
            onZoom={(factor) =>
              setZoomAction((v) => ({ factor, token: v.token + 1 }))
            }
          />
          {selectedPaper && !visible.some((p) => p.paper_id === selected) && (
            <div className="selection-filter-note">
              The selected paper is hidden by your filters.
              <button onClick={() => setFilters(emptyFilters)}>
                Show selected paper
              </button>
            </div>
          )}
          <div
            className={`graph-and-details ${selectedPaper ? "has-selection" : ""}`}
          >
            <div className="graph-region">
              <PaperGraph
                papers={visible}
                allPapers={papers}
                edges={edges}
                selected={selected}
                hovered={hovered}
                onSelect={onSelect}
                onHover={setHovered}
                onEdge={setEdgeDetail}
                resetToken={resetToken}
                zoomAction={zoomAction}
                onZoomChange={setZoom}
              />
              <div className="graph-legend">
                <div className="direction-legend">
                  {Object.entries(directions).map(([id, d]) => (
                    <span key={id}>
                      <i style={{ background: d.color }} />
                      {d.label}
                    </span>
                  ))}
                </div>
                <div className="relationship-legend">
                  <span>
                    <i className="legend-line" /> Method lineage
                  </span>
                  <span>
                    <i className="legend-line dashed" /> Citation
                  </span>
                  <span className="arrow-explanation">Earlier work → later work</span>
                  <span className="shape-legend">
                    ◎ Mainline · ○ Branch · ◇ Optimization · □ Resource
                  </span>
                </div>
              </div>
            </div>
            {selectedPaper && (
              <PaperDetails
                key={selectedPaper.paper_id}
                paper={selectedPaper}
                papers={papers}
                relations={relations}
                onSelect={onSelect}
                onClear={clear}
                onShare={share}
              />
            )}
          </div>
        </main>
      </div>
      <div
        role="status"
        aria-live="polite"
        className={`toast ${notice ? "visible" : ""}`}
      >
        {notice}
      </div>
      {about && (
        <Modal titleId="about-title" onClose={() => setAbout(false)}>
          <button
            className="dialog-close icon-button"
            aria-label="Close about dialog"
            onClick={() => setAbout(false)}
          >
            ×
          </button>
          <span className="eyebrow">ABOUT THE ATLAS</span>
          <h2 id="about-title">Follow the evidence.</h2>
          <p>
            ReSTIR Atlas
            maps documented connections between research papers. It covers published work directly related to ReSTIR and a few essential foundations, with preprints, abstracts, courses and implementation resources labeled separately.
          </p>
          <p>
            <strong>Arrows point from earlier work to later work.</strong>{" "}
            A solid line means the later paper explicitly adopts, extends or improves the earlier method. A dashed line means it cites the earlier paper. The All connections view merges the two into one edge where both apply, while keeping their evidence separate.
          </p>
          <p>
            Mainline, branch and optimization are editorial groupings, not quality rankings or a prescribed reading order. Papers can span several research areas. Only verified connections are shown; a missing edge does not establish that no connection exists.
          </p>
          <p>
            The default Method lineage view follows how methods develop. Switch to All connections to include verified citations. Select a paper and use its share button to copy a link. Your browser’s Back and Forward buttons restore previous selections.
          </p>
          <div className="about-meta">
            Literature through {cutoffDate}
            <br />
            Keyboard: / to search · Tab to navigate · Enter to select · Esc to clear
            <br />
            With the network focused: arrow keys to pan, + / − to zoom
          </div>
          <button className="primary-button" onClick={() => setAbout(false)}>
            Start exploring
          </button>
        </Modal>
      )}
      {edgeDetail && (
        <Modal titleId="edge-title" onClose={() => setEdgeDetail(null)}>
          <button
            className="dialog-close icon-button"
            aria-label="Close connection evidence"
            onClick={() => setEdgeDetail(null)}
          >
            ×
          </button>
          <span className="eyebrow">VERIFIED RELATION</span>
          <h2 id="edge-title">
            {papers.find((p) => p.paper_id === edgeDetail.source)?.short_title}{" "}
            →{" "}
            {papers.find((p) => p.paper_id === edgeDetail.target)?.short_title}
          </h2>
          {edgeDetail.relations.map((relation) => (
            <section key={relation.id}>
              <h3>{relation.type === "inheritance" ? "Method lineage" : "Citation"}</h3>
              {relation.evidence.map((e, i) => (
                <div className="evidence" key={i}>
                  <p>{e.explanation}</p>
                  <a href={e.source_url} target="_blank" rel="noreferrer">
                    {e.locator} ↗
                  </a>
                  <small>
                    {e.method === "reference_list_review"
                      ? "Reference list checked"
                      : "Paper text checked"}{" "}
                    · {e.checked}
                  </small>
                </div>
              ))}
            </section>
          ))}
          <button
            className="primary-button"
            onClick={() => onSelect(edgeDetail.target)}
          >
            Read later paper
          </button>
        </Modal>
      )}
    </div>
  );
}
