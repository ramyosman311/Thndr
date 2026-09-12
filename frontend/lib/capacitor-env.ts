/**
 * True when running inside the Capacitor native shell (Android/iOS),
 * false in a normal browser or installed-PWA context. Capacitor injects a
 * `window.Capacitor` global into the WebView at runtime, so this needs no
 * dependency on `@capacitor/core` -- the native shell only bundles this
 * app's static export (see mobile/capacitor/), it does not build against
 * the frontend package, so the frontend cannot import Capacitor APIs
 * directly. See DECISIONS.md, "Phase 22 — Capacitor Native Wrappers".
 */
export function isNativeApp(): boolean {
  if (typeof window === "undefined") return false;
  return Boolean((window as unknown as { Capacitor?: unknown }).Capacitor);
}
