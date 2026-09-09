import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { StrategyBanner, TotalValueCard } from "@/components/dashboard";
import type { PortfolioSummaryOut, StrategyValidationOut } from "@/types/api";

function makeSummary(overrides: Partial<PortfolioSummaryOut> = {}): PortfolioSummaryOut {
  return {
    base_currency: "EGP",
    total_value: "10000.00",
    emergency_value: "0.00",
    investable_value: "10000.00",
    denominator_basis: "investable",
    denominator_value: "10000.00",
    emergency_excluded: true,
    holdings_pnl: [],
    total_unrealized_pnl: "500.00",
    total_unrealized_pnl_percent: "5.00",
    ...overrides,
  };
}

describe("TotalValueCard", () => {
  it("renders the total value and a positive P/L badge", () => {
    render(<TotalValueCard summary={makeSummary()} />);
    expect(screen.getByText(/10,000.00 EGP/)).toBeInTheDocument();
    expect(screen.getByText(/500.00 EGP \(5.00%\)/)).toBeInTheDocument();
  });

  it("never fabricates a percent when the backend returns null", () => {
    render(
      <TotalValueCard
        summary={makeSummary({ total_unrealized_pnl: "0.00", total_unrealized_pnl_percent: null })}
      />
    );
    // The percent must not appear as "0%" or any invented number.
    expect(screen.queryByText(/%\)/)).not.toBeInTheDocument();
    expect(screen.getByText(/لا توجد تكلفة شراء مسجّلة/)).toBeInTheDocument();
  });
});

describe("StrategyBanner", () => {
  const validation: StrategyValidationOut = {
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
  };

  it("renders an incomplete strategy as a warning, not an error", () => {
    render(<StrategyBanner validation={validation} />);
    const pill = screen.getByText("توزيع الاستهداف غير مكتمل");
    expect(pill).toBeInTheDocument();
    // Warning tone class, never the danger/error tone class.
    expect(pill.className).toContain("warning");
    expect(pill.className).not.toContain("danger");
  });

  it("shows the exact 85% figure without inventing the missing 15%", () => {
    render(<StrategyBanner validation={validation} />);
    expect(screen.getByText("85.00%")).toBeInTheDocument();
    expect(screen.getByText(/100.00%/)).toBeInTheDocument();
  });
});
