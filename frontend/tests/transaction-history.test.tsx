import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import type { TransactionOut } from "@/types/api";

const mocks = vi.hoisted(() => ({ listTransactions: vi.fn() }));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, api: { ...actual.api, listTransactions: mocks.listTransactions } };
});

import { TransactionHistory } from "@/components/portfolio/transaction-history";

function makeTransaction(overrides: Partial<TransactionOut> = {}): TransactionOut {
  return {
    id: "t1",
    asset_id: "a1",
    asset_symbol: "TEST",
    transaction_type: "BUY",
    quantity: "10",
    price: "50",
    fees: "0",
    transaction_date: "2026-09-01T10:00:00Z",
    notes: null,
    created_at: "2026-09-01T10:00:00Z",
    ...overrides,
  };
}

describe("TransactionHistory", () => {
  it("labels each of the four transaction types distinctly (Phase 16 fix — DEPOSIT was previously mislabeled بيع/SELL)", async () => {
    mocks.listTransactions.mockResolvedValue([
      makeTransaction({ id: "1", transaction_type: "BUY" }),
      makeTransaction({ id: "2", transaction_type: "SELL" }),
      makeTransaction({ id: "3", transaction_type: "DEPOSIT" }),
      makeTransaction({ id: "4", transaction_type: "WITHDRAWAL" }),
    ]);

    render(<TransactionHistory refreshToken={0} />);

    await waitFor(() => expect(screen.getByText("شراء")).toBeInTheDocument());
    expect(screen.getByText("بيع")).toBeInTheDocument();
    expect(screen.getByText("إيداع")).toBeInTheDocument();
    expect(screen.getByText("سحب")).toBeInTheDocument();
  });
});
