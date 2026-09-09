"use client";

import { useState } from "react";
import { useApiQuery } from "@/hooks/use-api-query";
import { api } from "@/lib/api";
import { QueryBoundary, EmptyBlock } from "@/components/ui/query-boundary";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { AddAssetForm } from "@/components/watchlist/add-asset-form";
import { WatchlistEntryCard } from "@/components/watchlist/entry-card";
import { EvaluatePanel } from "@/components/watchlist/evaluate-panel";
import type { WatchlistOut } from "@/types/api";

export default function WatchlistPage() {
  const watchlistQuery = useApiQuery(() => api.listWatchlist());
  const [overrides, setOverrides] = useState<Record<string, WatchlistOut>>({});

  function applyChange(entry: WatchlistOut) {
    setOverrides((prev) => ({ ...prev, [entry.id]: entry }));
  }

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-lg font-bold text-foreground">المتابعة والتنبيهات</h1>

      <Card>
        <CardHeader title="إضافة أصل للمتابعة" />
        <CardBody>
          <QueryBoundary state={watchlistQuery} onRetry={watchlistQuery.refetch}>
            {(entries) => {
              const merged = mergeEntries(entries, overrides);
              const watchedIds = new Set(merged.filter((e) => e.enabled).map((e) => e.asset_id));
              return (
                <AddAssetForm
                  watchedAssetIds={watchedIds}
                  onAdded={(entry) => {
                    applyChange(entry);
                    watchlistQuery.refetch();
                  }}
                />
              );
            }}
          </QueryBoundary>
        </CardBody>
      </Card>

      <QueryBoundary state={watchlistQuery} onRetry={watchlistQuery.refetch} loadingLabel="جارٍ تحميل قائمة المتابعة...">
        {(entries) => {
          const merged = mergeEntries(entries, overrides);
          return merged.length === 0 ? (
            <EmptyBlock title="لا توجد أصول قيد المتابعة" body="أضف أصلًا من النموذج أعلاه لبدء متابعته." />
          ) : (
            <div className="flex flex-col gap-3">
              {merged.map((entry) => (
                <WatchlistEntryCard key={entry.id} entry={entry} onChanged={applyChange} />
              ))}
            </div>
          );
        }}
      </QueryBoundary>

      <Card>
        <CardHeader title="تقييم التنبيهات" subtitle="قراءة فقط — لا يتم تنفيذ أي بيع أو شراء" />
        <CardBody>
          <EvaluatePanel />
        </CardBody>
      </Card>
    </div>
  );
}

function mergeEntries(entries: WatchlistOut[], overrides: Record<string, WatchlistOut>): WatchlistOut[] {
  const byId = new Map(entries.map((e) => [e.id, e]));
  for (const [id, entry] of Object.entries(overrides)) {
    byId.set(id, entry);
  }
  return Array.from(byId.values()).sort(
    (a, b) => new Date(b.added_at).getTime() - new Date(a.added_at).getTime()
  );
}
