/**
 * Build-time safety guard for Capacitor native builds (Phase 22). Pulled
 * out of next.config.ts as a plain, testable function -- see
 * tests/capacitor.test.ts.
 *
 * The Capacitor native shell ships with no server -- it bundles whatever
 * `next build` produces and loads it straight from disk inside a WebView.
 * A relative "/api" base URL (this app's normal web/PWA default, proxied
 * by next.config.ts's rewrite) would resolve to nothing there, so a
 * Capacitor build must be given an explicit, reachable, durable FastAPI
 * base URL. This throws rather than silently shipping a native app that
 * can never reach its backend -- see DEPLOYMENT.md, "Capacitor Native
 * Builds" and DECISIONS.md, "Phase 22 — Capacitor Native Wrappers".
 */
export function assertCapacitorApiBaseUrlIsSafe(
  url: string | undefined,
  options: { allowInsecure?: boolean } = {}
): void {
  if (!url) {
    throw new Error(
      'BUILD_TARGET=capacitor requires NEXT_PUBLIC_API_BASE_URL to be set to the ' +
        'production FastAPI base URL (e.g. "https://api.example.com/api"). The native ' +
        'app bundles static files with no server behind them, so the default relative ' +
        '"/api" (which only works because the web build\'s dev/production Next.js ' +
        "server rewrites it to FastAPI) cannot resolve inside the app. See " +
        'DEPLOYMENT.md, "Capacitor Native Builds".'
    );
  }

  const isEmulatorLoopback = /^http:\/\/(localhost|127\.0\.0\.1|10\.0\.2\.2)(:\d+)?/.test(url);
  if (!url.startsWith("https://") && !(options.allowInsecure && isEmulatorLoopback)) {
    throw new Error(
      `NEXT_PUBLIC_API_BASE_URL must be an HTTPS URL for a Capacitor build (got "${url}"). ` +
        "Set ALLOW_INSECURE_CAPACITOR_API=1 only for local emulator/device development " +
        'against an unencrypted dev backend (e.g. "http://10.0.2.2:8000/api" from the ' +
        "Android emulator) -- never for a distributed build."
    );
  }

  if (/\.app\.github\.dev|\.githubpreview\.dev|\.gitpod\.io/i.test(url)) {
    throw new Error(
      `NEXT_PUBLIC_API_BASE_URL looks like an ephemeral Codespace/cloud-IDE preview URL ` +
        `("${url}"). That URL stops resolving once this session ends, so it cannot be a ` +
        'production mobile-app dependency. Deploy FastAPI somewhere durable first -- see ' +
        'DEPLOYMENT.md.'
    );
  }
}
