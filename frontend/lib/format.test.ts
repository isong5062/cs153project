import { describe, expect, it } from "vitest";

import { classifyHealth, fmtPct, regimeColor, statusColor } from "./format";

describe("classifyHealth", () => {
  it("maps 'ok' to healthy", () => expect(classifyHealth("ok")).toBe("healthy"));
  it("maps anything else to down", () => expect(classifyHealth("x")).toBe("down"));
});

describe("fmtPct", () => {
  it("formats a fraction as a percent", () => expect(fmtPct(0.1234)).toBe("12.34%"));
  it("handles null", () => expect(fmtPct(null)).toBe("–"));
});

describe("regimeColor", () => {
  it("colors known regimes", () => expect(regimeColor("bull")).toContain("emerald"));
  it("falls back for unknown", () => expect(regimeColor("???")).toContain("zinc"));
});

describe("statusColor", () => {
  it("colors live", () => expect(statusColor("live")).toContain("emerald"));
});
