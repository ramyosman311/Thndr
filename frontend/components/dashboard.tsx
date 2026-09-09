"use client";

import Link from "next/link";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { MetricCard } from "@/components/ui/metric-card";
import { StatusPill } from "@/components/ui/status-pill";
import { ForwardChevronIcon, BellIcon, CashIcon, CheckCircleIcon, WalletIcon } from "@/components/icons";
import { formatCurrency, formatPercent, isNegative, isZero } from "@/lib/format";
import { strategyStatusMeta } from "@/lib/status-labels";
import type { PortfolioAllocationOut, PortfolioSummaryOut, StrategyValidationOut, WatchlistOut } from "@/types/api";

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
