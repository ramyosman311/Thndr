import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ApiError } from "@/lib/api";
import type { PortfolioAnalyticsHistoryOut } from "@/types/api";

const mocks = vi.hoisted(() => ({
  portfolioAnalyticsHistory: vi.fn(),
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    api: { portfolioAnalyticsHistory: mocks.portfolioAnalyticsHistory },
  };
});

import { WealthHistoryCard } from "@/components/dashboard";

function insufficientHistory(range: PortfolioAnalyticsHistoryOut["range"]): PortfolioAnalyticsHistoryOut {
  return {
    range,
    base_currency: "EGP",
    data: [],
    insufficient_history: true,
    message: "Insufficient historical data for this range.",
  };
}

function populatedHistory(): PortfolioAnalyticsHistoryOut {
  return {
    range: "1M",
    base_currency: "EGP",
    data: [
      { date: "2026-08-01", portfolio_value: "10000.00", invested_capital: "10000.00", total_pnl: "0.00", twr_percentage: "0.00" },
      { date: "2026-08-15", portfolio_value: "11000.00", invested_capital: "10000.00", total_pnl: "1000.00", twr_percentage: "10.00" },
    ],
    insufficient_history: false,
    message: null,
  };
}

describe("WealthHistoryCard", () => {
  it("shows a loading state before the API responds", () => {
    mocks.portfolioAnalyticsHistory.mockReturnValue(new Promise(() => {})); // never resolves
    render(<WealthHistoryCard />);
    expect(screen.getByText(/جارٍ تحميل السجل التاريخي/)).toBeInTheDocument();
  });

  it("shows an explicit insufficient-data state, never an empty chart presented as real data", async () => {
    mocks.portfolioAnalyticsHistory.mockResolvedValue(insufficientHistory("1M"));
    render(<WealthHistoryCard />);

    await waitFor(() => {
      expect(screen.getByText("لا تتوفر بيانات تاريخية كافية")).toBeInTheDocument();
    });
    expect(screen.getByText("Insufficient historical data for this range.")).toBeInTheDocument();
    // No fabricated currency figure should render in this state.
    expect(screen.queryByText(/EGP/)).not.toBeInTheDocument();
  });

  it("shows an error state with a retry option when the API call fails", async () => {
    mocks.portfolioAnalyticsHistory.mockRejectedValue(new ApiError("server", 500, "Internal error"));
    render(<WealthHistoryCard />);

    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeInTheDocument();
    });
  });

  it("renders real backend data points with correct portfolio value, invested capital, and TWR", async () => {
    mocks.portfolioAnalyticsHistory.mockResolvedValue(populatedHistory());
    render(<WealthHistoryCard />);

    await waitFor(() => {
      expect(screen.getByText(/11,000.00 EGP/)).toBeInTheDocument();
    });
    expect(screen.getByText(/10.00% عائد حقيقي/)).toBeInTheDocument();
    // The chart's SVG (real geometry from real data) must be present.
    expect(screen.getByRole("img", { name: /مخطط قيمة المحفظة/ })).toBeInTheDocument();
  });

  it("never fabricates a TWR figure when the backend returns null for a point", async () => {
    mocks.portfolioAnalyticsHistory.mockResolvedValue({
      range: "1M",
      base_currency: "EGP",
      data: [
        { date: "2026-08-01", portfolio_value: "0.00", invested_capital: "0.00", total_pnl: "0.00", twr_percentage: null },
        { date: "2026-08-15", portfolio_value: "100.00", invested_capital: "0.00", total_pnl: "100.00", twr_percentage: null },
      ],
      insufficient_history: false,
      message: null,
    });
    render(<WealthHistoryCard />);

    await waitFor(() => {
      expect(screen.getByText("100.00 EGP")).toBeInTheDocument();
    });
    expect(screen.getByText("العائد الحقيقي غير محسوب لهذا النطاق")).toBeInTheDocument();
    expect(screen.queryByText(/عائد حقيقي \(TWR\)/)).not.toBeInTheDocument();
  });

  it("re-fetches with the newly selected range when a range button is clicked", async () => {
    const user = userEvent.setup();
    mocks.portfolioAnalyticsHistory.mockResolvedValue(insufficientHistory("1M"));
    render(<WealthHistoryCard />);

    await waitFor(() => {
      expect(mocks.portfolioAnalyticsHistory).toHaveBeenCalledWith("1M");
    });

    mocks.portfolioAnalyticsHistory.mockResolvedValue(insufficientHistory("ALL"));
    await user.click(screen.getByRole("tab", { name: "الكل" }));

    await waitFor(() => {
      expect(mocks.portfolioAnalyticsHistory).toHaveBeenCalledWith("ALL");
    });
  });
});
