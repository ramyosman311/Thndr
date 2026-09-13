import type { NextConfig } from "next";
import { assertCapacitorApiBaseUrlIsSafe } from "./lib/capacitor-build-guard";

const isCapacitorBuild = process.env.BUILD_TARGET === "capacitor";

if (isCapacitorBuild) {
  assertCapacitorApiBaseUrlIsSafe(process.env.NEXT_PUBLIC_API_BASE_URL, {
    allowInsecure: process.env.ALLOW_INSECURE_CAPACITOR_API === "1",
  });
}

const nextConfig: NextConfig = isCapacitorBuild
  ? {
      // Capacitor bundles this output directly (see
      // mobile/capacitor/capacitor.config.ts, webDir) -- there is no
      // server at runtime to serve pages or run app/api/[...path]/route.ts
      // below, so a static export is the only compatible output mode.
      output: "export",
    }
  : {
      // /api/* is handled by app/api/[...path]/route.ts (P0-2) -- a real
      // filesystem route always takes precedence over a plain-array
      // rewrite here, so a rewrite for the same path would be dead code.
    };

export default nextConfig;
