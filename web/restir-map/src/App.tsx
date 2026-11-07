import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties } from "react";
import {
  papers as sourcePapers,
  relations as sourceRelations,
  cutoffDate,
} from "./data/load";
import { GraphLegend } from "./components/GraphLegend";
import { methodConnectionCounts } from "./graph/nodeMetrics";
import type {
  EdgeMode,
  Filters,
  GraphEdge,
  LegendHighlight,
  Paper,
  Relation,
} from "./data/types";
import {
  coalesceRelations,
  filterPapers,
  matchesLegend,
  legendReadingSelection,
  readSelection,
  shareHash,
} from "./graph/selection";
import { PaperList } from "./components/PaperList";
import { PaperGraph } from "./components/PaperGraph";
import { PaperDetails } from "./components/PaperDetails";
import { GraphControls } from "./components/GraphControls";
import { AboutDialog } from "./components/AboutDialog";
import { ConnectionDialog } from "./components/ConnectionDialog";
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
  const detailsHeading = useRef<HTMLHeadingElement>(null);
  const focusReading = useRef(false);
  const [detailsWidth, setDetailsWidth] = useState<number | null>(null);
  const [filters, setFilters] = useState<Filters>(emptyFilters);
  const [selected, setSelected] = useState<string | null>(() =>
    readSelection(window.location.hash, papers),
  );
  const [hovered, setHovered] = useState<string | null>(null),
    [mode, setMode] = useState<EdgeMode>("inheritance");
  const [legendHighlight, setLegendHighlight] = useState<LegendHighlight>(null);
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
  const connectionCounts = useMemo(() => methodConnectionCounts(papers, relations), [papers, relations]);
  const highlightedIds = useMemo(() => legendHighlight ? new Set(papers.filter(paper =>
    matchesLegend(paper, legendHighlight)
  ).map(paper => paper.paper_id)) : null, [papers, legendHighlight]);
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
  const selectForReading = useCallback(
    (id: string) => {
      setSelected(id);
      setEdgeDetail(null);
      setHovered(null);
      window.history.pushState(
        null,
        "",
        `${window.location.pathname}${window.location.search}${shareHash(id)}`,
      );
    },
    [],
  );
  const onSelect = useCallback(
    (id: string) => {
      const paper = papers.find(p => p.paper_id === id);
      if (!paper) return;
      selectForReading(id);
      setLegendHighlight(current => matchesLegend(paper, current) ? current : null);
      if (!visible.some(p => p.paper_id === id)) {
        setFilters(emptyFilters);
        setNotice("Filters cleared to show the related paper.");
      }
    },
    [papers, visible, selectForReading],
  );
  function onReadRelated(id: string) {
    if (!papers.some(paper => paper.paper_id === id)) return;
    focusReading.current = true;
    onSelect(id);
  }
  useEffect(() => {
    if (!focusReading.current) return;
    focusReading.current = false;
    // Run after dialog cleanup restores its trigger, then continue in the paper.
    detailsHeading.current?.focus({ preventScroll: true });
  }, [selected, edgeDetail]);
  function onLegendChange(highlight: LegendHighlight) {
    setLegendHighlight(highlight);
    const next = legendReadingSelection(papers, selected, highlight);
    if (next && next !== selected) selectForReading(next);
  }
  useEffect(() => {
    const sync = () => {
      const next = readSelection(window.location.hash, papers);
      const paper = papers.find(p => p.paper_id === next);
      setSelected(next);
      setLegendHighlight(current => paper && matchesLegend(paper, current) ? current : null);
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
  }, [edgeDetail, about]);
  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(""), 5000);
    return () => clearTimeout(timer);
  }, [notice]);
  async function share() {
    const url = new URL(window.location.href);
    url.hash = shareHash(selected);
    window.history.replaceState(null, "", url.href);
    try {
      await navigator.clipboard.writeText(url.href);
      setNotice("Paper link copied.");
    } catch {
      setNotice("Copy the URL in your address bar to share this paper.");
    }
  }
  return (
    <div className="app-shell">
      <a className="skip-link" href="#explore" onClick={(event) => { event.preventDefault(); document.getElementById("explore")?.focus(); }}>
        Skip to research network
      </a>
      <header className="site-header">
        <a
          className="brand"
          href={import.meta.env.BASE_URL}
          aria-label="ReSTIR Atlas home"
        >
          {/* Tabler prism-light, MIT; license bundled under public/licenses. */}
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M4.731 19h11.539a1 1 0 0 0 .866 -1.5l-5.769 -10a1 1 0 0 0 -1.732 0l-5.769 10a1 1 0 0 0 .865 1.5" />
            <path d="M2 13h4.45" /><path d="M18 5l-4.5 6" />
            <path d="M22 9l-7.75 3.25" /><path d="M22 15l-7 -1.5" />
          </svg>
          <strong>
            ReSTIR <span>Atlas</span>
          </strong>
          <span className="brand-count">({papers.length} papers)</span>
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
          highlightedIds={highlightedIds}
        />
        <main className="exploration" id="explore" tabIndex={-1}>
          <h1 className="sr-only">ReSTIR research network</h1>
          <GraphControls mode={mode} onMode={setMode} />
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
                connectionCounts={connectionCounts}
                highlightedIds={highlightedIds}
              />
              <GraphLegend active={legendHighlight} onChange={onLegendChange} />
            </div>
            {selectedPaper && (
              <PaperDetails
                key={selectedPaper.paper_id}
                headingRef={detailsHeading}
                paper={selectedPaper}
                papers={papers}
                relations={relations}
                onSelect={onReadRelated}
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
        <AboutDialog cutoffDate={cutoffDate} onClose={() => setAbout(false)} />
      )}
      {edgeDetail && (
        <ConnectionDialog
          edge={edgeDetail}
          papers={papers}
          onClose={() => setEdgeDetail(null)}
          onRead={onReadRelated}
        />
      )}
    </div>
  );
}
