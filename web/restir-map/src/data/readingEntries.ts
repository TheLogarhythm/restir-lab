import type { PaperRole, ResearchDirection } from "./types";

// Editorial reading entry points, not graph roots or quality rankings.
// Rationale and update rules live in web/restir-map/README.md.
export const readingEntries: {
  direction: Record<ResearchDirection, string>;
  role: Record<PaperRole, string>;
} = {
  direction: {
    foundations: "restir_di2020",
    reuse_quality: "production2021",
    camera_dynamics: "area2024",
    transport: "restir_gi2021",
    estimators: "inverse2023",
    supporting: "course2023",
  },
  role: {
    mainline: "restir_di2020",
    branch: "volume2021",
    optimization: "production2021",
    resource: "course2023",
  },
};
