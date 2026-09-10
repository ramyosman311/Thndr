import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ApiError } from "@/lib/api";

const mocks = vi.hoisted(() => ({
  listStrategyBuckets: vi.fn(),
  listAllocationTargets: vi.fn(),
  strategyValidation: vi.fn(),
  createStrategyBucket: vi.fn(),
  updateStrategyBucket: vi.fn(),
  activateStrategyBucket: vi.fn(),
  deactivateStrategyBucket: vi.fn(),
  createAllocationTarget: vi.fn(),
  updateAllocationTarget: vi.fn(),
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    api: { ...mocks },
  };
});

import { StrategyAdmin } from "@/components/settings/strategy-admin";

const BUCKET = { id: "b1", portfolio_config_id: "p1", name: "Growth", description: null, is_active: true };

const VALIDATION = {
  status: "INCOMPLETE_TARGET_ALLOCATION",
  is_valid: false,
  total_target_percent: "55.00",
  expected_target_percent: "100.00",
  explanation: "Configured target allocation totals 55.00%, which is below the expected 100%.",
  target_rows: [], maximum_only_rows: [], excluded_emergency_rows: [], field_errors: [], priority_order: [],
};

describe("StrategyAdmin", () => {
  it("shows the aggregate validation status banner", async () => {
    mocks.listStrategyBuckets.mockResolvedValue([BUCKET]);
    mocks.listAllocationTargets.mockResolvedValue([]);
    mocks.strategyValidation.mockResolvedValue(VALIDATION);

    render(<StrategyAdmin />);
    await waitFor(() => expect(screen.getByText(/توزيع الاستهداف غير مكتمل/)).toBeInTheDocument());
    expect(screen.getAllByText(/55.00%/).length).toBeGreaterThan(0);
  });

  it("creates a new strategy bucket", async () => {
    mocks.listStrategyBuckets.mockResolvedValue([]);
    mocks.listAllocationTargets.mockResolvedValue([]);
    mocks.strategyValidation.mockResolvedValue(VALIDATION);
    mocks.createStrategyBucket.mockResolvedValue({ ...BUCKET, id: "new1" });

    const user = userEvent.setup();
    render(<StrategyAdmin />);
    await waitFor(() => expect(screen.getByRole("button", { name: /فئة جديدة/ })).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: /فئة جديدة/ }));
    await user.type(screen.getByLabelText("اسم الفئة"), "Defensive");
    await user.click(screen.getByRole("button", { name: "إنشاء" }));

    await waitFor(() =>
      expect(mocks.createStrategyBucket).toHaveBeenCalledWith({ name: "Defensive", description: null })
    );
  });

  it("rejects a duplicate bucket name with a conflict message", async () => {
    mocks.listStrategyBuckets.mockResolvedValue([]);
    mocks.listAllocationTargets.mockResolvedValue([]);
    mocks.strategyValidation.mockResolvedValue(VALIDATION);
    mocks.createStrategyBucket.mockRejectedValue(new ApiError("conflict", 409, "already exists"));

    const user = userEvent.setup();
    render(<StrategyAdmin />);
    await waitFor(() => expect(screen.getByRole("button", { name: /فئة جديدة/ })).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: /فئة جديدة/ }));
    await user.type(screen.getByLabelText("اسم الفئة"), "Growth");
    await user.click(screen.getByRole("button", { name: "إنشاء" }));

    await waitFor(() => expect(screen.getByText("تعارض في البيانات")).toBeInTheDocument());
  });

  it("deactivates a bucket", async () => {
    mocks.listStrategyBuckets.mockResolvedValue([BUCKET]);
    mocks.listAllocationTargets.mockResolvedValue([]);
    mocks.strategyValidation.mockResolvedValue(VALIDATION);
    mocks.deactivateStrategyBucket.mockResolvedValue({ ...BUCKET, is_active: false });

    const user = userEvent.setup();
    render(<StrategyAdmin />);
    await waitFor(() => expect(screen.getByText("Growth")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "تعديل" }));
    await user.click(screen.getByRole("button", { name: "تعطيل" }));

    await waitFor(() => expect(mocks.deactivateStrategyBucket).toHaveBeenCalledWith("b1"));
  });

  it("creates an allocation target for a bucket without one yet", async () => {
    mocks.listStrategyBuckets.mockResolvedValue([BUCKET]);
    mocks.listAllocationTargets.mockResolvedValue([]);
    mocks.strategyValidation.mockResolvedValue(VALIDATION);
    mocks.createAllocationTarget.mockResolvedValue({
      id: "t1", portfolio_config_id: "p1", strategy_bucket_id: "b1",
      target_percent: "55.00", minimum_percent: null, maximum_percent: null,
      allow_new_buy: true, priority: 1, is_active: true,
    });

    const user = userEvent.setup();
    render(<StrategyAdmin />);
    await waitFor(() => expect(screen.getByRole("button", { name: /هدف جديد/ })).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: /هدف جديد/ }));
    await user.type(screen.getByLabelText("الهدف %"), "55");
    await user.click(screen.getByRole("button", { name: "إنشاء" }));

    await waitFor(() =>
      expect(mocks.createAllocationTarget).toHaveBeenCalledWith(
        expect.objectContaining({ strategy_bucket_id: "b1", target_percent: "55" })
      )
    );
  });

  it("never blocks target creation on the aggregate validation status", async () => {
    // The banner shows INCOMPLETE, but creating another target must still work.
    mocks.listStrategyBuckets.mockResolvedValue([BUCKET]);
    mocks.listAllocationTargets.mockResolvedValue([]);
    mocks.strategyValidation.mockResolvedValue(VALIDATION);
    mocks.createAllocationTarget.mockResolvedValue({
      id: "t1", portfolio_config_id: "p1", strategy_bucket_id: "b1",
      target_percent: "10.00", minimum_percent: null, maximum_percent: null,
      allow_new_buy: true, priority: 0, is_active: true,
    });

    const user = userEvent.setup();
    render(<StrategyAdmin />);
    await waitFor(() => expect(screen.getByText(/توزيع الاستهداف غير مكتمل/)).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: /هدف جديد/ }));
    await user.type(screen.getByLabelText("الهدف %"), "10");
    await user.click(screen.getByRole("button", { name: "إنشاء" }));

    await waitFor(() => expect(mocks.createAllocationTarget).toHaveBeenCalled());
  });
});
