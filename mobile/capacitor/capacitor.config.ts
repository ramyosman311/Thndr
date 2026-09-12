import type { CapacitorConfig } from "@capacitor/cli";

/**
 * MIZAN native app shell (Phase 22). Capacitor wraps the frontend's static
 * export in a WebView -- it is not a second frontend and does not run a
 * server. FastAPI + PostgreSQL stay server-side; the native app reaches
 * FastAPI over HTTPS via NEXT_PUBLIC_API_BASE_URL, baked in at
 * `npm run build:capacitor` time (see frontend/next.config.ts and
 * DEPLOYMENT.md, "Capacitor Native Builds").
 *
 * App ID `com.mizan.app`: this project has no prior published app-store
 * listing or reserved identifier, so this is a new, deliberately chosen,
 * documented identifier (not "com.thndr.*" -- README.md is explicit that
 * MIZAN is "an independent, standalone product", inspired by but not
 * affiliated with Thndr). See DECISIONS.md, "Phase 22 — Capacitor Native
 * Wrappers" for the full rationale. Treat this as stable once any build
 * is distributed: an app's package name/bundle ID cannot change after its
 * first store release without becoming a new listing.
 */
const config: CapacitorConfig = {
  appId: "com.mizan.app",
  appName: "MIZAN",
  // The frontend's static export (`npm run build:capacitor` in
  // frontend/, output: "export" -- see frontend/next.config.ts). Not
  // committed; generated before `cap sync`.
  webDir: "../../frontend/out",
  // No `server.url`: the app ships the bundled static export as its
  // web content rather than loading a remote page, per this phase's
  // "native shell + bundled frontend + remote HTTPS API" architecture.
  // `androidScheme: "https"` (Capacitor's documented recommendation)
  // gives the bundled content a secure origin so browser APIs that
  // require one (e.g. service workers, if ever re-enabled here) behave
  // the same as they would on a real HTTPS-served PWA.
  server: {
    androidScheme: "https",
  },
  android: {
    // Explicit and matching the platform default for a targetSdk >= 28
    // app: never allow plaintext HTTP in the shipped app. Local HTTP
    // development against an emulator is handled by a separate,
    // git-ignored dev override -- see DEPLOYMENT.md, "Capacitor local
    // device/emulator development" -- never by relaxing this default.
    allowMixedContent: false,
  },
};

export default config;
