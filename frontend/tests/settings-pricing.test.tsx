import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ApiError } from "@/lib/api";

const mocks = vi.hoisted(() => ({
  listAssets: vi.fn(),
  getAssetPriceConfig: vi.fn(),
  putAssetPriceConfig: vi.fn(),
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    api: { ...mocks },
  };
});

import { PricingAdmin } from "@/components/settings/pricing-admin";

const ASSET = { id: "a1", symbol: "TMGH", name: "Talaat", asset_type: "STOCK", market: null, currency: "EGP", strategy_bucket_id: null, is_active: true };

const UNCONFIGURED = {
  asset_id: "a1", configured: false, primary_provider: null, primary_provider_symbol: null,
  secondary_provider: null, secondary_provider_symbol: null, automated_fetching_enabled: false,
  manual_override_enabled: true, stale_threshold_minutes: null, lock_manual: false,
};

describe("PricingAdmin", () => {
  it("shows an unconfigured status until an asset is selected and loaded", async () => {
    mocks.listAssets.mockResolvedValue([ASSET]);
    mocks.getAssetPriceConfig.mockResolvedValue(UNCONFIGURED);

    const user = userEvent.setup();
    render(<PricingAdmin />);
    await waitFor(() => expect(screen.getByRole("combobox")).toBeInTheDocument());
    await user.selectOptions(screen.getByRole("combobox"), "a1");

    await waitFor(() => expect(screen.getByText("غير مُهيّأ (يدوي فقط)")).toBeInTheDocument());
  });

  it("saves a valid provider configuration", async () => {
    mocks.listAssets.mockResolvedValue([ASSET]);
    mocks.getAssetPriceConfig.mockResolvedValue(UNCONFIGURED);
    mocks.putAssetPriceConfig.mockResolvedValue({
      ...UNCONFIGURED, configured: true, primary_provider: "yahoo", primary_provider_symbol: "TMGH.CA",
      automated_fetching_enabled: true,
    });

    const user = userEvent.setup();
    render(<PricingAdmin />);
    await user.selectOptions(await screen.findByRole("combobox"), "a1");
    await waitFor(() => expect(screen.getByText("غير مُهيّأ (يدوي فقط)")).toBeInTheDocument());

    const selects = screen.getAllByRole("combobox");
    const providerSelect = selects[1];
    await user.selectOptions(providerSelect, "yahoo");
    await user.type(screen.getByPlaceholderText(/TMGH.CA/), "TMGH.CA");
    await user.click(screen.getByLabelText("تفعيل الجلب الآلي للسعر"));
    await user.click(screen.getByRole("button", { name: "حفظ إعداد السعر" }));

    await waitFor(() =>
      expect(mocks.putAssetPriceConfig).toHaveBeenCalledWith(
        "a1",
        expect.objectContaining({
          primary_provider: "yahoo",
          primary_provider_symbol: "TMGH.CA",
          automated_fetching_enabled: true,
        })
      )
    );
  });

  it("surfaces a validation error from the backend for an inconsistent configuration", async () => {
    mocks.listAssets.mockResolvedValue([ASSET]);
    mocks.getAssetPriceConfig.mockResolvedValue(UNCONFIGURED);
    mocks.putAssetPriceConfig.mockRejectedValue(
      new ApiError("validation", 400, "automated_fetching_enabled requires a primary_provider.")
    );

    const user = userEvent.setup();
    render(<PricingAdmin />);
    await user.selectOptions(await screen.findByRole("combobox"), "a1");
    await waitFor(() => expect(screen.getByText("غير مُهيّأ (يدوي فقط)")).toBeInTheDocument());

    await user.click(screen.getByLabelText("تفعيل الجلب الآلي للسعر"));
    await user.click(screen.getByRole("button", { name: "حفظ إعداد السعر" }));

    await waitFor(() => expect(screen.getByText("بيانات غير صالحة")).toBeInTheDocument());
  });

  it("reflects an already-configured provider when loaded", async () => {
    mocks.listAssets.mockResolvedValue([ASSET]);
    mocks.getAssetPriceConfig.mockResolvedValue({
      ...UNCONFIGURED, configured: true, primary_provider: "yahoo", primary_provider_symbol: "TMGH.CA",
      lock_manual: true,
    });

    const user = userEvent.setup();
    render(<PricingAdmin />);
    await user.selectOptions(await screen.findByRole("combobox"), "a1");

    await waitFor(() => expect(screen.getByText("مُهيّأ")).toBeInTheDocument());
    expect(screen.getByDisplayValue("TMGH.CA")).toBeInTheDocument();
    expect(screen.getByLabelText(/قفل السعر اليدوي/)).toBeChecked();
  });
});
