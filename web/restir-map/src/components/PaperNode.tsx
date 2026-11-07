import { colorFor, roleNames, graphLabelLines } from "../data/labels";
import type { Paper, Point } from "../data/types";
import { nodeLabelOffset, nodeOuterRadius, nodeRadius } from "../graph/nodeMetrics";

export function PaperNode({
  paper,
  point,
  selected,
  highlighted,
  dimmed,
  scale,
  connectionCount,
  hitRadiusLimit,
  showLabel,
  onSelect,
  onHover,
  onPointerDown,
}: {
  paper: Paper;
  point: Point;
  selected: boolean;
  highlighted: boolean;
  dimmed: boolean;
  scale: number;
  connectionCount: number;
  hitRadiusLimit: number;
  showLabel: boolean;
  onSelect: () => void;
  onHover: (id: string | null) => void;
  onPointerDown: (event: React.PointerEvent<SVGGElement>) => void;
}) {
  const lines = graphLabelLines(paper);
  const fontSize = Math.max(12, 11.5 / scale);
  const radius = nodeRadius(connectionCount);
  const outerRadius = nodeOuterRadius(radius, paper.role);
  const labelOffset = nodeLabelOffset(paper.role === "optimization" ? outerRadius : radius, scale);
  return (
    <g
      className={`paper-node ${selected ? "selected" : ""} ${highlighted ? "highlighted" : ""} ${dimmed ? "dimmed" : ""}`}
      transform={`translate(${point.x},${point.y})`}
      style={{ "--node-color": colorFor(paper.tags) } as React.CSSProperties}
      role="button"
      tabIndex={0}
      aria-label={`${paper.short_title}, ${paper.year}, ${roleNames[paper.role]}`}
      aria-pressed={selected}
      data-node-id={paper.paper_id}
      onClick={onSelect}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onSelect();
        }
      }}
      onMouseEnter={() => onHover(paper.paper_id)}
      onMouseLeave={() => onHover(null)}
      onFocus={() => onHover(paper.paper_id)}
      onBlur={() => onHover(null)}
      onPointerDown={onPointerDown}
    >
      <title>
        {paper.title} · {paper.year}
      </title>
      <circle className="node-hit" r={Math.min(hitRadiusLimit, Math.max(outerRadius + 7 / scale, 22 / scale))} fill="transparent" />
      <circle className="node-halo" r={outerRadius + 5 / scale} vectorEffect="non-scaling-stroke" pointerEvents="none" />
      {selected && <circle className="node-selection-ring" r={outerRadius + 5 / scale} fill="none" stroke="var(--node-color)" strokeWidth={2} vectorEffect="non-scaling-stroke" pointerEvents="none" />}
      {paper.role === "optimization" ? (
        <rect
          className="node-shape"
          x={-radius * 0.85}
          y={-radius * 0.85}
          width={radius * 1.7}
          height={radius * 1.7}
          rx="3"
          transform="rotate(45)"
          vectorEffect="non-scaling-stroke"
        />
      ) : paper.role === "resource" ? (
        <rect
          className="node-shape"
          x={-radius}
          y={-radius}
          width={radius * 2}
          height={radius * 2}
          rx="4"
          vectorEffect="non-scaling-stroke"
        />
      ) : (
        <circle
          className="node-shape"
          r={radius}
          vectorEffect="non-scaling-stroke"
        />
      )}
      {paper.role === "mainline" && <circle className="node-inner" r={radius * 0.55} vectorEffect="non-scaling-stroke" />}
      {paper.publication_status !== "published" && (
        <text className="node-resource-mark" textAnchor="middle" y="4">
          {paper.publication_status === "preprint"
            ? "P"
            : paper.publication_status === "course"
              ? "C"
              : "·"}
        </text>
      )}
      {showLabel && <><text className="node-label" textAnchor="middle" style={{ fontSize }}>
        {lines.map((line, index) => (
          <tspan key={index} x="0" y={labelOffset + index * fontSize * 1.15}>
            {line}
          </tspan>
        ))}
      </text>
      <text
        className="node-year"
        textAnchor="middle"
        y={labelOffset + 3 + lines.length * fontSize * 1.15}
        style={{ fontSize: Math.max(9, 10 / scale) }}
      >
        {paper.year}
      </text></>}
    </g>
  );
}
