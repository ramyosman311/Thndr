import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

const mocks = vi.hoisted(() => ({
  portfolioAllocation: vi.fn(),
  strategyValidation: vi.fn(),
  portfolioSummary: vi.fn(),
  portfolioRebalancing: vi.fn(),
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    api: {
      portfolioAllocation: mocks.portfolioAllocation,
      strategyValidation: mocks.strategyValidation,
      portfolioSummary: mocks.portfolioSummary,
      portfolioRebalancing: mocks.portfolioRebalancing,
    },
  };
});

import AllocationPage from "@/app/allocation/page";

describe("AllocationPage", () => {
  it("renders each bucket's target/minimum/maximum status using the backend's own values", async () => {
    mocks.portfolioSummary.mockResolvedValue({
      base_currency: "EGP",
      total_value: "10000.00",
      emergency_value: "0.00",
      investable_value: "10000.00",
      denominator_basis: "investable",
      denominator_value: "10000.00",
      emergency_excluded: false,
      holdings_pnl: [],
      total_unrealized_pnl: "0.00",
      total_unrealized_pnl_percent: null,
    });
    mocks.strategyValidation.mockResolvedValue({
      status: "INCOMPLETE_TARGET_ALLOCATION",
      is_valid: false,
      total_target_percent: "85.00",
      expected_target_percent: "100.00",
      explanation: "Configured target allocation totals 85.00%.",
      target_rows: [],
      maximum_only_rows: [],
      excluded_emergency_rows: [],
      field_errors: [],
      priority_order: [],
    });
    mocks.portfolioAllocation.mockResolvedValue({
      total_portfolio_value: "10000.00",
      risk_denominator_basis: "investable",
      risk_denominator_value: "10000.00",
      emergency_excluded: false,
      buckets: [
        {
          strategy_bucket_id: "b1",
          bucket_name: "Individual Stocks",
          actual_value: "1000.00",
          total_portfolio_percent: "10.00",
          risk_allocation_percent: "10.00",
          target_percent: null,
          minimum_percent: null,
          maximum_percent: "15.00",
          allow_new_buy: true,
          target_status: "NO_TARGET",
          minimum_status: "NO_MINIMUM",
          maximum_status: "WITHIN_MAXIMUM",
          buy_allowed: true,
          excluded_from_risk_allocation: false,
        },
      ],
    });
    mocks.portfolioRebalancing.mockResolvedValue({
      available_cash: "0.00",
      total_recommended_buy: "0.00",
      total_recommended_reduce: "0.00",
      is_complete: true,
      recommendations: [
        {
          strategy_bucket_id: "b1",
          bucket_name: "Individual Stocks",
          actual_value: "1000.00",
          current_percent: "10.00",
          target_percent: null,
          maximum_percent: "15.00",
          difference_percent: null,
          target_value: null,
          difference_value: null,
          action: "NO_TARGET",
          recommended_value: null,
          priority: 0,
          allow_new_buy: true,
          status: "NO_TARGET",
          reason: "Individual Stocks has no configured target.",
        },
      ],
    });

    render(<AllocationPage />);

    await waitFor(() => {
      expect(screen.getByText("Individual Stocks")).toBeInTheDocument();
    });
    expect(screen.getByText("توزيع الاستهداف غير مكتمل")).toBeInTheDocument();
    expect(screen.getByText("بدون هدف")).toBeInTheDocument();
    expect(screen.getByText("ضمن الحد الأقصى")).toBeInTheDocument();
    // A maximum-only bucket must never be shown with an invented target.
    expect(screen.getByText("بدون هدف محدد")).toBeInTheDocument();

    // Phase 17: the rebalancing recommendation surfaces contextually on
    // this same card, not only in a separate Settings screen.
    await waitFor(() => {
      expect(screen.getByText("Individual Stocks has no configured target.")).toBeInTheDocument();
    });
  });

  it("shows an empty state instead of a fabricated bucket when none are configured", async () => {
    mocks.portfolioSummary.mockRejectedValue(new Error("404"));
    mocks.strategyValidation.mockResolvedValue({
      status: "EMPTY_CONFIGURATION",
      is_valid: false,
      total_target_percent: "0.00",
      expected_target_percent: "100.00",
      explanation: "No configuration yet.",
      target_rows: [],
      maximum_only_rows: [],
      excluded_emergency_rows: [],
      field_errors: [],
      priority_order: [],
    });
    mocks.portfolioAllocation.mockResolvedValue({
      total_portfolio_value: "0.00",
      risk_denominator_basis: "investable",
      risk_denominator_value: "0.00",
      emergency_excluded: false,
      buckets: [],
    });
    mocks.portfolioRebalancing.mockResolvedValue({
      available_cash: "0.00",
      total_recommended_buy: "0.00",
      total_recommended_reduce: "0.00",
      is_complete: true,
      recommendations: [],
    });

    render(<AllocationPage />);

    await waitFor(() => {
      expect(screen.getByText("لا توجد فئات استراتيجية مُهيّأة بعد")).toBeInTheDocument();
    });
  });
});
