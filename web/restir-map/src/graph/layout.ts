import savedLayout from "./layout.json";
import type { Paper, Point, View } from "../data/types";
import { graphLabelLines } from "../data/labels";

// Low zoom keeps readable labels instead of shrinking them into overlapping text.
// This affects presentation only: every node remains visible and keyboard accessible.
export function visibleLabelIds(papers: Paper[], positions: Record<string, Point>, scale: number, active: string | null): Set<string> {
  if (scale >= 0.46) return new Set(papers.map(p => p.paper_id));
  const priority = (p: Paper) => p.paper_id === active ? 0 : p.role === "mainline" ? 1 : 2;
  const ordered = [...papers].sort((a, b) => priority(a) - priority(b));
  const occupied: {left: number; right: number; top: number; bottom: number}[] = [];
  const visible = new Set<string>();
  for (const paper of ordered) {
    const point = positions[paper.paper_id];
    if (!point) continue;
    const lines = graphLabelLines(paper), font = Math.max(12 * scale, 11.5);
    const width = Math.max(...lines.map(line => line.length)) * font * 0.64 + 8;
    const box = {left: point.x * scale - width / 2, right: point.x * scale + width / 2,
      top: point.y * scale + 40 * scale - font - 3,
      bottom: point.y * scale + 43 * scale + lines.length * font * 1.15 + 5};
    if (occupied.some(b => box.left < b.right && box.right > b.left && box.top < b.bottom && box.bottom > b.top)) continue;
    occupied.push(box);
    visible.add(paper.paper_id);
  }
  return visible;
}
export function initialLayout(papers: Paper[]): Record<string, Point> {
  const saved: Record<string, Point> = savedLayout;
  return Object.fromEntries(
    papers.map((paper, index) => [
      paper.paper_id,
      saved[paper.paper_id] ?? {
        x: 150 + (index % 7) * 170,
        y: 130 + Math.floor(index / 7) * 150,
      },
    ]),
  );
}
export function fitView(
  positions: Record<string, Point>,
  width: number,
  height: number,
): View {
  const points = Object.values(positions);
  if (!points.length || !width || !height) return { x: 0, y: 0, scale: 1 };
  const minX = Math.min(...points.map((p) => p.x)) - 85,
    maxX = Math.max(...points.map((p) => p.x)) + 85;
  const minY = Math.min(...points.map((p) => p.y)) - 50,
    maxY = Math.max(...points.map((p) => p.y)) + 70;
  const scale =
    Math.min(
      Math.min(width / (maxX - minX), height / (maxY - minY), 1.5) * 0.92,
      // Labels keep a minimum readable screen size, so their margin must too.
      (width - 2 * Math.min(70, width * 0.2)) / Math.max(1, maxX - minX - 170),
      (height - 2 * Math.min(50, height * 0.15)) / Math.max(1, maxY - minY - 120),
    );
  return {
    scale,
    x: width / 2 - ((minX + maxX) / 2) * scale,
    y: height / 2 - ((minY + maxY) / 2) * scale,
  };
}
export function zoomAt(view: View, factor: number, point: Point): View {
  // A fitted overview may already be below the usual interaction floor.
  // Zooming out must never jump upward to that floor.
  const scale = Math.max(Math.min(0.08, view.scale), Math.min(2.6, view.scale * factor));
  const ratio = scale / view.scale;
  return {
    scale,
    x: point.x - (point.x - view.x) * ratio,
    y: point.y - (point.y - view.y) * ratio,
  };
}
export function edgePath(from: Point, to: Point): string {
  const dx = to.x - from.x,
    dy = to.y - from.y,
    length = Math.hypot(dx, dy) || 1;
  const ax = from.x + (dx / length) * 21,
    ay = from.y + (dy / length) * 21;
  const bx = to.x - (dx / length) * 25,
    by = to.y - (dy / length) * 25;
  const curve = Math.min(length * 0.1, 28);
  return `M ${ax} ${ay} Q ${(ax + bx) / 2 - (dy / length) * curve} ${(ay + by) / 2 + (dx / length) * curve} ${bx} ${by}`;
}
