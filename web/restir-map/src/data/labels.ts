export const directions: Record<string, { label: string; color: string }> = {
  foundations: { label: "Foundations", color: "#35776d" },
  reuse_quality: { label: "Reuse quality", color: "#b17935" },
  camera_dynamics: { label: "Cameras & motion", color: "#5c83a2" },
  transport: { label: "Light transport", color: "#987198" },
  estimators: { label: "Estimator extensions", color: "#a66459" },
  supporting: { label: "Learning & implementation", color: "#7f8586" },
};
export const roleNames = {
  mainline: "Mainline",
  branch: "Branch",
  optimization: "Optimization",
  resource: "Resource",
};
export const statusNames = {
  published: "Published",
  preprint: "Preprint",
  course: "Course",
  book_chapter: "Book chapter",
  abstract: "Abstract / short contribution",
  technical_report: "Technical report",
  talk: "Conference talk",
  unverified: "Publication unverified",
};
export const colorFor = (tags: string[]) =>
  directions[tags[0]]?.color ?? "#7f8586";

const graphLabels: Record<string, string> = {
  conditional2023: "Conditional RIS",
  production2021: "Production ReSTIR",
  inverse2023: "Inverse ReSTIR",
  parameter2023: "Parameter ReSTIR",
  shape_splatting2024: "Shape Splatting",
  world_space2021: "World-space ReSTIR",
  multilayer2026: "Multi-layer Splatting",
};
export function graphLabelLines(paper: {paper_id: string; short_title: string}): string[] {
  const words = (graphLabels[paper.paper_id] || paper.short_title).split(" ");
  const lines = [""];
  for (const word of words) {
    const last = lines.length - 1;
    if (lines[last] && (lines[last] + " " + word).length > 17) lines.push(word);
    else lines[last] += (lines[last] ? " " : "") + word;
  }
  return lines;
}
