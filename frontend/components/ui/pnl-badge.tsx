import { formatPercent, formatSignedCurrency, isNegative, isZero } from "@/lib/format";
import type { DecimalStr } from "@/types/api";

/** Phase 16: a profit/loss figure must communicate its direction and
 * meaning without relying on color alone (see FINANCIAL_RULES.md, "P/L
 * Presentation Is Never Color-Only") — every render includes an
 * explicit arrow, a signed amount, and a plain-language label. Color is
 * still applied as a secondary reinforcement, never the only signal. */
export function PnLBadge({
  value,
  percent,
  currency,
  kind = "unrealized",
  className = "",
}: {
  value: DecimalStr | null;
  percent?: DecimalStr | null;
  currency?: string;
  kind?: "unrealized" | "realized";
  className?: string;
}) {
  if (value === null) {
    return <span className={`text-xs text-muted-foreground ${className}`}>غير متاح</span>;
  }

  const negative = isNegative(value);
  const zero = isZero(value);
  const arrow = zero ? "→" : negative ? "↓" : "↑";
  const tone = zero ? "text-muted-foreground" : negative ? "text-danger" : "text-success";
  const meaning = zero
    ? "بدون تغيير"
    : kind === "realized"
      ? negative
        ? "خسارة محققة"
        : "ربح محقق"
      : negative
        ? "خسارة غير محققة"
        : "ربح غير محقق";

  return (
    <span className={`tabular-nums inline-flex items-center gap-1 text-xs font-semibold ${tone} ${className}`}>
      <span aria-hidden="true">{arrow}</span>
      <span>
        {formatSignedCurrency(value, currency)}
        {percent !== null && percent !== undefined ? ` (${formatPercent(percent)})` : ""}
      </span>
      <span className="font-normal text-muted-foreground">— {meaning}</span>
    </span>
  );
}
