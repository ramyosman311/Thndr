import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { ApiError } from "@/lib/api";

const mocks = vi.hoisted(() => ({
  portfolioSummary: vi.fn(),
  portfolioAllocation: vi.fn(),
  strategyValidation: vi.fn(),
  listWatchlist: vi.fn(),
  portfolioAnalyticsHistory: vi.fn(),
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    api: {
      portfolioSummary: mocks.portfolioSummary,
      portfolioAllocation: mocks.portfolioAllocation,
      strategyValidation: mocks.strategyValidation,
      listWatchlist: mocks.listWatchlist,
      portfolioAnalyticsHistory: mocks.portfolioAnalyticsHistory,
    },
  };
});

import DashboardPage from "@/app/page";

describe("DashboardPage", () => {
  it("shows a 'not configured' empty state, never fabricated numbers, when the backend has no portfolio yet", async () => {
    mocks.portfolioSummary.mockRejectedValue(new ApiError("not_configured", 404, "No portfolio configuration exists yet."));
    mocks.portfolioAllocation.mockRejectedValue(new ApiError("not_configured", 404, "No portfolio configuration exists yet."));
    mocks.strategyValidation.mockRejectedValue(new ApiError("not_configured", 404, "No portfolio configuration exists yet."));
    mocks.listWatchlist.mockResolvedValue([]);
    mocks.portfolioAnalyticsHistory.mockRejectedValue(
      new ApiError("not_configured", 404, "No portfolio configuration exists yet.")
    );

    render(<DashboardPage />);

    await waitFor(() => {
      expect(screen.getAllByText("لا توجد بيانات بعد").length).toBeGreaterThan(0);
    });
    // No total-value figure should render at all when the API 404s.
    expect(screen.queryByText(/EGP/)).not.toBeInTheDocument();
  });

  it("renders real backend values once loaded, including a watchlist summary", async () => {
    mocks.portfolioSummary.mockResolvedValue({
      base_currency: "EGP",
      total_value: "11000.00",
      emergency_value: "10000.00",
      investable_value: "1000.00",
      denominator_basis: "investable",
      denominator_value: "1000.00",
      emergency_excluded: true,
      holdings_pnl: [],
      total_unrealized_pnl: "0.00",
      total_unrealized_pnl_percent: null,
    });
    mocks.portfolioAllocation.mockResolvedValue({
      total_portfolio_value: "11000.00",
      risk_denominator_basis: "investable",
      risk_denominator_value: "1000.00",
      emergency_excluded: true,
      buckets: [],
    });
    mocks.strategyValidation.mockResolvedValue({
      status: "EMPTY_CONFIGURATION",
      is_valid: false,
      total_target_percent: "0.00",
      expected_target_percent: "100.00",
      explanation: "No strategy configured.",
      target_rows: [],
      maximum_only_rows: [],
      excluded_emergency_rows: [],
      field_errors: [],
      priority_order: [],
    });
    mocks.listWatchlist.mockResolvedValue([
      {
        id: "w1",
        asset_id: "a1",
        asset_symbol: "BWA",
        enabled: true,
        notes: null,
        added_at: "2026-01-01T00:00:00Z",
        removed_at: null,
        alert_rule: { id: "r1", watchlist_id: "w1", enabled: true, allocation_alert_enabled: false, allocation_max_percent: null, price_target_enabled: false, price_target: null, dip_buy_enabled: false, dip_buy_price: null, telegram_enabled: false, last_triggered_at: null },
      },
    ]);
    mocks.portfolioAnalyticsHistory.mockResolvedValue({
      range: "1M",
      base_currency: "EGP",
      data: [],
      insufficient_history: true,
      message: "Insufficient historical data for this range.",
    });

    render(<DashboardPage />);

    await waitFor(() => {
      expect(screen.getByText(/11,000.00 EGP/)).toBeInTheDocument();
    });
    expect(screen.getByText(/بتنبيهات مفعّلة/)).toBeInTheDocument();
    expect(screen.getAllByText("1").length).toBeGreaterThan(0);
  });
});
