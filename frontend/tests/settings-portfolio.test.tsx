import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ApiError } from "@/lib/api";

const mocks = vi.hoisted(() => ({
  getPortfolioConfig: vi.fn(),
  createPortfolioConfig: vi.fn(),
  updatePortfolioConfig: vi.fn(),
  listAssets: vi.fn(),
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    api: {
      getPortfolioConfig: mocks.getPortfolioConfig,
      createPortfolioConfig: mocks.createPortfolioConfig,
      updatePortfolioConfig: mocks.updatePortfolioConfig,
      listAssets: mocks.listAssets,
    },
  };
});

import { PortfolioSettings } from "@/components/settings/portfolio-settings";

describe("PortfolioSettings", () => {
  it("shows a create form when no portfolio is configured yet", async () => {
    mocks.getPortfolioConfig.mockRejectedValue(new ApiError("not_configured", 404, "No portfolio configuration exists yet."));
    mocks.listAssets.mockResolvedValue([]);

    render(<PortfolioSettings />);

    await waitFor(() => expect(screen.getByText("إنشاء المحفظة")).toBeInTheDocument());
  });

  it("creates a portfolio via the create form", async () => {
    mocks.getPortfolioConfig.mockRejectedValue(new ApiError("not_configured", 404, "x"));
    mocks.listAssets.mockResolvedValue([]);
    mocks.createPortfolioConfig.mockResolvedValue({
      id: "p1", name: "محفظتي", base_currency: "EGP", emergency_asset_id: null,
      emergency_excluded: false, telegram_enabled: false,
    });

    const user = userEvent.setup();
    render(<PortfolioSettings />);
    await waitFor(() => expect(screen.getByText("إنشاء المحفظة")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "إنشاء المحفظة" }));

    await waitFor(() => expect(mocks.createPortfolioConfig).toHaveBeenCalledWith({ name: "محفظتي", base_currency: "EGP" }));
  });

  it("shows the edit form with existing values when a portfolio is configured", async () => {
    mocks.getPortfolioConfig.mockResolvedValue({
      id: "p1", name: "My Portfolio", base_currency: "EGP", emergency_asset_id: null,
      emergency_excluded: true, telegram_enabled: false,
    });
    mocks.listAssets.mockResolvedValue([{ id: "a1", symbol: "TMGH", name: "Talaat", asset_type: "STOCK", market: null, currency: "EGP", strategy_bucket_id: null, is_active: true }]);

    render(<PortfolioSettings />);
    await waitFor(() => expect(screen.getByDisplayValue("My Portfolio")).toBeInTheDocument());
    expect(screen.getByDisplayValue("EGP")).toBeInTheDocument();
  });

  it("requires an explicit confirmation step before saving a base_currency change", async () => {
    mocks.getPortfolioConfig.mockResolvedValue({
      id: "p1", name: "My Portfolio", base_currency: "EGP", emergency_asset_id: null,
      emergency_excluded: false, telegram_enabled: false,
    });
    mocks.listAssets.mockResolvedValue([]);
    mocks.updatePortfolioConfig.mockResolvedValue({
      id: "p1", name: "My Portfolio", base_currency: "USD", emergency_asset_id: null,
      emergency_excluded: false, telegram_enabled: false,
    });

    const user = userEvent.setup();
    render(<PortfolioSettings />);
    await waitFor(() => expect(screen.getByDisplayValue("EGP")).toBeInTheDocument());

    const currencyInput = screen.getByDisplayValue("EGP");
    await user.clear(currencyInput);
    await user.type(currencyInput, "USD");
    await user.click(screen.getByRole("button", { name: "حفظ الإعدادات" }));

    // First click only asks for confirmation -- it must not call the API yet.
    expect(mocks.updatePortfolioConfig).not.toHaveBeenCalled();
    expect(screen.getByText(/تغيير عملة الأساس يؤثر/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "تأكيد تغيير العملة والحفظ" }));
    await waitFor(() => expect(mocks.updatePortfolioConfig).toHaveBeenCalled());
  });

  it("surfaces the backend's rejection when base_currency change is blocked by existing transactions", async () => {
    mocks.getPortfolioConfig.mockResolvedValue({
      id: "p1", name: "My Portfolio", base_currency: "EGP", emergency_asset_id: null,
      emergency_excluded: false, telegram_enabled: false,
    });
    mocks.listAssets.mockResolvedValue([]);
    mocks.updatePortfolioConfig.mockRejectedValue(
      new ApiError("conflict", 409, "Cannot change base_currency: transactions already exist.")
    );

    const user = userEvent.setup();
    render(<PortfolioSettings />);
    await waitFor(() => expect(screen.getByDisplayValue("EGP")).toBeInTheDocument());

    const currencyInput = screen.getByDisplayValue("EGP");
    await user.clear(currencyInput);
    await user.type(currencyInput, "USD");
    await user.click(screen.getByRole("button", { name: "حفظ الإعدادات" }));
    await user.click(screen.getByRole("button", { name: "تأكيد تغيير العملة والحفظ" }));

    await waitFor(() => expect(screen.getByText("تعارض في البيانات")).toBeInTheDocument());
  });
});
