import { colorFor, roleNames, graphLabelLines } from "../data/labels";
import type { Paper, Point } from "../data/types";

export function PaperNode({
  paper,
  point,
  selected,
  highlighted,
  dimmed,
  scale,
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
  showLabel: boolean;
  onSelect: () => void;
  onHover: (id: string | null) => void;
  onPointerDown: (event: React.PointerEvent<SVGGElement>) => void;
}) {
  const lines = graphLabelLines(paper);
  const fontSize = Math.max(12, 11.5 / scale);
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
      <circle className="node-hit" r="29" fill="transparent" />
      <circle className="node-halo" r="26" />
      {paper.role === "optimization" ? (
        <rect
          className="node-shape"
          x="-13"
          y="-13"
          width="26"
          height="26"
          rx="3"
          transform="rotate(45)"
        />
      ) : paper.role === "resource" ? (
        <rect
          className="node-shape"
          x="-15"
          y="-15"
          width="30"
          height="30"
          rx="4"
        />
      ) : (
        <circle
          className="node-shape"
          r={paper.role === "mainline" ? 20 : 15}
        />
      )}
      {paper.role === "mainline" && <circle className="node-inner" r="11" />}
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
          <tspan key={index} x="0" y={40 + index * fontSize * 1.15}>
            {line}
          </tspan>
        ))}
      </text>
      <text
        className="node-year"
        textAnchor="middle"
        y={43 + lines.length * fontSize * 1.15}
        style={{ fontSize: Math.max(9, 10 / scale) }}
      >
        {paper.year}
      </text></>}
    </g>
  );
}
