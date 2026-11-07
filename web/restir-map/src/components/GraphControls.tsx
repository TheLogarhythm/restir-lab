import type { EdgeMode } from "../data/types";

export function GraphControls({ mode, onMode }: { mode: EdgeMode; onMode: (mode: EdgeMode) => void }) {
  return <div className="graph-toolbar">
    <div className="segmented" role="group" aria-label="Connection view">
      <button aria-pressed={mode === "inheritance"} onClick={() => onMode("inheritance")}>Method lineage</button>
      <button aria-pressed={mode === "all"} onClick={() => onMode("all")}>All connections</button>
      <button aria-pressed={mode === "citation"} onClick={() => onMode("citation")}>Citations only</button>
    </div>
  </div>;
}
