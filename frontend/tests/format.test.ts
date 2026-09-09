import { describe, expect, it } from "vitest";
import { formatCurrency, formatNumber, formatPercent, isNegative, isZero } from "@/lib/format";

describe("formatCurrency", () => {
  it("groups thousands and appends the currency code", () => {
    expect(formatCurrency("12345.6", "EGP")).toBe("12,345.60 EGP");
  });

  it("returns an em-dash for null/undefined instead of fabricating a value", () => {
    expect(formatCurrency(null)).toBe("—");
    expect(formatCurrency(undefined)).toBe("—");
  });

  it("preserves a negative sign", () => {
    expect(formatCurrency("-500", "EGP")).toBe("-500.00 EGP");
  });
});

describe("formatPercent", () => {
  it("appends a percent sign without altering the backend's digits", () => {
    expect(formatPercent("54.05")).toBe("54.05%");
  });

  it("returns an em-dash for null rather than 0%", () => {
    expect(formatPercent(null)).toBe("—");
  });
});

describe("formatNumber", () => {
  it("groups a large quantity", () => {
    expect(formatNumber("1234567.89012345")).toBe("1,234,567.89012345");
  });
});

describe("isNegative / isZero", () => {
  it("detects negative values without parsing to float", () => {
    expect(isNegative("-1.00")).toBe(true);
    expect(isNegative("1.00")).toBe(false);
    expect(isNegative(null)).toBe(false);
  });

  it("detects zero in various representations", () => {
    expect(isZero("0")).toBe(true);
    expect(isZero("0.00")).toBe(true);
    expect(isZero("-0.00")).toBe(true);
    expect(isZero("0.01")).toBe(false);
  });
});
