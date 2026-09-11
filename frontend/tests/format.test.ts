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

  it("rounds (half-up) to exactly 2 decimal places when the backend value carries more precision", () => {
    // Phase 16: prices/average_cost can carry up to 8 decimal places —
    // display must never show more than 2, and must round rather than
    // truncate, without ever parsing through a binary float.
    expect(formatCurrency("12345.678")).toBe("12,345.68");
    expect(formatCurrency("100.005")).toBe("100.01");
    expect(formatCurrency("1.00000000")).toBe("1.00");
    expect(formatCurrency("0.999")).toBe("1.00");
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

  it("shows a mathematically integral quantity with no decimal places (Phase 16)", () => {
    expect(formatNumber("50.00000000")).toBe("50");
    expect(formatNumber("20")).toBe("20");
  });

  it("trims trailing zeros from a fractional quantity without rounding away real precision", () => {
    expect(formatNumber("0.50000000")).toBe("0.5");
    expect(formatNumber("1.23400000")).toBe("1.234");
    expect(formatNumber("-3.10000000")).toBe("-3.1");
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
