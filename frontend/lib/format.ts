/**
 * Presentation-only formatting for backend-provided Decimal strings.
 *
 * These functions never parse into `number` for anything except adding
 * thousands separators to digits the backend already rounded — they
 * never recompute, re-round to a different precision, or derive a new
 * financial value. See FINANCIAL_RULES.md, "Precision", and
 * ARCHITECTURE.md, "no P/L, allocation, or rebalancing math is computed
 * in React."
 */
import type { DecimalStr } from "@/types/api";

/** Inserts thousands separators into a Decimal string's integer part
 * without ever round-tripping the value through a binary float. */
function groupDigits(value: DecimalStr): string {
  const negative = value.startsWith("-");
  const unsigned = negative ? value.slice(1) : value;
  const [intPart, fracPart] = unsigned.split(".");
  const grouped = intPart.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const withFraction = fracPart !== undefined ? `${grouped}.${fracPart}` : grouped;
  return negative ? `-${withFraction}` : withFraction;
}

/** Formats a currency Decimal string, e.g. "12345.6" -> "12,345.60 EGP". */
export function formatCurrency(value: DecimalStr | null | undefined, currency?: string): string {
  if (value === null || value === undefined) return "—";
  const [intPart, fracPart = ""] = value.split(".");
  const padded = `${intPart}.${fracPart.padEnd(2, "0").slice(0, Math.max(2, fracPart.length))}`;
  const grouped = groupDigits(padded);
  return currency ? `${grouped} ${currency}` : grouped;
}

/** Formats a percent Decimal string, e.g. "54.0500" -> "54.05%". */
export function formatPercent(value: DecimalStr | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `${groupDigits(value)}%`;
}

/** Formats a plain quantity/number Decimal string with grouping, no unit. */
export function formatNumber(value: DecimalStr | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return groupDigits(value);
}

/** True when a Decimal string represents a value < 0 — for choosing a
 * positive/negative/neutral visual treatment without parsing the value
 * for arithmetic. */
export function isNegative(value: DecimalStr | null | undefined): boolean {
  if (!value) return false;
  return value.trim().startsWith("-");
}

export function isZero(value: DecimalStr | null | undefined): boolean {
  if (!value) return false;
  return /^-?0(\.0+)?$/.test(value.trim());
}

const DATE_FORMATTER = new Intl.DateTimeFormat("ar-EG-u-nu-latn", {
  year: "numeric",
  month: "short",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return DATE_FORMATTER.format(new Date(iso));
  } catch {
    return iso;
  }
}
