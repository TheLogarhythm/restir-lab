import { useEffect, useRef } from "react";
import type { Filters, Paper } from "../data/types";
import { colorFor, directions, roleNames, statusNames } from "../data/labels";

export function PaperList({
  papers,
  allPapers,
  filters,
  onFilters,
  selected,
  hovered,
  onSelect,
  onHover,
  highlightedIds,
}: {
  highlightedIds: Set<string> | null;
  papers: Paper[];
  allPapers: Paper[];
  filters: Filters;
  onFilters: (filters: Filters) => void;
  selected: string | null;
  hovered: string | null;
  onSelect: (id: string) => void;
  onHover: (id: string | null) => void;
}) {
  const selectedRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    const item = selectedRef.current;
    const list = item?.closest(".paper-list");
    if (!item || !list) return;
    // Keep the selected row visible inside the list without scrolling the page
    // away from the map on stacked layouts.
    const row = item.getBoundingClientRect(), box = list.getBoundingClientRect();
    if (row.top < box.top) list.scrollTop += row.top - box.top;
    else if (row.bottom > box.bottom) list.scrollTop += row.bottom - box.bottom;
    if (row.left < box.left) list.scrollLeft += row.left - box.left;
    else if (row.right > box.right) list.scrollLeft += row.right - box.right;
  }, [selected, papers]);
  const years = [...new Set(allPapers.map((p) => p.year))].sort(
    (a, b) => b - a,
  );
  const update = (key: keyof Filters, value: string) =>
    onFilters({ ...filters, [key]: value });
  const filtered =
    filters.query ||
    filters.tag !== "all" ||
    filters.year !== "all" ||
    filters.status !== "all";
  return (
    <aside className="paper-sidebar" aria-label="Paper collection">
      <div className="search-and-filters">
        <label className="search-box">
          <svg aria-hidden="true" viewBox="0 0 24 24">
            <circle cx="10" cy="10" r="6.5" />
            <path d="m15 15 5 5" />
          </svg>
          <input
            type="search"
            aria-label="Search papers"
            placeholder="Search titles, authors or keywords"
            value={filters.query}
            onChange={(e) => update("query", e.target.value)}
          />
          <kbd>/</kbd>
        </label>
        <label className="select-label">
          <span className="sr-only">Research area</span>
          <select
            aria-label="Research area"
            value={filters.tag}
            onChange={(e) => update("tag", e.target.value)}
          >
            <option value="all">All research areas</option>
            {Object.entries(directions).map(([id, d]) => (
              <option key={id} value={id}>
                {d.label}
              </option>
            ))}
          </select>
        </label>
        <div className="filter-row">
          <select
            aria-label="Publication year"
            value={filters.year}
            onChange={(e) => update("year", e.target.value)}
          >
            <option value="all">All years</option>
            {years.map((year) => (
              <option key={year} value={year}>
                {year}
              </option>
            ))}
          </select>
          <select
            aria-label="Publication type"
            value={filters.status}
            onChange={(e) => update("status", e.target.value)}
          >
            <option value="all">All types</option>
            {Object.entries(statusNames).map(([id, label]) => (
              <option key={id} value={id}>
                {label}
              </option>
            ))}
          </select>
        </div>
      </div>
      <div className="list-meta">
        <span aria-live="polite">{papers.length} {papers.length === 1 ? "result" : "results"} · oldest first</span>
        {filtered && (
          <button
            onClick={() =>
              onFilters({ query: "", tag: "all", year: "all", status: "all" })
            }
          >
            Clear filters
          </button>
        )}
      </div>
      <ol className="paper-list">
        {papers.map((paper, index) => (
          <li key={paper.paper_id}>
            <button
              ref={selected === paper.paper_id ? selectedRef : undefined}
              data-paper-id={paper.paper_id}
              aria-pressed={selected === paper.paper_id}
              className={`paper-item ${highlightedIds ? highlightedIds.has(paper.paper_id) ? "legend-match" : "legend-dimmed" : ""} ${selected === paper.paper_id ? "selected" : ""} ${hovered === paper.paper_id ? "hovered" : ""}`}
              onClick={() => onSelect(paper.paper_id)}
              onMouseEnter={() => onHover(paper.paper_id)}
              onMouseLeave={() => onHover(null)}
              onFocus={() => onHover(paper.paper_id)}
              onBlur={() => onHover(null)}
              style={
                { "--direction": colorFor(paper.tags) } as React.CSSProperties
              }
            >
              <span className="item-number">
                {String(index + 1).padStart(2, "0")}
              </span>
              <span className="item-content">
                <span className="item-title">{paper.short_title}</span>
                <span className="item-full-title">{paper.title}</span>
                <span className="item-meta">
                  <span>{paper.year}</span>
                  <span className="direction-dot" />
                  {directions[paper.tags[0]]?.label}
                  <span className="item-role">{roleNames[paper.role]}</span>
                </span>
                {paper.publication_status !== "published" && (
                  <span className="resource-label">
                    {statusNames[paper.publication_status]}
                  </span>
                )}
              </span>
            </button>
          </li>
        ))}
      </ol>
      {!papers.length && (
        <div className="empty-list">
          <strong>No matching papers</strong>
          <p>Try a short title, an author’s name or fewer filters.</p>
        </div>
      )}
    </aside>
  );
}
