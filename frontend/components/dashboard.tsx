"use client";

import Link from "next/link";
import { useState } from "react";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { MetricCard } from "@/components/ui/metric-card";
import { StatusPill } from "@/components/ui/status-pill";
import { EmptyBlock, QueryBoundary } from "@/components/ui/query-boundary";
import { ForwardChevronIcon, BellIcon, CashIcon, CheckCircleIcon, WalletIcon } from "@/components/icons";
import { useApiQuery } from "@/hooks/use-api-query";
import { api } from "@/lib/api";
import { formatCurrency, formatPercent, isNegative, isZero } from "@/lib/format";
import { strategyStatusMeta } from "@/lib/status-labels";
import type {
  AnalyticsRange,
  PortfolioAllocationOut,
  PortfolioAnalyticsHistoryOut,
  PortfolioSummaryOut,
  StrategyValidationOut,
  WatchlistOut,
} from "@/types/api";

export function TotalValueCard({ summary }: { summary: PortfolioSummaryOut }) {
  const pnlNegative = isNegative(summary.total_unrealized_pnl);
  const pnlZero = isZero(summary.total_unrealized_pnl);
  const tone = pnlZero ? "neutral" : pnlNegative ? "danger" : "success";
  return (
    <Card>
      <CardBody className="p-5">
        <p className="text-xs font-medium text-muted-foreground">إجمالي قيمة المحفظة</p>
        <p className="tabular-nums mt-1 text-3xl font-extrabold text-foreground">
          {formatCurrency(summary.total_value, summary.base_currency)}
        </p>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <span
            className={`tabular-nums inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-semibold ${
              tone === "success"
                ? "bg-success-muted text-success"
                : tone === "danger"
                  ? "bg-danger-muted text-danger"
                  : "bg-muted text-muted-foreground"
            }`}
          >
            {formatCurrency(summary.total_unrealized_pnl, summary.base_currency)}
            {summary.total_unrealized_pnl_percent !== null
              ? ` (${formatPercent(summary.total_unrealized_pnl_percent)})`
              : ""}
          </span>
          <span className="text-[11px] text-muted-foreground">ربح/خسارة غير محققة</span>
        </div>
        {summary.total_unrealized_pnl_percent === null ? (
          <p className="mt-1 text-[11px] text-muted-foreground">
            النسبة غير محسوبة — لا توجد تكلفة شراء مسجّلة بعد لهذه المراكز.
          </p>
        ) : null}
      </CardBody>
    </Card>
  );
}

export function ValueSplitCard({ summary }: { summary: PortfolioSummaryOut }) {
  return (
    <div className="grid grid-cols-2 gap-3">
      <MetricCard
        label="القيمة القابلة للاستثمار"
        value={formatCurrency(summary.investable_value, summary.base_currency)}
        hint={summary.emergency_excluded ? "أساس الحساب المستخدم في التوزيع" : undefined}
        icon={<WalletIcon width={16} height={16} />}
      />
      <MetricCard
        label="النقد الاحتياطي"
        value={formatCurrency(summary.emergency_value, summary.base_currency)}
        hint={summary.emergency_excluded ? "مستبعد من حسابات التوزيع" : "غير مستبعد من التوزيع"}
        icon={<CashIcon width={16} height={16} />}
      />
    </div>
  );
}

export function StrategyBanner({ validation }: { validation: StrategyValidationOut }) {
  const meta = strategyStatusMeta(validation.status);
  return (
    <Card>
      <CardHeader
        title="حالة الاستراتيجية"
        action={<StatusPill label={meta.label} tone={meta.tone} />}
      />
      <CardBody>
        <p className="text-sm text-muted-foreground">{validation.explanation}</p>
        <div className="mt-3 flex items-center justify-between text-xs text-muted-foreground">
          <span>
            إجمالي نسب الاستهداف:{" "}
            <span className="tabular-nums font-semibold text-foreground">
              {formatPercent(validation.total_target_percent)}
            </span>{" "}
            من {formatPercent(validation.expected_target_percent)}
          </span>
          <Link href="/allocation" className="inline-flex items-center gap-1 font-medium text-primary">
            التفاصيل
            <ForwardChevronIcon width={14} height={14} />
          </Link>
        </div>
      </CardBody>
    </Card>
  );
}

