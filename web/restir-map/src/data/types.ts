export type PublicationStatus =
  | "published"
  | "preprint"
  | "course"
  | "book_chapter"
  | "abstract"
  | "technical_report"
  | "talk"
  | "unverified";
export type Paper = {
  paper_id: string;
  title: string;
  short_title: string;
  authors: string[];
  year: number;
  venue: string;
  publication_status: PublicationStatus;
  doi: string | null;
  tags: string[];
  role: "mainline" | "branch" | "optimization" | "resource";
  problem: string;
  contributions: string[];
  changes: string;
  limitations: string[];
  links: { paper: string; pdf: string | null; code: string | null };
  sources: { url: string; kind: string; checked: string; note: string }[];
  verification: {
    metadata: "verified" | "partial";
    content: "full_text" | "abstract_only";
    notes: string;
  };
  pdf: {
    status: string;
    local_file: string | null;
    sha256: string | null;
    version: string;
    source_url: string | null;
  };
};
export type Relation = {
  id: string;
  predecessor: string;
  successor: string;
  type: "citation" | "inheritance";
  citing_paper: string;
  cited_paper: string;
  verification: "verified" | "pending";
  evidence: {
    source_url: string;
    locator: string;
    explanation: string;
    quote?: string;
    checked: string;
    method: string;
  }[];
};
export type EdgeMode = "inheritance" | "all" | "citation";
export type GraphEdge = {
  id: string;
  source: string;
  target: string;
  type: "citation" | "inheritance";
  relations: Relation[];
};
export type Filters = {
  query: string;
  tag: string;
  year: string;
  status: string;
};
export type Point = { x: number; y: number };
export type View = { x: number; y: number; scale: number };

export type PaperFigure = {
  id: string;
  src: string;
  alt: string;
  caption: string;
  source_url: string;
  source_locator: string;
  credit: string;
  source_kind: "paper_figure" | "project_teaser";
  sha256: string;
  width: number;
  height: number;
};
export type PaperFigureRecord = {
  paper_id: string;
  status: "available" | "unavailable";
  reason?: string;
  images: PaperFigure[];
};
