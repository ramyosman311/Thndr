import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ApiError } from "@/lib/api";

const mocks = vi.hoisted(() => ({
  portfolioSummary: vi.fn(),
  listAssets: vi.fn(),
  createTransaction: vi.fn(),
  listTransactions: vi.fn(),
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    api: {
      portfolioSummary: mocks.portfolioSummary,
      listAssets: mocks.listAssets,
      createTransaction: mocks.createTransaction,
      listTransactions: mocks.listTransactions,
    },
  };
});

import PortfolioPage from "@/app/portfolio/page";

const ASSET = { id: "a1", symbol: "TMGH", name: "Talaat Moustafa", asset_type: "STOCK", currency: "EGP", is_active: true };

function baseSummary(holdingsPnl: unknown[] = []) {
  return {
    base_currency: "EGP",
    total_value: "0.00",
    emergency_value: "0.00",
    investable_value: "0.00",
    denominator_basis: "investable",
    denominator_value: "0.00",
    emergency_excluded: true,
    is_complete: true,
    unpriced_asset_ids: [],
    holdings_pnl: holdingsPnl,
    total_unrealized_pnl: "0.00",
    total_unrealized_pnl_percent: null,
  };
}

describe("PortfolioPage transaction form", () => {
  it("renders BUY/SELL toggle and asset options from the API, never hardcoded", async () => {
    mocks.portfolioSummary.mockResolvedValue(baseSummary());
    mocks.listAssets.mockResolvedValue([ASSET]);
    mocks.listTransactions.mockResolvedValue([]);

    render(<PortfolioPage />);

    await waitFor(() => expect(screen.getByRole("button", { name: "شراء" })).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "بيع" })).toBeInTheDocument();
    const select = await screen.findByRole("combobox");
    expect(within(select).getByText(/TMGH/)).toBeInTheDocument();
  });

  it("shows clear validation errors and does not call the API when the form is incomplete", async () => {
    mocks.portfolioSummary.mockResolvedValue(baseSummary());
    mocks.listAssets.mockResolvedValue([ASSET]);
    mocks.listTransactions.mockResolvedValue([]);

    const user = userEvent.setup();
    render(<PortfolioPage />);

    await waitFor(() => expect(screen.getByRole("button", { name: "مراجعة المعاملة" })).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "مراجعة المعاملة" }));

    expect(await screen.findAllByRole("alert")).not.toHaveLength(0);
    expect(mocks.createTransaction).not.toHaveBeenCalled();
  });

  it("submits a BUY after confirmation and records it as an executed transaction, not a recommendation", async () => {
    mocks.portfolioSummary.mockResolvedValue(baseSummary());
    mocks.listAssets.mockResolvedValue([ASSET]);
    mocks.listTransactions.mockResolvedValue([]);
    mocks.createTransaction.mockResolvedValue({
      transaction: {
        id: "t1", asset_id: "a1", asset_symbol: "TMGH", transaction_type: "BUY",
        quantity: "10", price: "100.00", fees: "0.00",
        transaction_date: "2026-01-01T00:00:00Z", notes: null, created_at: "2026-01-01T00:00:00Z",
      },
      holding: { quantity: "10", average_cost: "100.00", current_price: "0.00" },
      realized_pnl: null,
    });

    const user = userEvent.setup();
    render(<PortfolioPage />);

    await waitFor(() => expect(screen.getByRole("combobox")).toBeInTheDocument());
    await user.selectOptions(screen.getByRole("combobox"), "a1");
    await user.type(screen.getByPlaceholderText("10"), "10");
    await user.type(screen.getByPlaceholderText("100.00"), "100");
    await user.click(screen.getByRole("button", { name: "مراجعة المعاملة" }));

    // Confirmation step must appear before the API is called.
    expect(await screen.findByRole("button", { name: "تأكيد التسجيل" })).toBeInTheDocument();
    expect(mocks.createTransaction).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "تأكيد التسجيل" }));

    await waitFor(() => {
      expect(mocks.createTransaction).toHaveBeenCalledWith(
        expect.objectContaining({ asset_id: "a1", transaction_type: "BUY", quantity: "10", price: "100" })
      );
    });
    expect(await screen.findByText(/تم تسجيل المعاملة بنجاح/)).toBeInTheDocument();
  });

  it("shows an oversell conflict from the API clearly", async () => {
    // No holdings_pnl row for this asset: the client-side "available
    // quantity" hint is unavailable, so this exercises the real
    // API-level 409 response path (the hint's own pre-check is covered
    // in a separate test below).
    mocks.portfolioSummary.mockResolvedValue(baseSummary());
    mocks.listAssets.mockResolvedValue([ASSET]);
    mocks.listTransactions.mockResolvedValue([]);
    mocks.createTransaction.mockRejectedValue(new ApiError("conflict", 409, "Cannot sell 10: only 5 currently held."));

    const user = userEvent.setup();
    render(<PortfolioPage />);

    await waitFor(() => expect(screen.getByRole("combobox")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "بيع" }));
    await user.selectOptions(screen.getByRole("combobox"), "a1");
    await user.type(screen.getByPlaceholderText("10"), "10");
    await user.type(screen.getByPlaceholderText("100.00"), "100");
    await user.click(screen.getByRole("button", { name: "مراجعة المعاملة" }));
    await user.click(await screen.findByRole("button", { name: "تأكيد التسجيل" }));

    await waitFor(() => {
      expect(screen.getByText("تعارض في البيانات")).toBeInTheDocument();
    });
  });

  it("shows the available quantity hint for SELL from the already-loaded portfolio summary", async () => {
    mocks.portfolioSummary.mockResolvedValue(
      baseSummary([
        {
          asset_id: "a1", symbol: "TMGH", quantity: "5", average_cost: "100", asset_currency: "EGP",
          current_price: "100", price_status: "CURRENT_PRICE_AVAILABLE", price_recorded_at: "2026-01-01T00:00:00Z",
          price_is_stale: false, market_value: "500.00", cost_basis: "500.00", unrealized_pnl: "0.00",
          unrealized_pnl_percent: "0.00",
        },
      ])
    );
    mocks.listAssets.mockResolvedValue([ASSET]);
    mocks.listTransactions.mockResolvedValue([]);

    const user = userEvent.setup();
    render(<PortfolioPage />);

    await waitFor(() => expect(screen.getByRole("combobox")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "بيع" }));
    await user.selectOptions(screen.getByRole("combobox"), "a1");

    expect(await screen.findByText(/الكمية المتاحة حاليًا/)).toBeInTheDocument();
  });
});

