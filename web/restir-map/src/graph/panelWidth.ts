export function detailsPanelWidth(viewportWidth: number, sidebarWidth: number): number | null {
  if (viewportWidth <= 1000) return null;
  return sidebarWidth;
}
