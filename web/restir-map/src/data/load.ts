import paperData from "../../../../docs/literature/restir-map/papers.json";
import relationData from "../../../../docs/literature/restir-map/relations.json";
import figureData from "../../../../docs/literature/restir-map/figures.json";
import type { Paper, PaperFigureRecord, Relation } from "./types";
export const papers = paperData.papers as Paper[];
export const relations = relationData.relations as Relation[];
export const cutoffDate = paperData.cutoff_date;
export const figureRecords: Record<string, PaperFigureRecord> = Object.fromEntries(
  (figureData.records as PaperFigureRecord[]).map(record => [record.paper_id, record]),
);