describe("PortfolioPage transaction history", () => {
  it("shows an empty state when there are no transactions, never a fabricated row", async () => {
    mocks.portfolioSummary.mockResolvedValue(baseSummary());
    mocks.listAssets.mockResolvedValue([]);
    mocks.listTransactions.mockResolvedValue([]);

    render(<PortfolioPage />);

    await waitFor(() => {
      expect(screen.getByText("لا توجد معاملات مسجلة بعد")).toBeInTheDocument();
    });
  });

  it("renders real transaction history rows with BUY/SELL badges", async () => {
    mocks.portfolioSummary.mockResolvedValue(baseSummary());
    mocks.listAssets.mockResolvedValue([]);
    mocks.listTransactions.mockResolvedValue([
      {
        id: "t1", asset_id: "a1", asset_symbol: "TMGH", transaction_type: "BUY",
        quantity: "10", price: "100.00", fees: "5.00",
        transaction_date: "2026-01-01T00:00:00Z", notes: "first lot", created_at: "2026-01-01T00:00:00Z",
      },
      {
        id: "t2", asset_id: "a1", asset_symbol: "TMGH", transaction_type: "SELL",
        quantity: "4", price: "120.00", fees: "0.00",
        transaction_date: "2026-02-01T00:00:00Z", notes: null, created_at: "2026-02-01T00:00:00Z",
      },
    ]);

    render(<PortfolioPage />);

    // "شراء"/"بيع" also label the transaction-form's BUY/SELL toggle
    // buttons, so scope the assertion to the history badges specifically.
    await waitFor(() => {
      expect(screen.getByText("first lot")).toBeInTheDocument();
    });
    const historyHeading = screen.getByText("سجل المعاملات");
    const historyCard = historyHeading.closest('[class*="rounded-2xl"]') as HTMLElement;
    expect(within(historyCard).getByText("شراء")).toBeInTheDocument();
    expect(within(historyCard).getByText("بيع")).toBeInTheDocument();
  });
});

