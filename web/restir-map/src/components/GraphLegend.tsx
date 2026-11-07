import { directions, roleNames } from "../data/labels";
import type { LegendHighlight, PaperRole, ResearchDirection } from "../data/types";

const symbols = { mainline: "◎", branch: "○", optimization: "◇", resource: "□" };

export function GraphLegend({ active, onChange }: {
  active: LegendHighlight;
  onChange: (highlight: LegendHighlight) => void;
}) {
  const pressed = (kind: "direction" | "role", value: string) => active?.kind === kind && active.value === value;
  const toggle = (highlight: NonNullable<LegendHighlight>) =>
    onChange(pressed(highlight.kind, highlight.value) ? null : highlight);
  return <div className="graph-legend" aria-label="Graph legend">
    <div className="direction-legend" role="group" aria-label="Highlight a research area">
      {Object.entries(directions).map(([id, direction]) => <button key={id}
        aria-label={`Research area: ${direction.label}`} aria-pressed={pressed("direction", id)}
        onClick={() => toggle({ kind: "direction", value: id as ResearchDirection })}>
        <i style={{ background: direction.color }} aria-hidden="true" />{direction.label}
      </button>)}
    </div>
    <div className="shape-legend" role="group" aria-label="Highlight a classification">
      {Object.entries(roleNames).map(([id, name]) => <button key={id}
        aria-label={`Classification: ${name}`} aria-pressed={pressed("role", id)}
        onClick={() => toggle({ kind: "role", value: id as PaperRole })}><span aria-hidden="true">{symbols[id as PaperRole]}</span> {name}</button>)}
    </div>
    <div className="relationship-legend">
      <span><i className="legend-line" /> Method lineage</span>
      <span><i className="legend-line dashed" /> Citation</span>
      <span>Earlier work → later work</span>
    </div>
  </div>;
}
