import type { EdgeMode } from "../data/types";
export function GraphControls({
  mode,
  onMode,
  onReset,
  onClear,
  selected,
  zoom,
  onZoom,
}: {
  mode: EdgeMode;
  onMode: (mode: EdgeMode) => void;
  onReset: () => void;
  onClear: () => void;
  selected: boolean;
  zoom: number;
  onZoom: (factor: number) => void;
}) {
  return (
    <div className="graph-toolbar">
      <div className="segmented" role="group" aria-label="Connection view">
        <button
          aria-pressed={mode === "inheritance"}
          onClick={() => onMode("inheritance")}
        >
          Method lineage
        </button>
        <button aria-pressed={mode === "all"} onClick={() => onMode("all")}>
          All connections
        </button>
        <button
          aria-pressed={mode === "citation"}
          onClick={() => onMode("citation")}
        >
          Citations only
        </button>
      </div>
      <div className="view-actions">
        <button
          className="icon-button"
          aria-label="Zoom out"
          onClick={() => onZoom(1 / 1.2)}
        >
          −
        </button>
        <span className="zoom-label">{Math.round(zoom * 100)}%</span>
        <button
          className="icon-button"
          aria-label="Zoom in"
          onClick={() => onZoom(1.2)}
        >
          +
        </button>
        <button onClick={onReset}>Reset view</button>
        {selected && (
          <button onClick={onClear}>
            Clear selection <span aria-hidden="true">×</span>
          </button>
        )}
      </div>
    </div>
  );
}
