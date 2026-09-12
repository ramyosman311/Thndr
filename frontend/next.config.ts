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
      // server at runtime to serve pages or run the API rewrite below,
      // so a static export is the only compatible output mode.
      output: "export",
    }
  : {
      async rewrites() {
        return [
          {
            source: "/api/:path*",
            destination: "http://127.0.0.1:8000/api/:path*",
          },
        ];
      },
    };

export default nextConfig;
