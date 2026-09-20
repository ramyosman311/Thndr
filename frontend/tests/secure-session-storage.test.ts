import { afterEach, describe, expect, it, vi } from "vitest";

const secureStorageMock = vi.hoisted(() => ({
  getItem: vi.fn(),
  setItem: vi.fn(),
  removeItem: vi.fn(),
}));

vi.mock("@aparajita/capacitor-secure-storage", () => ({
  SecureStorage: secureStorageMock,
}));

import { nativeSecureSessionStorage } from "@/lib/secure-session-storage";

function setNative(native: boolean): void {
  if (native) {
    (window as unknown as { Capacitor?: unknown }).Capacitor = {};
  } else {
    delete (window as unknown as { Capacitor?: unknown }).Capacitor;
  }
}

describe("nativeSecureSessionStorage", () => {
  afterEach(() => {
    setNative(false);
    vi.clearAllMocks();
    vi.restoreAllMocks();
  });

  // --- Native platform: calls actually reach the plugin -------------------

  describe("inside the Capacitor native app", () => {
    it("getItem forwards to SecureStorage.getItem and returns its result", async () => {
      setNative(true);
      secureStorageMock.getItem.mockResolvedValue("the-refresh-token");

      const result = await nativeSecureSessionStorage.getItem("supabase.session");

      expect(result).toBe("the-refresh-token");
      expect(secureStorageMock.getItem).toHaveBeenCalledWith("supabase.session");
    });

    it("setItem forwards to SecureStorage.setItem", async () => {
      setNative(true);
      secureStorageMock.setItem.mockResolvedValue(undefined);

      await nativeSecureSessionStorage.setItem("supabase.session", "the-refresh-token");

      expect(secureStorageMock.setItem).toHaveBeenCalledWith(
        "supabase.session",
        "the-refresh-token"
      );
    });

    it("removeItem forwards to SecureStorage.removeItem", async () => {
      setNative(true);
      secureStorageMock.removeItem.mockResolvedValue(undefined);

      await nativeSecureSessionStorage.removeItem("supabase.session");

      expect(secureStorageMock.removeItem).toHaveBeenCalledWith("supabase.session");
    });

    it("propagates a plugin failure as a rejection rather than swallowing it", async () => {
      setNative(true);
      const pluginError = new Error("Keychain unavailable");
      secureStorageMock.getItem.mockRejectedValue(pluginError);

      await expect(nativeSecureSessionStorage.getItem("supabase.session")).rejects.toThrow(
        "Keychain unavailable"
      );
    });
  });

  // --- Non-native (web/PWA): must never reach the plugin's own localStorage
  //     fallback, and must never touch localStorage/sessionStorage itself --

  describe("outside the Capacitor native app (web/PWA)", () => {
    it("getItem throws instead of falling back to any other storage", async () => {
      setNative(false);

      await expect(nativeSecureSessionStorage.getItem("supabase.session")).rejects.toThrow(
        /native-only/i
      );
      expect(secureStorageMock.getItem).not.toHaveBeenCalled();
    });

    it("setItem throws instead of falling back to any other storage", async () => {
      setNative(false);

      await expect(
        nativeSecureSessionStorage.setItem("supabase.session", "the-refresh-token")
      ).rejects.toThrow(/native-only/i);
      expect(secureStorageMock.setItem).not.toHaveBeenCalled();
    });

    it("removeItem throws instead of falling back to any other storage", async () => {
      setNative(false);

      await expect(nativeSecureSessionStorage.removeItem("supabase.session")).rejects.toThrow(
        /native-only/i
      );
      expect(secureStorageMock.removeItem).not.toHaveBeenCalled();
    });

    it("never writes, reads, or removes anything via localStorage or sessionStorage", async () => {
      setNative(false);
      const localGet = vi.spyOn(Storage.prototype, "getItem");
      const localSet = vi.spyOn(Storage.prototype, "setItem");
      const localRemove = vi.spyOn(Storage.prototype, "removeItem");

      await Promise.allSettled([
        nativeSecureSessionStorage.getItem("supabase.session"),
        nativeSecureSessionStorage.setItem("supabase.session", "the-refresh-token"),
        nativeSecureSessionStorage.removeItem("supabase.session"),
      ]);

      expect(localGet).not.toHaveBeenCalled();
      expect(localSet).not.toHaveBeenCalled();
      expect(localRemove).not.toHaveBeenCalled();
    });
  });
});
