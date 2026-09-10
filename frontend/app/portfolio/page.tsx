"use client";

import { useMemo, useState } from "react";
import { useApiQuery } from "@/hooks/use-api-query";
import { api } from "@/lib/api";
import { QueryBoundary, EmptyBlock } from "@/components/ui/query-boundary";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { TotalValueCard, ValueSplitCard } from "@/components/dashboard";
import { TransactionForm } from "@/components/portfolio/transaction-form";
import { TransactionHistory } from "@/components/portfolio/transaction-history";
import { ManualPriceEditor, PriceStateBadge } from "@/components/portfolio/price-state";
import { AlertTriangleIcon } from "@/components/icons";
import { formatCurrency, formatNumber, formatPercent, isNegative, isZero } from "@/lib/format";
import type { HoldingPnLOut } from "@/types/api";

export default function PortfolioPage() {
  const summaryQuery = useApiQuery(() => api.portfolioSummary());
  const [historyRefreshToken, setHistoryRefreshToken] = useState(0);

  const holdingQuantityByAssetId = useMemo(() => {
    if (summaryQuery.status !== "success") return {};
    return Object.fromEntries(summaryQuery.data.holdings_pnl.map((h) => [h.asset_id, h.quantity]));
  }, [summaryQuery]);

  function handleTransactionRecorded() {
    summaryQuery.refetch();
    setHistoryRefreshToken((t) => t + 1);
  }

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-lg font-bold text-foreground">المحفظة</h1>
      <QueryBoundary state={summaryQuery} onRetry={summaryQuery.refetch} loadingLabel="جارٍ تحميل المحفظة...">
        {(summary) => (
          <>
            <TotalValueCard summary={summary} />
            <ValueSplitCard summary={summary} />

            {!summary.is_complete ? (
              <div className="flex items-start gap-2 rounded-2xl border border-warning/30 bg-warning-muted p-3 text-xs text-warning">
                <AlertTriangleIcon width={16} height={16} className="mt-0.5 shrink-0" />
                <p>
                  القيم أعلاه غير مكتملة: توجد {summary.unpriced_asset_ids.length} أصول مملوكة بدون سعر متاح حاليًا،
                  ولم تُحتسب قيمتها ضمن الإجمالي (لم تُعتبر صفرًا).
                </p>
              </div>
            ) : null}

            <Card>
              <CardHeader title="المراكز الحالية" subtitle={`${summary.holdings_pnl.length} مركز نشط`} />
              <CardBody>
                {summary.holdings_pnl.length === 0 ? (
                  <EmptyBlock
                    title="لا توجد مراكز حالية"
                    body="لم تُسجَّل أي كمية مملوكة بعد. المراكز تُقرأ من جدول الحيازات الحالية، وليست من اللقطات التاريخية."
                  />
                ) : (
                  <ul className="flex flex-col divide-y divide-border">
                    {summary.holdings_pnl.map((holding) => (
                      <HoldingRow
                        key={holding.asset_id}
                        holding={holding}
                        currency={summary.base_currency}
                        onPriceChanged={summaryQuery.refetch}
                      />
                    ))}
                  </ul>
                )}
              </CardBody>
            </Card>
          </>
        )}
      </QueryBoundary>

      <Card>
        <CardHeader title="تسجيل معاملة" subtitle="شراء أو بيع فعلي — ليس توصية" />
        <CardBody>
          <TransactionForm holdingQuantityByAssetId={holdingQuantityByAssetId} onSuccess={handleTransactionRecorded} />
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="سجل المعاملات" />
        <CardBody>
          <TransactionHistory refreshToken={historyRefreshToken} />
        </CardBody>
      </Card>
    </div>
  );
}

function HoldingRow({
  holding,
  currency,
  onPriceChanged,
}: {
  holding: HoldingPnLOut;
  currency: string;
  onPriceChanged: () => void;
}) {
  const negative = isNegative(holding.unrealized_pnl);
  const zero = isZero(holding.unrealized_pnl);
  const tone = holding.unrealized_pnl === null ? "text-muted-foreground" : zero ? "text-muted-foreground" : negative ? "text-danger" : "text-success";
  const priceUnavailable = holding.current_price === null;

  return (
    <li className="flex flex-col gap-2 py-3 first:pt-0 last:pb-0">
      <div className="flex items-center justify-between">
        <span className="text-sm font-bold text-foreground">{holding.symbol}</span>
        <span className="tabular-nums text-sm font-semibold text-foreground">
          {formatCurrency(holding.market_value, currency)}
        </span>
      </div>
      <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-[11px] text-muted-foreground sm:grid-cols-4">
        <span>
          الكمية: <span className="tabular-nums text-foreground">{formatNumber(holding.quantity)}</span>
        </span>
        <span>
          متوسط التكلفة:{" "}
          <span className="tabular-nums text-foreground">{formatCurrency(holding.average_cost, currency)}</span>
        </span>
        <span>
          السعر الحالي:{" "}
          <span className="tabular-nums text-foreground">{formatCurrency(holding.current_price, currency)}</span>
        </span>
        <span>
          التكلفة الإجمالية:{" "}
          <span className="tabular-nums text-foreground">{formatCurrency(holding.cost_basis, currency)}</span>
        </span>
      </div>

      <div className="flex items-center justify-between gap-2">
        <p className={`tabular-nums text-xs font-semibold ${tone}`}>
          {holding.unrealized_pnl !== null
            ? `${formatCurrency(holding.unrealized_pnl, currency)}${
                holding.unrealized_pnl_percent !== null ? ` (${formatPercent(holding.unrealized_pnl_percent)})` : " (النسبة غير محسوبة)"
              }`
            : priceUnavailable
              ? "الربح/الخسارة غير متاحة — السعر الحالي غير متوفر"
              : "غير متاح"}
        </p>
        <div className="flex items-center gap-1.5">
          <PriceStateBadge status={holding.price_status} isStale={holding.price_is_stale} recordedAt={holding.price_recorded_at} />
          <ManualPriceEditor assetId={holding.asset_id} assetCurrency={holding.asset_currency} onSaved={onPriceChanged} />
        </div>
      </div>
    </li>
  );
}
