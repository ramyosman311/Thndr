#!/usr/bin/env node
/**
 * Wraps `next build` for the Capacitor static-export target (P0-2 follow-up).
 *
 * app/api/[...path]/route.ts (the server-side auth proxy added for the
 * web/PWA build) is incompatible with `output: "export"` -- Next.js
 * refuses to statically export any Route Handler that relies on the
 * Request object (arbitrary method/body/headers), which a forwarding
 * proxy inherently does. The Capacitor native shell never uses this
 * proxy anyway: it ships with no server of its own and always calls the
 * backend directly via an explicit NEXT_PUBLIC_API_BASE_URL -- see
 * lib/capacitor-build-guard.ts. So for this one build only, the route is
 * excluded rather than adapted.
 *
 * This moves app/api out of app/ before running `next build` with
 * BUILD_TARGET=capacitor, and always moves it back afterward -- on
 * success, on a build failure, or on Ctrl-C -- so the working tree is
 * never left missing a real, version-controlled source file.
 */
import { existsSync, renameSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const apiDir = join(root, "app", "api");
const excludedDir = join(root, ".capacitor-build-excluded-api");

let restored = false;
function restore() {
  if (restored) return;
  restored = true;
  if (existsSync(excludedDir) && !existsSync(apiDir)) {
    renameSync(excludedDir, apiDir);
  }
}

process.on("exit", restore);
process.on("SIGINT", () => process.exit(130));
process.on("SIGTERM", () => process.exit(143));

if (!existsSync(apiDir)) {
  console.error(`Expected ${apiDir} to exist -- nothing to exclude. Aborting.`);
  process.exit(1);
}
renameSync(apiDir, excludedDir);

const result = spawnSync("npx", ["next", "build"], {
  stdio: "inherit",
  env: { ...process.env, BUILD_TARGET: "capacitor" },
  shell: process.platform === "win32",
});

process.exit(result.status ?? 1);
