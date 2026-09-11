"use client";

import { useApiQuery } from "@/hooks/use-api-query";
import { api } from "@/lib/api";
import { QueryBoundary, EmptyBlock } from "@/components/ui/query-boundary";
import { BucketCard, StrategyDetailCard } from "@/components/allocation";

export default function AllocationPage() {
  const allocationQuery = useApiQuery(() => api.portfolioAllocation());
  const strategyQuery = useApiQuery(() => api.strategyValidation());
  const summaryQuery = useApiQuery(() => api.portfolioSummary());
  // Phase 17: best-effort — a rebalancing recommendation is a helpful
  // addition to each bucket card, never a requirement for the
  // Distribution screen to render (see QueryBoundary usage below: no
  // loading/error state is shown for this query on its own, and a
  // bucket simply renders without its RebalancingHint until this
  // resolves or if it fails).
  const rebalancingQuery = useApiQuery(() => api.portfolioRebalancing());

  const currency = summaryQuery.status === "success" ? summaryQuery.data.base_currency : "";
  const recommendationByBucketId =
    rebalancingQuery.status === "success"
      ? Object.fromEntries(rebalancingQuery.data.recommendations.map((r) => [r.strategy_bucket_id, r]))
      : {};

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-lg font-bold text-foreground">التوزيع والاستراتيجية</h1>

      <QueryBoundary state={strategyQuery} onRetry={strategyQuery.refetch} loadingLabel="جارٍ تحميل الاستراتيجية...">
        {(validation) => <StrategyDetailCard validation={validation} />}
      </QueryBoundary>

      <QueryBoundary state={allocationQuery} onRetry={allocationQuery.refetch} loadingLabel="جارٍ تحميل التوزيع...">
        {(allocation) =>
          allocation.buckets.length === 0 ? (
            <EmptyBlock title="لا توجد فئات استراتيجية مُهيّأة بعد" />
          ) : (
            <div className="flex flex-col gap-3">
              {allocation.buckets.map((bucket) => (
                <BucketCard
                  key={bucket.strategy_bucket_id}
                  bucket={bucket}
                  currency={currency}
                  recommendation={recommendationByBucketId[bucket.strategy_bucket_id]}
                />
              ))}
            </div>
          )
        }
      </QueryBoundary>
    </div>
  );
}