export function AllocationHealthCard({ allocation }: { allocation: PortfolioAllocationOut }) {
  const breached = allocation.buckets.filter((b) => b.maximum_status === "MAXIMUM_BREACHED").length;
  const overweight = allocation.buckets.filter((b) => b.target_status === "OVERWEIGHT").length;
  const healthy = allocation.buckets.filter(
    (b) => b.target_status === "ON_TARGET" && b.maximum_status !== "MAXIMUM_BREACHED"
  ).length;

  return (
    <Card>
      <CardHeader
        title="صحة التوزيع"
        subtitle={`${allocation.buckets.length} فئة استراتيجية مُهيّأة`}
        action={
          <Link href="/allocation" className="inline-flex items-center gap-1 text-xs font-medium text-primary">
            عرض الكل
            <ForwardChevronIcon width={12} height={12} />
          </Link>
        }
      />
      <CardBody>
        <div className="grid grid-cols-3 gap-2 text-center">
          <div className="rounded-xl bg-success-muted p-2.5">
            <p className="tabular-nums text-lg font-bold text-success">{healthy}</p>
            <p className="text-[11px] text-success">عند الهدف</p>
          </div>
          <div className="rounded-xl bg-warning-muted p-2.5">
            <p className="tabular-nums text-lg font-bold text-warning">{overweight}</p>
            <p className="text-[11px] text-warning">أعلى من الهدف</p>
          </div>
          <div className="rounded-xl bg-danger-muted p-2.5">
            <p className="tabular-nums text-lg font-bold text-danger">{breached}</p>
            <p className="text-[11px] text-danger">تجاوز الحد الأقصى</p>
          </div>
        </div>
      </CardBody>
    </Card>
  );
}

export function WatchlistSummaryCard({ watchlist }: { watchlist: WatchlistOut[] }) {
  const active = watchlist.filter((w) => w.enabled);
  const withAlerts = active.filter((w) => w.alert_rule && w.alert_rule.enabled);
  return (
    <Card>
      <CardHeader
        title="المتابعة والتنبيهات"
        action={
          <Link href="/watchlist" className="inline-flex items-center gap-1 text-xs font-medium text-primary">
            فتح
            <ForwardChevronIcon width={12} height={12} />
          </Link>
        }
      />
      <CardBody>
        {active.length === 0 ? (
          <p className="flex items-center gap-2 text-sm text-muted-foreground">
            <BellIcon width={16} height={16} />
            لا توجد أصول قيد المتابعة حاليًا.
          </p>
        ) : (
          <p className="flex items-center gap-2 text-sm text-foreground">
            <CheckCircleIcon width={16} height={16} className="text-primary" />
            <span className="tabular-nums font-semibold">{active.length}</span> أصل قيد المتابعة، منها{" "}
            <span className="tabular-nums font-semibold">{withAlerts.length}</span> بتنبيهات مفعّلة
          </p>
        )}
      </CardBody>
    </Card>
  );
}

// --- Wealth History (Phase 15) ---------------------------------------------

const ANALYTICS_RANGES: AnalyticsRange[] = ["1W", "1M", "3M", "YTD", "ALL"];
const RANGE_LABELS: Record<AnalyticsRange, string> = {
  "1W": "أسبوع",
  "1M": "شهر",
  "3M": "3 أشهر",
  YTD: "منذ بداية العام",
  ALL: "الكل",
};

