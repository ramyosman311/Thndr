import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ApiError } from "@/lib/api";

const mocks = vi.hoisted(() => ({
  allocateCashFlow: vi.fn(),
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    api: { allocateCashFlow: mocks.allocateCashFlow },
  };
});

import InflowPage from "@/app/inflow/page";

describe("InflowPage", () => {
  it("submits the entered amount and renders the recommendation, clearly labeled as non-executed", async () => {
    mocks.allocateCashFlow.mockResolvedValue({
      requested_cash: "1000.00",
      allocated_cash: "850.00",
      unallocated_cash: "150.00",
      strategy_status: "INCOMPLETE_TARGET_ALLOCATION",
      strategy_is_valid: false,
      recommendations: [
        {
          strategy_bucket_id: "b1",
          bucket_name: "Growth",
          current_value: "0.00",
          current_percent: "0.00",
          target_percent: "55.00",
          maximum_percent: null,
          allow_new_buy: true,
          priority: 1,
          target_gap: "550.00",
          maximum_capacity: null,
          eligible: true,
          allocated_amount: "550.00",
          status: "ELIGIBLE",
          projected_value: "550.00",
          projected_percent: "29.73",
        },
      ],
    });

    const user = userEvent.setup();
    render(<InflowPage />);

    const input = screen.getByPlaceholderText("5000.00");
    await user.type(input, "1000.00");
    await user.click(screen.getByRole("button", { name: "احسب التوصية" }));

    await waitFor(() => {
      expect(mocks.allocateCashFlow).toHaveBeenCalledWith("1000.00");
    });

    // The unallocated remainder must be shown exactly as returned, never
    // forced into a destination or hidden.
    await waitFor(() => {
      expect(screen.getByText("150.00")).toBeInTheDocument();
    });
    expect(screen.getByText("850.00")).toBeInTheDocument();
    expect(screen.getByText(/هذه توصية فقط/)).toBeInTheDocument();
    expect(screen.getByText("Growth")).toBeInTheDocument();
  });

  it("rejects a zero/invalid amount client-side without calling the API", async () => {
    const user = userEvent.setup();
    render(<InflowPage />);

    const input = screen.getByPlaceholderText("5000.00");
    await user.type(input, "0");
    await user.click(screen.getByRole("button", { name: "احسب التوصية" }));

    expect(screen.getByRole("alert")).toHaveTextContent("أدخل مبلغًا صحيحًا");
    expect(mocks.allocateCashFlow).not.toHaveBeenCalled();
  });

  it("shows a clear error state when the portfolio is not configured", async () => {
    mocks.allocateCashFlow.mockRejectedValue(
      new ApiError("not_configured", 404, "No portfolio configuration exists yet.")
    );

    const user = userEvent.setup();
    render(<InflowPage />);

    await user.type(screen.getByPlaceholderText("5000.00"), "500");
    await user.click(screen.getByRole("button", { name: "احسب التوصية" }));

    await waitFor(() => {
      expect(screen.getByText("لا توجد بيانات بعد")).toBeInTheDocument();
    });
  });
});
