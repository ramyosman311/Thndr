/**
 * OS-backed secure storage for Supabase session/refresh-token state,
 * for the Capacitor native app ONLY (P0-3 — see DECISIONS.md, "P0-3
 * Secure Storage" for the full audit and package-selection rationale).
 *
 * Backed by @aparajita/capacitor-secure-storage: iOS Keychain, Android
 * Keystore-backed AES-GCM encryption under a plain SharedPreferences
 * file (never EncryptedSharedPreferences for this specific package --
 * confirmed during the P0-3 audit).
 *
 * SECURITY -- read before touching this file: the plugin ships its own
 * web implementation (its own `web.ts`) that silently falls back to
 * plain `localStorage` when not running natively. That is exactly the
 * plaintext fallback this phase exists to forbid for a session secret.
 * `assertNativePlatform()` below is what stands between every exported
 * function and that fallback -- it throws rather than ever letting a
 * call reach the plugin's web path. Never wrap these functions in a
 * try/catch that redirects to localStorage/sessionStorage/
 * @capacitor/preferences on failure; a thrown error here must propagate,
 * not be swallowed into a weaker storage mechanism.
 *
 * Nothing in this codebase constructs a Supabase client yet (no
 * @supabase/supabase-js dependency exists) -- `nativeSecureSessionStorage`
 * is shaped to match supabase-js's own `SupportedStorage` interface
 * (getItem/setItem/removeItem) so it can be passed directly as
 * `createClient(url, key, { auth: { storage: nativeSecureSessionStorage } } )`
 * once that client is introduced, without this file changing.
 */
import { SecureStorage } from "@aparajita/capacitor-secure-storage";
import { isNativeApp } from "@/lib/capacitor-env";

function assertNativePlatform(): void {
  if (!isNativeApp()) {
    throw new Error(
      "nativeSecureSessionStorage was called outside the Capacitor native app. " +
        'This storage is native-only by design -- see DECISIONS.md, "P0-3 Secure Storage" -- ' +
        "and must never fall back to localStorage/sessionStorage for a session secret."
    );
  }
}

export const nativeSecureSessionStorage = {
  async getItem(key: string): Promise<string | null> {
    assertNativePlatform();
    return SecureStorage.getItem(key);
  },

  async setItem(key: string, value: string): Promise<void> {
    assertNativePlatform();
    await SecureStorage.setItem(key, value);
  },

  async removeItem(key: string): Promise<void> {
    assertNativePlatform();
    await SecureStorage.removeItem(key);
  },
};