function RangeSwitcher({ value, onChange }: { value: AnalyticsRange; onChange: (range: AnalyticsRange) => void }) {
  return (
    <div className="flex gap-1 rounded-full bg-muted p-0.5" role="tablist" aria-label="النطاق الزمني">
      {ANALYTICS_RANGES.map((range) => (
        <button
          key={range}
          type="button"
          role="tab"
          aria-selected={value === range}
          onClick={() => onChange(range)}
          className={`rounded-full px-2.5 py-1 text-[11px] font-medium transition-colors ${
            value === range ? "bg-card text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
          }`}
        >
          {RANGE_LABELS[range]}
        </button>
      ))}
    </div>
  );
}

/** Real, persisted-snapshot-driven wealth chart (Phase 15). Never
 * fabricates, interpolates, or extrapolates a data point — every point on
 * the chart is exactly one point the backend returned, which in turn is
 * exactly one persisted `PortfolioSnapshot` row (see
 * services/portfolio_analytics_service.py). When fewer than two eligible
 * historical observations exist for the selected range, an explicit
 * "insufficient data" state is shown instead of an empty/misleading chart. */
export function WealthHistoryCard() {
  const [range, setRange] = useState<AnalyticsRange>("1M");
  const query = useApiQuery(() => api.portfolioAnalyticsHistory(range), [range]);

  return (
    <Card>
      <CardHeader
        title="نمو الثروة"
        subtitle="قيمة المحفظة مقابل رأس المال المستثمر عبر الزمن"
        action={<RangeSwitcher value={range} onChange={setRange} />}
      />
      <CardBody>
        <QueryBoundary state={query} onRetry={query.refetch} loadingLabel="جارٍ تحميل السجل التاريخي...">
          {(history) =>
            history.insufficient_history || history.data.length < 2 ? (
              <EmptyBlock
                title="لا تتوفر بيانات تاريخية كافية"
                body={
                  history.message ??
                  "أضف عمليات إيداع/سحب أو انتظر حتى تتوفر لقطات كافية للمحفظة ضمن هذا النطاق."
                }
              />
            ) : (
              <WealthLineChart history={history} />
            )
          }
        </QueryBoundary>
      </CardBody>
    </Card>
  );
}

