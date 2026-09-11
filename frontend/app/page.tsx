"use client";

import { useApiQuery } from "@/hooks/use-api-query";
import { api } from "@/lib/api";
import { QueryBoundary, EmptyBlock } from "@/components/ui/query-boundary";
import {
  AllocationHealthCard,
  InflowCtaCard,
  StrategyBanner,
  TotalValueCard,
  ValueSplitCard,
  WatchlistSummaryCard,
  WealthHistoryCard,
} from "@/components/dashboard";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { PnLBadge } from "@/components/ui/pnl-badge";
import { formatCurrency } from "@/lib/format";
import type { HoldingPnLOut } from "@/types/api";

export default function DashboardPage() {
  const summaryQuery = useApiQuery(() => api.portfolioSummary());
  const allocationQuery = useApiQuery(() => api.portfolioAllocation());
  const strategyQuery = useApiQuery(() => api.strategyValidation());
  const watchlistQuery = useApiQuery(() => api.listWatchlist());

  return (
    <div className="flex flex-col gap-4">
      <QueryBoundary state={summaryQuery} onRetry={summaryQuery.refetch} loadingLabel="جارٍ تحميل ملخص المحفظة...">
        {(summary) => (
          <>
            <TotalValueCard summary={summary} />
            <ValueSplitCard summary={summary} />
            {summary.holdings_pnl.length > 0 ? <HoldingsPreview holdings={summary.holdings_pnl} /> : null}
          </>
        )}
      </QueryBoundary>

      <QueryBoundary state={strategyQuery} onRetry={strategyQuery.refetch} loadingLabel="جارٍ تحميل حالة الاستراتيجية...">
        {(validation) => <StrategyBanner validation={validation} />}
      </QueryBoundary>

      <QueryBoundary
        state={allocationQuery}
        onRetry={allocationQuery.refetch}
        loadingLabel="جارٍ تحميل بيانات التوزيع..."
      >
        {(allocation) =>
          allocation.buckets.length === 0 ? (
            <EmptyBlock title="لا توجد فئات استراتيجية مُهيّأة بعد" />
          ) : (
            <AllocationHealthCard allocation={allocation} />
          )
        }
      </QueryBoundary>

      <WealthHistoryCard />

      <QueryBoundary state={watchlistQuery} onRetry={watchlistQuery.refetch} loadingLabel="جارٍ تحميل المتابعة...">
        {(watchlist) => <WatchlistSummaryCard watchlist={watchlist} />}
      </QueryBoundary>

      <InflowCtaCard />
    </div>
  );
}

function HoldingsPreview({ holdings }: { holdings: HoldingPnLOut[] }) {
  const top = holdings.slice(0, 4);
  return (
    <Card>
      <CardHeader title="أبرز المراكز" subtitle={`${holdings.length} مركز نشط`} />
      <CardBody className="flex flex-col gap-2">
        {top.map((h) => (
          <div key={h.asset_id} className="flex items-center justify-between text-sm">
            <span className="font-semibold text-foreground">{h.symbol}</span>
            <div className="text-end">
              <p className="tabular-nums text-foreground">{formatCurrency(h.market_value)}</p>
              <PnLBadge value={h.unrealized_pnl} percent={h.unrealized_pnl_percent} />
            </div>
          </div>
        ))}
      </CardBody>
    </Card>
  );
}
