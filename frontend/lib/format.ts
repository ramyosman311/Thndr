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

/** Rounds a Decimal string to exactly `decimals` fractional digits,
 * half-up, using plain digit arithmetic — never `Number`/`parseFloat`,
 * so a value with more precision than the display wants (e.g. a raw
 * `average_cost` or `current_price` carrying 8 decimal places) is never
 * round-tripped through a binary float to get there (see
 * FINANCIAL_RULES.md, "Precision"). The backend's own stored precision
 * is never touched — this only affects what this one render shows. */
function roundDecimalString(value: DecimalStr, decimals: number): string {
  const negative = value.startsWith("-");
  const unsigned = negative ? value.slice(1) : value;
  const [intPart, fracPart = ""] = unsigned.split(".");

  let digits: string;
  let pointFromEnd: number;
  if (fracPart.length <= decimals) {
    digits = intPart + fracPart.padEnd(decimals, "0");
    pointFromEnd = decimals;
  } else {
    const kept = fracPart.slice(0, decimals);
    const roundUp = Number(fracPart[decimals]) >= 5;
    const rawDigits = (intPart + kept).split("");
    if (roundUp) {
      let i = rawDigits.length - 1;
      while (i >= 0) {
        if (rawDigits[i] === "9") {
          rawDigits[i] = "0";
          i -= 1;
        } else {
          rawDigits[i] = String(Number(rawDigits[i]) + 1);
          break;
        }
      }
      if (i < 0) rawDigits.unshift("1");
    }
    digits = rawDigits.join("");
    pointFromEnd = decimals;
  }

  const intLen = digits.length - pointFromEnd;
  const newIntPart = (intLen > 0 ? digits.slice(0, intLen) : "0").replace(/^0+(?=\d)/, "");
  const newFracPart = pointFromEnd > 0 ? digits.slice(intLen < 0 ? 0 : intLen).padStart(pointFromEnd, "0") : "";
  const magnitude = pointFromEnd > 0 ? `${newIntPart}.${newFracPart}` : newIntPart;
  const isZero = /^0+(\.0+)?$/.test(magnitude);
  return negative && !isZero ? `-${magnitude}` : magnitude;
}

/** Formats a currency Decimal string as exactly 2 decimal places, e.g.
 * "12345.6" -> "12,345.60 EGP", "12345.678" -> "12,345.68 EGP". Rounds
 * (half-up), never truncates or pads past 2dp, regardless of how much
 * precision the backend value carries — the backend's own stored value
 * is untouched, this is a display-only rounding. */
export function formatCurrency(value: DecimalStr | null | undefined, currency?: string): string {
  if (value === null || value === undefined) return "—";
  const grouped = groupDigits(roundDecimalString(value, 2));
  return currency ? `${grouped} ${currency}` : grouped;
}

/** Like `formatCurrency`, but prepends an explicit "+" for a positive
 * value (a negative value already carries its own "-", and this never
 * adds a sign to exactly zero) — used wherever a profit/loss figure must
 * communicate its direction through more than color alone (Phase 16, see
 * components/ui/pnl-badge.tsx and FINANCIAL_RULES.md, "P/L Presentation
 * Is Never Color-Only"). */
export function formatSignedCurrency(value: DecimalStr | null | undefined, currency?: string): string {
  if (value === null || value === undefined) return "—";
  const formatted = formatCurrency(value, currency);
  return isNegative(value) || isZero(value) ? formatted : `+${formatted}`;
}

/** Formats a percent Decimal string, e.g. "54.0500" -> "54.05%". */
export function formatPercent(value: DecimalStr | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `${groupDigits(value)}%`;
}

/** Formats a quantity Decimal string with grouping, no unit — trims
 * trailing fractional zeros so a mathematically integral quantity shows
 * as "50", never "50.00000000", while a genuinely fractional quantity
 * still shows only as much precision as it actually carries (e.g.
 * "0.50000000" -> "0.5"). Never rounds away real fractional precision —
 * only removes trailing zeros already present in the backend's own
 * string. */
export function formatNumber(value: DecimalStr | null | undefined): string {
  if (value === null || value === undefined) return "—";
  const negative = value.startsWith("-");
  const unsigned = negative ? value.slice(1) : value;
  const [intPart, fracPart = ""] = unsigned.split(".");
  const trimmedFrac = fracPart.replace(/0+$/, "");
  const trimmed = trimmedFrac ? `${intPart}.${trimmedFrac}` : intPart;
  return groupDigits(negative ? `-${trimmed}` : trimmed);
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

const RELATIVE_TIME_FORMATTER = new Intl.RelativeTimeFormat("ar-EG-u-nu-latn", { numeric: "auto" });

/** Formats a timestamp as "X ago" for the price-state UI (Phase 11) —
 * e.g. "قبل 5 دقائق". Never used to decide freshness itself: the
 * backend's `is_stale` flag is the only source of truth for that (see
 * FINANCIAL_RULES.md, "Stale Price Policy") — this only renders the
 * age the backend already computed. */
export function formatRelativeTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "—";
  const diffSeconds = Math.round((then - Date.now()) / 1000);
  const absSeconds = Math.abs(diffSeconds);

  if (absSeconds < 60) return RELATIVE_TIME_FORMATTER.format(diffSeconds, "second");
  const diffMinutes = Math.round(diffSeconds / 60);
  if (absSeconds < 3600) return RELATIVE_TIME_FORMATTER.format(diffMinutes, "minute");
  const diffHours = Math.round(diffSeconds / 3600);
  if (absSeconds < 86400) return RELATIVE_TIME_FORMATTER.format(diffHours, "hour");
  const diffDays = Math.round(diffSeconds / 86400);
  return RELATIVE_TIME_FORMATTER.format(diffDays, "day");
}
