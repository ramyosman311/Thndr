"use client";

import { useApiQuery } from "@/hooks/use-api-query";
import { api } from "@/lib/api";
import { QueryBoundary, EmptyBlock } from "@/components/ui/query-boundary";
import { formatCurrency, formatDateTime, formatNumber } from "@/lib/format";
import type { TransactionOut } from "@/types/api";

export function TransactionHistory({ refreshToken }: { refreshToken: number }) {
  const query = useApiQuery(() => api.listTransactions(), [refreshToken]);

  return (
    <QueryBoundary state={query} onRetry={query.refetch} loadingLabel="جارٍ تحميل سجل المعاملات...">
      {(transactions) =>
        transactions.length === 0 ? (
          <EmptyBlock title="لا توجد معاملات مسجلة بعد" body="سجل معاملة شراء أو بيع لتظهر هنا كسجل تاريخي دائم." />
        ) : (
          <ul className="flex flex-col divide-y divide-border">
            {transactions.map((t) => (
              <TransactionRow key={t.id} transaction={t} />
            ))}
          </ul>
        )
      }
    </QueryBoundary>
  );
}

/** Phase 15 added DEPOSIT/WITHDRAWAL alongside BUY/SELL — this must
 * label all four distinctly (previously anything that wasn't BUY was
 * mislabeled "بيع"/SELL, including a DEPOSIT — a real display defect
 * found during Phase 16 live verification, fixed here since it sits
 * directly in the transaction-history display this phase already
 * touches for ordering). */
const TRANSACTION_TYPE_META: Record<string, { label: string; tone: "success" | "danger" | "warning" }> = {
  BUY: { label: "شراء", tone: "success" },
  SELL: { label: "بيع", tone: "danger" },
  DEPOSIT: { label: "إيداع", tone: "success" },
  WITHDRAWAL: { label: "سحب", tone: "warning" },
};

function TransactionRow({ transaction }: { transaction: TransactionOut }) {
  const meta = TRANSACTION_TYPE_META[transaction.transaction_type] ?? {
    label: transaction.transaction_type,
    tone: "warning" as const,
  };
  return (
    <li className="flex flex-col gap-1 py-3 first:pt-0 last:pb-0">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span
            className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${
              meta.tone === "success"
                ? "bg-success-muted text-success"
                : meta.tone === "danger"
                  ? "bg-danger-muted text-danger"
                  : "bg-warning-muted text-warning"
            }`}
          >
            {meta.label}
          </span>
          <span className="text-sm font-bold text-foreground">{transaction.asset_symbol}</span>
        </div>
        <span className="text-[11px] text-muted-foreground">{formatDateTime(transaction.transaction_date)}</span>
      </div>
      <div className="grid grid-cols-3 gap-x-3 text-[11px] text-muted-foreground">
        <span>
          الكمية: <span className="tabular-nums text-foreground">{formatNumber(transaction.quantity)}</span>
        </span>
        <span>
          السعر: <span className="tabular-nums text-foreground">{formatCurrency(transaction.price)}</span>
        </span>
        <span>
          الرسوم: <span className="tabular-nums text-foreground">{formatCurrency(transaction.fees)}</span>
        </span>
      </div>
      {transaction.notes ? <p className="text-[11px] italic text-muted-foreground">{transaction.notes}</p> : null}
    </li>
  );
}
