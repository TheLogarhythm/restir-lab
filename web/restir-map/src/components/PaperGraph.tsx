import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from "react";
import { colorFor, directions, roleNames } from "../data/labels";
import type { GraphEdge, Paper, Point, View } from "../data/types";
import { edgePath, fitView, initialLayout, visibleLabelIds, zoomAt } from "../graph/layout";
import { relatedIds } from "../graph/selection";
import { nodeOuterRadius, nodeRadius } from "../graph/nodeMetrics";
import { PaperNode } from "./PaperNode";
import { useGraphGestures } from "../graph/useGraphGestures";

type Props = {
  papers: Paper[];
  allPapers: Paper[];
  edges: GraphEdge[];
  selected: string | null;
  hovered: string | null;
  onSelect: (id: string) => void;
  onHover: (id: string | null) => void;
  onEdge: (edge: GraphEdge) => void;
  connectionCounts: Record<string, number>;
  highlightedIds: Set<string> | null;
};
export function PaperGraph({
  papers,
  allPapers,
  edges,
  selected,
  hovered,
  onSelect,
  onHover,
  onEdge,
  connectionCounts,
  highlightedIds,
}: Props) {
  const markerPrefix = useId();
  const container = useRef<HTMLDivElement>(null),
    svg = useRef<SVGSVGElement>(null);
  const [size, setSize] = useState({ width: 900, height: 660 });
  const [storedPositions, setPositions] = useState(() => initialLayout(allPapers));
  // New papers need coordinates in this render, before the retention effect runs.
  const positions = useMemo(() => ({ ...initialLayout(allPapers), ...storedPositions }), [allPapers, storedPositions]);
  const positionsRef = useRef(positions);
  positionsRef.current = positions;
  const [view, setView] = useState<View>({ x: 0, y: 0, scale: 1 });
  const initiallyFitted = useRef(false);
  const { startGesture, moveGesture, stopGesture, cancelGesture, suppressClick } = useGraphGestures({
    svg, positionsRef, view, setPositions, setView, initiallyFitted,
  });
  const active = hovered || selected;
  const labels = useMemo(() => visibleLabelIds(papers, positions, view.scale, active, connectionCounts), [papers, positions, view.scale, active, connectionCounts]);
  const connected = useMemo(
    () => (active ? relatedIds(active, edges) : null),
    [active, edges],
  );
  const visible = new Set(papers.map((p) => p.paper_id));
  const hitRadiusLimits = useMemo(() => Object.fromEntries(papers.map(paper => {
    const point = positions[paper.paper_id];
    const distances = papers.filter(other => other.paper_id !== paper.paper_id && positions[other.paper_id]).map(other => Math.hypot(point.x - positions[other.paper_id].x, point.y - positions[other.paper_id].y));
    return [paper.paper_id, Math.min(...distances) * 0.45];
  })), [papers, positions]);
  const outerRadii = Object.fromEntries(allPapers.map(paper => [paper.paper_id, nodeOuterRadius(nodeRadius(connectionCounts[paper.paper_id] ?? 0), paper.role)]));
  const activePaper = hovered
    ? allPapers.find((p) => p.paper_id === hovered)
    : null;
  useLayoutEffect(() => {
    const element = container.current;
    if (!element) return;
    const update = () => {
      const width = element.clientWidth, height = element.clientHeight;
      if (!width || !height) return;
      setSize({ width, height });
      if (!initiallyFitted.current) {
        setView(fitView(positionsRef.current, width, height));
        initiallyFitted.current = true;
      }
    };
    const observer = new ResizeObserver(update);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    const initial = initialLayout(allPapers);
    setPositions(current => ({ ...initial, ...current }));
  }, [allPapers]);
  useEffect(() => {
    const element = svg.current;
    if (!element) return;
    const wheel = (event: WheelEvent) => {
      event.preventDefault();
      initiallyFitted.current = true;
      const box = element.getBoundingClientRect();
      setView((current) =>
        zoomAt(current, Math.exp(-event.deltaY * 0.0015), {
          x: event.clientX - box.left,
          y: event.clientY - box.top,
        }),
      );
    };
    element.addEventListener("wheel", wheel, { passive: false });
    return () => element.removeEventListener("wheel", wheel);
  }, []);
  function center() {
    initiallyFitted.current = true;
    const visiblePositions = Object.fromEntries(papers.filter(paper => positions[paper.paper_id]).map(paper => [paper.paper_id, positions[paper.paper_id]]));
    setView(fitView(visiblePositions, size.width, size.height));
  }
  return (
    <div className="graph-canvas" ref={container}>
      <p className="sr-only" id={`${markerPrefix}-instructions`}>
        Scroll or pinch with two fingers to zoom. Drag the background to pan or a paper to move it.
        With the network focused, use arrow keys to pan and + or - to zoom.
        Tab to a paper or connection and press Enter or Space to select it or open its evidence.
        Use Center to fit the visible papers without resetting their positions.
      </p>
      <div className="graph-center-control">
        <button className="icon-button graph-center" aria-label="Center" title="Center" onClick={center}>
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M8 3H3v5M16 3h5v5M21 16v5h-5M3 16v5h5M8 12h8M12 8v8" />
          </svg>
          <span className="graph-center-tooltip" aria-hidden="true">Center</span>
        </button>
      </div>
      <svg
        ref={svg}
        className="network-svg"
        width="100%"
        height="100%"
        aria-label="ReSTIR research network"
        aria-describedby={`${markerPrefix}-instructions`}
        role="group"
        tabIndex={0}
        onPointerDown={(e) => startGesture(e, null)}
        onPointerMove={moveGesture}
        onPointerUp={stopGesture}
        onPointerCancel={cancelGesture}
        onLostPointerCapture={(event) => {
          // Touch capture transfers from a node to the SVG when dragging starts.
          if (event.target === event.currentTarget) cancelGesture(event);
        }}
        onKeyDown={(e) => {
          if (e.target !== e.currentTarget) return;
          const steps: Record<string, Point> = {
            ArrowLeft: { x: 45, y: 0 },
            ArrowRight: { x: -45, y: 0 },
            ArrowUp: { x: 0, y: 45 },
            ArrowDown: { x: 0, y: -45 },
          };
          if (steps[e.key]) {
            e.preventDefault();
            initiallyFitted.current = true;
            setView((v) => ({
              ...v,
              x: v.x + steps[e.key].x,
              y: v.y + steps[e.key].y,
            }));
          }
          if (e.key === "+" || e.key === "=") {
            e.preventDefault();
            initiallyFitted.current = true;
            setView((v) =>
              zoomAt(v, 1.2, { x: size.width / 2, y: size.height / 2 }),
            );
          }
          if (e.key === "-") {
            e.preventDefault();
            initiallyFitted.current = true;
            setView((v) =>
              zoomAt(v, 1 / 1.2, { x: size.width / 2, y: size.height / 2 }),
            );
          }
        }}
      >
        <g transform={`translate(${view.x},${view.y}) scale(${view.scale})`}>
          {edges
            .filter(
              (edge) =>
                visible.has(edge.source) &&
                visible.has(edge.target) &&
                positions[edge.source] &&
                positions[edge.target],
            )
            .map((edge, index) => {
              const highlighted = highlightedIds
                ? highlightedIds.has(edge.source) || highlightedIds.has(edge.target)
                : !!active && (edge.source === active || edge.target === active);
              const path = edgePath(positions[edge.source], positions[edge.target], outerRadii[edge.source], outerRadii[edge.target], view.scale);
              const markerId = `${markerPrefix}-arrow-${index}`;
              const sourceTitle = allPapers.find((paper) => paper.paper_id === edge.source)?.short_title;
              const targetTitle = allPapers.find((paper) => paper.paper_id === edge.target)?.short_title;
              const label = `${sourceTitle} → ${targetTitle} · View ${edge.type === "inheritance" ? "method lineage" : "citation"} evidence`;
              return (
                <g
                  key={edge.id}
                  className={`graph-edge ${edge.type} ${highlighted ? "highlighted" : ""} ${(highlightedIds || active) && !highlighted ? "dimmed" : ""}`}
                  role="button"
                  tabIndex={0}
                  aria-label={label}
                  onPointerDown={(event) => event.pointerType === "touch" ? startGesture(event, null) : event.stopPropagation()}
                  onClick={() => { if (!suppressClick.current) onEdge(edge); }}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      event.stopPropagation();
                      onEdge(edge);
                    }
                  }}
                >
                  <defs>
                    <marker
                      id={markerId}
                      markerWidth={11 / view.scale}
                      markerHeight={11 / view.scale}
                      viewBox="-2 -2 11 11"
                      refX="7"
                      refY="3.5"
                      orient="auto"
                      markerUnits="userSpaceOnUse"
                    >
                      <path className="edge-arrowhead" d="M0,0 L7,3.5 L0,7" />
                    </marker>
                  </defs>
                  <path
                    className="edge-line"
                    vectorEffect="non-scaling-stroke"
                    d={path}
                    markerEnd={`url(#${markerId})`}
                  />
                  <path
                    className="edge-hit"
                    vectorEffect="non-scaling-stroke"
                    d={path}
                  >
                    <title>{label}</title>
                  </path>
                </g>
              );
            })}
          {papers.map((paper) => (
            <PaperNode
              key={paper.paper_id}
              paper={paper}
              point={positions[paper.paper_id] || { x: 0, y: 0 }}
              scale={view.scale}
              connectionCount={connectionCounts[paper.paper_id] ?? 0}
              hitRadiusLimit={hitRadiusLimits[paper.paper_id]}
              showLabel={labels.has(paper.paper_id)}
              selected={selected === paper.paper_id}
              highlighted={highlightedIds ? highlightedIds.has(paper.paper_id) : !!connected?.has(paper.paper_id)}
              dimmed={highlightedIds ? !highlightedIds.has(paper.paper_id) : !!active && !connected?.has(paper.paper_id)}
              onSelect={() => {
                if (!suppressClick.current) onSelect(paper.paper_id);
              }}
              onHover={onHover}
              onPointerDown={(event) => startGesture(event, paper.paper_id)}
            />
          ))}
        </g>
      </svg>
      {!papers.length && (
        <div className="graph-empty">No papers match these filters. Try clearing them.</div>
      )}
      {activePaper && (
        <div
          className="node-tooltip"
          role="tooltip"
          style={{ borderLeftColor: colorFor(activePaper.tags) }}
        >
          <span>
            {activePaper.year} · {roleNames[activePaper.role]} ·{" "}
            {directions[activePaper.tags[0]]?.label}
          </span>
          <strong>{activePaper.short_title}</strong>
          <p>{activePaper.problem}</p>
          <small>Select to keep details open</small>
        </div>
      )}
    </div>
  );
}
