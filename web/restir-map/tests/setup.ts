import { afterEach, beforeEach } from "vitest";
import { cleanup } from "@testing-library/react";
beforeEach(() => {
  window.history.replaceState(null, "", "/restir-lab/");
});
afterEach(() => {
  cleanup();
  window.history.replaceState(null, "", "/restir-lab/");
});
