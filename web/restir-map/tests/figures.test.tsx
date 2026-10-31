import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { PaperFigures } from "../src/components/PaperFigures";
import type { PaperFigureRecord } from "../src/data/types";

const record: PaperFigureRecord = {
  paper_id: "example",
  status: "available",
  images: [{
    id: "example-fig1", src: "figures/example-fig1.webp",
    alt: "Reservoirs reuse samples across neighboring pixels.",
    caption: "Spatial reuse in the sampling pipeline.",
    source_url: "https://example.org/paper.pdf", source_locator: "Figure 2, p. 3",
    credit: "Figure © the authors", source_kind: "paper_figure",
    sha256: "a".repeat(64), width: 1200, height: 600,
  }],
};

describe("paper figures", () => {
  afterEach(() => vi.unstubAllEnvs());
  it("loads from the Pages subpath and opens an accessible enlarged view with attribution", async () => {
    vi.stubEnv("BASE_URL", "/restir-lab/");
    const user = userEvent.setup();
    render(<PaperFigures title="Example paper" record={record} />);
    const image = screen.getByRole("img", { name: record.images[0].alt });
    expect(image.getAttribute("src")).toBe("/restir-lab/figures/example-fig1.webp");
    const trigger = screen.getByRole("button", { name: "Enlarge image 1 for Example paper" });
    await user.click(trigger);
    const dialog = screen.getByRole("dialog", { name: "Example paper — Image 1" });
    expect(within(dialog).getByRole("link", { name: /Figure 2, p. 3/ }).getAttribute("href"))
      .toBe("https://example.org/paper.pdf");
    expect(within(dialog).getByText(record.images[0].credit)).toBeTruthy();
    await user.keyboard("/");
    expect(dialog.contains(document.activeElement)).toBe(true);
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });

  it("states when no source figure is available without showing an invented image", () => {
    render(<PaperFigures title="Example paper" record={{ paper_id: "example", status: "unavailable", images: [], reason: "No accessible source figure was found." }} />);
    expect(screen.queryByRole("img")).toBeNull();
    expect(screen.getByText("No accessible source figure was found.")).toBeTruthy();
  });

  it("keeps a usable source link if a local figure fails to load", () => {
    render(<PaperFigures title="Example paper" record={record} />);
    fireEvent.error(screen.getByRole("img"));
    expect(screen.queryByRole("img")).toBeNull();
    expect(screen.getByRole("link", { name: "View figure at source ↗" }).getAttribute("href"))
      .toBe("https://example.org/paper.pdf");
  });
});
