import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ApiError } from "@/lib/api";

const mocks = vi.hoisted(() => ({
  listAssets: vi.fn(),
  listStrategyBuckets: vi.fn(),
  createAsset: vi.fn(),
  updateAsset: vi.fn(),
  activateAsset: vi.fn(),
  deactivateAsset: vi.fn(),
  deleteAsset: vi.fn(),
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    api: { ...mocks },
  };
});

import { AssetsAdmin } from "@/components/settings/assets-admin";

const ASSET = {
  id: "a1", symbol: "TMGH", name: "Talaat Moustafa", asset_type: "STOCK",
  market: "EGX", currency: "EGP", strategy_bucket_id: null, is_active: true,
};

describe("AssetsAdmin", () => {
  it("lists assets with their status", async () => {
    mocks.listAssets.mockResolvedValue([ASSET]);
    mocks.listStrategyBuckets.mockResolvedValue([]);

    render(<AssetsAdmin />);
    await waitFor(() => expect(screen.getByText("TMGH")).toBeInTheDocument());
    expect(screen.getByText("نشط")).toBeInTheDocument();
  });

  it("filters the list by search text", async () => {
    mocks.listAssets.mockResolvedValue([
      ASSET,
      { ...ASSET, id: "a2", symbol: "ETEL", name: "Egypt Telecom" },
    ]);
    mocks.listStrategyBuckets.mockResolvedValue([]);

    const user = userEvent.setup();
    render(<AssetsAdmin />);
    await waitFor(() => expect(screen.getByText("TMGH")).toBeInTheDocument());

    await user.type(screen.getByPlaceholderText("بحث بالرمز أو الاسم..."), "ETEL");
    expect(screen.queryByText("TMGH")).not.toBeInTheDocument();
    expect(screen.getByText("ETEL")).toBeInTheDocument();
  });

  it("creates a new asset via the create form", async () => {
    mocks.listAssets.mockResolvedValue([]);
    mocks.listStrategyBuckets.mockResolvedValue([]);
    mocks.createAsset.mockResolvedValue({ ...ASSET, id: "new1", symbol: "NEWCO" });

    const user = userEvent.setup();
    render(<AssetsAdmin />);
    await waitFor(() => expect(screen.getByRole("button", { name: /أصل جديد/ })).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: /أصل جديد/ }));

    await user.type(screen.getByLabelText("الرمز"), "NEWCO");
    await user.type(screen.getByLabelText("الاسم"), "New Co");
    await user.click(screen.getByRole("button", { name: "إنشاء" }));

    await waitFor(() =>
      expect(mocks.createAsset).toHaveBeenCalledWith(
        expect.objectContaining({ symbol: "NEWCO", name: "New Co", currency: "EGP" })
      )
    );
  });

  it("shows a conflict error when creating a duplicate symbol", async () => {
    mocks.listAssets.mockResolvedValue([]);
    mocks.listStrategyBuckets.mockResolvedValue([]);
    mocks.createAsset.mockRejectedValue(new ApiError("conflict", 409, "Asset symbol already in use."));

    const user = userEvent.setup();
    render(<AssetsAdmin />);
    await waitFor(() => expect(screen.getByRole("button", { name: /أصل جديد/ })).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: /أصل جديد/ }));
    await user.type(screen.getByLabelText("الرمز"), "DUP");
    await user.type(screen.getByLabelText("الاسم"), "Dup");
    await user.click(screen.getByRole("button", { name: "إنشاء" }));

    await waitFor(() => expect(screen.getByText("تعارض في البيانات")).toBeInTheDocument());
  });

  it("edits an asset's name and market via the inline edit form", async () => {
    mocks.listAssets.mockResolvedValue([ASSET]);
    mocks.listStrategyBuckets.mockResolvedValue([]);
    mocks.updateAsset.mockResolvedValue({ ...ASSET, name: "Renamed" });

    const user = userEvent.setup();
    render(<AssetsAdmin />);
    await waitFor(() => expect(screen.getByText("TMGH")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "تعديل" }));

    const nameInput = screen.getByDisplayValue("Talaat Moustafa");
    await user.clear(nameInput);
    await user.type(nameInput, "Renamed");
    await user.click(screen.getByRole("button", { name: "حفظ" }));

    await waitFor(() =>
      expect(mocks.updateAsset).toHaveBeenCalledWith("a1", expect.objectContaining({ name: "Renamed" }))
    );
  });

  it("deactivates and reactivates an asset", async () => {
    mocks.listAssets.mockResolvedValue([ASSET]);
    mocks.listStrategyBuckets.mockResolvedValue([]);
    mocks.deactivateAsset.mockResolvedValue({ ...ASSET, is_active: false });

    const user = userEvent.setup();
    render(<AssetsAdmin />);
    await waitFor(() => expect(screen.getByText("TMGH")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "تعديل" }));
    await user.click(screen.getByRole("button", { name: "تعطيل" }));

    await waitFor(() => expect(mocks.deactivateAsset).toHaveBeenCalledWith("a1"));
  });

  it("blocks deletion with a clear conflict message when the asset has historical data", async () => {
    mocks.listAssets.mockResolvedValue([ASSET]);
    mocks.listStrategyBuckets.mockResolvedValue([]);
    mocks.deleteAsset.mockRejectedValue(
      new ApiError("conflict", 409, "Asset has holdings and cannot be permanently deleted.")
    );

    const user = userEvent.setup();
    render(<AssetsAdmin />);
    await waitFor(() => expect(screen.getByText("TMGH")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "تعديل" }));
    await user.click(screen.getByRole("button", { name: "حذف نهائي" }));

    await waitFor(() => expect(screen.getByText("تعارض في البيانات")).toBeInTheDocument());
  });
});
