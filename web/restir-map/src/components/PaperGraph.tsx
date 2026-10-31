import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from "react";
import { colorFor, directions, roleNames } from "../data/labels";
import type { GraphEdge, Paper, Point, View } from "../data/types";
import { edgePath, fitView, initialLayout, visibleLabelIds, zoomAt } from "../graph/layout";
import { relatedIds } from "../graph/selection";
import { PaperNode } from "./PaperNode";

type Props = {
  papers: Paper[];
  allPapers: Paper[];
  edges: GraphEdge[];
  selected: string | null;
  hovered: string | null;
  onSelect: (id: string) => void;
  onHover: (id: string | null) => void;
  onEdge: (edge: GraphEdge) => void;
  resetToken: number;
  zoomAction: { factor: number; token: number };
  onZoomChange: (zoom: number) => void;
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
  resetToken,
  zoomAction,
  onZoomChange,
}: Props) {
  const markerPrefix = useId();
  const container = useRef<HTMLDivElement>(null),
    svg = useRef<SVGSVGElement>(null);
  const [size, setSize] = useState({ width: 900, height: 660 });
  const sizeRef = useRef(size);
  sizeRef.current = size;
  const [positions, setPositions] = useState(() => initialLayout(allPapers));
  const positionsRef = useRef(positions);
  positionsRef.current = positions;
  const [view, setView] = useState<View>({ x: 0, y: 0, scale: 1 });
  const [fitted, setFitted] = useState(false);
  const gesture = useRef<{
    id: string | null;
    start: Point;
    origin: Point;
    pointer: number;
    moved: boolean;
  } | null>(null);
  const suppressClick = useRef(false);
  const active = hovered || selected;
  const labels = useMemo(() => visibleLabelIds(papers, positions, view.scale, active), [papers, positions, view.scale, active]);
  const connected = useMemo(
    () => (active ? relatedIds(active, edges) : null),
    [active, edges],
  );
  const visible = new Set(papers.map((p) => p.paper_id));
  const activePaper = hovered
    ? allPapers.find((p) => p.paper_id === hovered)
    : null;
  useLayoutEffect(() => {
    const element = container.current;
    if (!element) return;
    const update = () => {
      setSize({
        width: element.clientWidth || 900,
        height: element.clientHeight || 660,
      });
      setFitted(false);
    };
    update();
    const observer = new ResizeObserver(update);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    setPositions(initialLayout(allPapers));
    setFitted(false);
  }, [allPapers]);
  useEffect(() => {
    if (!fitted) {
      setView(
        fitView(
          Object.fromEntries(
            papers
              .map((p) => [p.paper_id, positions[p.paper_id]])
              .filter(([, p]) => p),
          ),
          size.width,
          size.height,
        ),
      );
      setFitted(true);
    }
  }, [fitted, papers, positions, size]);
  useEffect(() => {
    if (!selected) return;
    const point = positionsRef.current[selected];
    if (!point) return;
    setView((current) => {
      const scale = Math.max(0.65, current.scale);
      return {
        scale,
        x: size.width / 2 - point.x * scale,
        y: size.height / 2 - point.y * scale,
      };
    });
  }, [selected, size, allPapers]);
  useEffect(() => {
    setPositions(initialLayout(allPapers));
    setFitted(false);
  }, [resetToken, allPapers]);
  useEffect(() => {
    if (!zoomAction.token) return;
    setView((current) =>
      zoomAt(current, zoomAction.factor, {
        x: sizeRef.current.width / 2,
        y: sizeRef.current.height / 2,
      }),
    );
  }, [zoomAction]);
  useEffect(() => {
    onZoomChange(view.scale);
  }, [view.scale, onZoomChange]);
  useEffect(() => {
    const element = svg.current;
    if (!element) return;
    const wheel = (event: WheelEvent) => {
      event.preventDefault();
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
  function startGesture(event: React.PointerEvent, id: string | null) {
    if (event.button !== 0) return;
    event.stopPropagation();
    gesture.current = {
      id,
      start: { x: event.clientX, y: event.clientY },
      origin: id ? positions[id] : { x: view.x, y: view.y },
      pointer: event.pointerId,
      moved: false,
    };
  }
  function moveGesture(event: React.PointerEvent) {
    const drag = gesture.current;
    if (!drag || drag.pointer !== event.pointerId) return;
    const dx = event.clientX - drag.start.x,
      dy = event.clientY - drag.start.y;
    if (Math.hypot(dx, dy) > 4 && !drag.moved) {
      drag.moved = true;
      svg.current?.setPointerCapture?.(event.pointerId);
    }
    if (!drag.moved) return;
    if (drag.id)
      setPositions((current) => ({
        ...current,
        [drag.id!]: {
          x: drag.origin.x + dx / view.scale,
          y: drag.origin.y + dy / view.scale,
        },
      }));
    else
      setView((current) => ({
        ...current,
        x: drag.origin.x + dx,
        y: drag.origin.y + dy,
      }));
  }
  function stopGesture(event: React.PointerEvent) {
    if (gesture.current?.pointer !== event.pointerId) return;
    suppressClick.current = gesture.current.moved;
    gesture.current = null;
    if (svg.current?.hasPointerCapture?.(event.pointerId))
      svg.current.releasePointerCapture(event.pointerId);
    window.setTimeout(() => {
      suppressClick.current = false;
    }, 0);
  }
  return (
    <div className="graph-canvas" ref={container}>
      <div className="graph-corner">
        <span className="eyebrow">RESEARCH NETWORK</span>
        <p>Follow how ideas develop.</p>
      </div>
      <svg
        ref={svg}
        className="network-svg"
        width="100%"
        height="100%"
        aria-label="ReSTIR research network"
        role="group"
        tabIndex={0}
        onPointerDown={(e) => startGesture(e, null)}
        onPointerMove={moveGesture}
        onPointerUp={stopGesture}
        onPointerCancel={stopGesture}
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
            setView((v) => ({
              ...v,
              x: v.x + steps[e.key].x,
              y: v.y + steps[e.key].y,
            }));
          }
          if (e.key === "+" || e.key === "=") {
            e.preventDefault();
            setView((v) =>
              zoomAt(v, 1.2, { x: size.width / 2, y: size.height / 2 }),
            );
          }
          if (e.key === "-") {
            e.preventDefault();
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
              const highlighted =
                !!active && (edge.source === active || edge.target === active);
              const markerId = `${markerPrefix}-arrow-${index}`;
              const sourceTitle = allPapers.find((paper) => paper.paper_id === edge.source)?.short_title;
              const targetTitle = allPapers.find((paper) => paper.paper_id === edge.target)?.short_title;
              const label = `${sourceTitle} → ${targetTitle} · View ${edge.type === "inheritance" ? "method lineage" : "citation"} evidence`;
              return (
                <g
                  key={edge.id}
                  className={`graph-edge ${edge.type} ${highlighted ? "highlighted" : ""} ${active && !highlighted ? "dimmed" : ""}`}
                  role="button"
                  tabIndex={0}
                  aria-label={label}
                  onPointerDown={(event) => event.stopPropagation()}
                  onClick={() => onEdge(edge)}
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
                    d={edgePath(positions[edge.source], positions[edge.target])}
                    markerEnd={`url(#${markerId})`}
                  />
                  <path
                    className="edge-hit"
                    vectorEffect="non-scaling-stroke"
                    d={edgePath(positions[edge.source], positions[edge.target])}
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
              showLabel={labels.has(paper.paper_id)}
              selected={selected === paper.paper_id}
              highlighted={!!connected?.has(paper.paper_id)}
              dimmed={!!active && !connected?.has(paper.paper_id)}
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
      <div className="graph-hint">
        {view.scale < 0.46 ? "Fewer labels at this scale · Zoom in or select a paper" : "Drag nodes or the background · Scroll to zoom"} <span>Tab to focus · Enter to read</span>
      </div>
    </div>
  );
}