describe("PortfolioPage holdings edge cases", () => {
  it("shows an empty state for holdings, never fabricated positions", async () => {
    mocks.portfolioSummary.mockResolvedValue(baseSummary());
    mocks.listAssets.mockResolvedValue([]);
    mocks.listTransactions.mockResolvedValue([]);

    render(<PortfolioPage />);

    await waitFor(() => {
      expect(screen.getByText("لا توجد مراكز حالية")).toBeInTheDocument();
    });
  });

  it("shows 'not configured' state when the backend has no portfolio yet, without crashing", async () => {
    mocks.portfolioSummary.mockRejectedValue(new ApiError("not_configured", 404, "No portfolio configuration exists yet."));
    mocks.listAssets.mockResolvedValue([]);
    mocks.listTransactions.mockResolvedValue([]);

    render(<PortfolioPage />);

    await waitFor(() => {
      expect(screen.getByText("لا توجد بيانات بعد")).toBeInTheDocument();
    });
  });
});

describe("PortfolioPage price states (Phase 11)", () => {
  it("shows an incomplete-valuation notice when a held asset has no usable price", async () => {
    mocks.portfolioSummary.mockResolvedValue({
      ...baseSummary([
        {
          asset_id: "a1", symbol: "UNPRICED", quantity: "5", average_cost: "100", asset_currency: "EGP",
          current_price: null, price_status: "PRICE_UNAVAILABLE", price_recorded_at: null, price_is_stale: false,
          market_value: null, cost_basis: "500.00", unrealized_pnl: null, unrealized_pnl_percent: null,
        },
      ]),
      is_complete: false,
      unpriced_asset_ids: ["a1"],
    });
    mocks.listAssets.mockResolvedValue([]);
    mocks.listTransactions.mockResolvedValue([]);

    render(<PortfolioPage />);

    await waitFor(() => {
      expect(screen.getByText(/القيم أعلاه غير مكتملة/)).toBeInTheDocument();
    });
    // Never a fabricated 0 for the unpriced holding's price or market value.
    expect(screen.getByText("السعر غير متاح")).toBeInTheDocument();
    expect(screen.getByText(/الربح\/الخسارة غير متاحة/)).toBeInTheDocument();
  });

  it("shows no incomplete-valuation notice when every position is priced", async () => {
    mocks.portfolioSummary.mockResolvedValue(
      baseSummary([
        {
          asset_id: "a1", symbol: "PRICED", quantity: "5", average_cost: "100", asset_currency: "EGP",
          current_price: "100", price_status: "CURRENT_PRICE_AVAILABLE", price_recorded_at: "2026-01-01T00:00:00Z",
          price_is_stale: false, market_value: "500.00", cost_basis: "500.00", unrealized_pnl: "0.00",
          unrealized_pnl_percent: "0.00",
        },
      ])
    );
    mocks.listAssets.mockResolvedValue([]);
    mocks.listTransactions.mockResolvedValue([]);

    render(<PortfolioPage />);

    await waitFor(() => {
      expect(screen.getByText("PRICED")).toBeInTheDocument();
    });
    expect(screen.queryByText(/القيم أعلاه غير مكتملة/)).not.toBeInTheDocument();
  });
});
