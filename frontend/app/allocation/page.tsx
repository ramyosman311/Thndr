"use client";

import { useApiQuery } from "@/hooks/use-api-query";
import { api } from "@/lib/api";
import { QueryBoundary, EmptyBlock } from "@/components/ui/query-boundary";
import { BucketCard, StrategyDetailCard } from "@/components/allocation";

export default function AllocationPage() {
  const allocationQuery = useApiQuery(() => api.portfolioAllocation());
  const strategyQuery = useApiQuery(() => api.strategyValidation());
  const summaryQuery = useApiQuery(() => api.portfolioSummary());

  const currency = summaryQuery.status === "success" ? summaryQuery.data.base_currency : "";

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
                <BucketCard key={bucket.strategy_bucket_id} bucket={bucket} currency={currency} />
              ))}
            </div>
          )
        }
      </QueryBoundary>
    </div>
  );
}