function WealthLineChart({ history }: { history: PortfolioAnalyticsHistoryOut }) {
  const points = history.data;
  const width = 600;
  const height = 180;
  const paddingX = 8;
  const paddingY = 16;

  // Numeric parsing here is for SVG pixel geometry ONLY (chart layout is
  // not a financial calculation) — every value actually displayed to the
  // user (headline figure, tooltip, legend) always comes straight from
  // the backend's own formatted Decimal string via formatCurrency/
  // formatPercent, never from these parsed floats (see lib/format.ts's
  // module docstring, "never recompute... a new financial value").
  const portfolioValues = points.map((p) => Number(p.portfolio_value));
  const investedValues = points.map((p) => Number(p.invested_capital));
  const allValues = [...portfolioValues, ...investedValues];
  const minValue = Math.min(...allValues, 0);
  const maxValue = Math.max(...allValues, 1);
  const valueRange = maxValue - minValue || 1;

  const xFor = (index: number) =>
    points.length === 1 ? width / 2 : paddingX + (index / (points.length - 1)) * (width - paddingX * 2);
  const yFor = (value: number) => height - paddingY - ((value - minValue) / valueRange) * (height - paddingY * 2);

  const pathFor = (values: number[]) => values.map((v, i) => `${i === 0 ? "M" : "L"}${xFor(i)},${yFor(v)}`).join(" ");

  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const latest = points[points.length - 1];

  return (
    <div>
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
        <div>
          <p className="tabular-nums text-2xl font-extrabold text-foreground">
            {formatCurrency(latest.portfolio_value, history.base_currency)}
          </p>
          <p className="text-[11px] text-muted-foreground">القيمة الحالية</p>
        </div>
        {latest.twr_percentage !== null ? (
          <span
            className={`tabular-nums rounded-full px-2 py-0.5 text-xs font-semibold ${
              isNegative(latest.twr_percentage)
                ? "bg-danger-muted text-danger"
                : isZero(latest.twr_percentage)
                  ? "bg-muted text-muted-foreground"
                  : "bg-success-muted text-success"
            }`}
          >
            {formatPercent(latest.twr_percentage)} عائد حقيقي (TWR)
          </span>
        ) : (
          <span className="rounded-full bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground">
            العائد الحقيقي غير محسوب لهذا النطاق
          </span>
        )}
      </div>

      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="mt-3 w-full touch-none"
        role="img"
        aria-label="مخطط قيمة المحفظة ورأس المال المستثمر عبر الزمن"
        onMouseMove={(event) => {
          const rect = event.currentTarget.getBoundingClientRect();
          const relativeX = ((event.clientX - rect.left) / rect.width) * width;
          const index = Math.round(((relativeX - paddingX) / (width - paddingX * 2)) * (points.length - 1));
          setHoverIndex(Math.min(Math.max(index, 0), points.length - 1));
        }}
        onMouseLeave={() => setHoverIndex(null)}
      >
        <path
          d={pathFor(investedValues)}
          fill="none"
          stroke="var(--color-muted-foreground)"
          strokeWidth={2}
          strokeDasharray="4 3"
          strokeLinecap="round"
        />
        <path d={pathFor(portfolioValues)} fill="none" stroke="var(--color-primary)" strokeWidth={2} strokeLinecap="round" />
        {hoverIndex !== null ? (
          <>
            <line
              x1={xFor(hoverIndex)}
              x2={xFor(hoverIndex)}
              y1={0}
              y2={height}
              stroke="var(--color-border)"
              strokeWidth={1}
            />
            <circle cx={xFor(hoverIndex)} cy={yFor(portfolioValues[hoverIndex])} r={3.5} fill="var(--color-primary)" />
            <circle
              cx={xFor(hoverIndex)}
              cy={yFor(investedValues[hoverIndex])}
              r={3.5}
              fill="var(--color-muted-foreground)"
            />
          </>
        ) : null}
      </svg>

      {hoverIndex !== null ? (
        <div className="mt-2 rounded-lg border border-border bg-muted/50 p-2 text-xs">
          <p className="font-semibold text-foreground">{points[hoverIndex].date}</p>
          <p className="tabular-nums text-primary">
            قيمة المحفظة: {formatCurrency(points[hoverIndex].portfolio_value, history.base_currency)}
          </p>
          <p className="tabular-nums text-muted-foreground">
            رأس المال المستثمر: {formatCurrency(points[hoverIndex].invested_capital, history.base_currency)}
          </p>
          {points[hoverIndex].twr_percentage !== null ? (
            <p className="tabular-nums text-muted-foreground">
              العائد الحقيقي: {formatPercent(points[hoverIndex].twr_percentage)}
            </p>
          ) : null}
        </div>
      ) : null}

      <div className="mt-2 flex items-center gap-4 text-[11px] text-muted-foreground">
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block h-0.5 w-3 rounded-full bg-primary" />
          قيمة المحفظة
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block h-0.5 w-3 rounded-full border-t-2 border-dashed border-muted-foreground" />
          رأس المال المستثمر
        </span>
      </div>
    </div>
  );
}

export function InflowCtaCard() {
  return (
    <Link
      href="/inflow"
      className="flex items-center justify-between gap-3 rounded-2xl border border-primary/30 bg-accent p-4 transition-opacity hover:opacity-90"
    >
      <div>
        <p className="text-sm font-bold text-accent-foreground">لديك مبلغ جديد؟</p>
        <p className="mt-0.5 text-xs text-accent-foreground/80">
          احصل على توصية بتوزيع السيولة الجديدة على فئات المحفظة
        </p>
      </div>
      <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-primary text-primary-foreground">
        <ForwardChevronIcon />
      </span>
    </Link>
  );
}
