import { describe, expect, it, afterEach, vi } from "vitest";
import { render, cleanup } from "@testing-library/react";
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { assertCapacitorApiBaseUrlIsSafe } from "@/lib/capacitor-build-guard";
import { isNativeApp } from "@/lib/capacitor-env";
import { ServiceWorkerRegistration } from "@/components/service-worker-registration";

// --- D: production API configuration never uses a dev/Codespace URL -------

describe("assertCapacitorApiBaseUrlIsSafe", () => {
  it("rejects a missing URL", () => {
    expect(() => assertCapacitorApiBaseUrlIsSafe(undefined)).toThrow(/NEXT_PUBLIC_API_BASE_URL to be set/);
  });

  it("rejects the relative web/PWA default", () => {
    expect(() => assertCapacitorApiBaseUrlIsSafe("/api")).toThrow(/must be an HTTPS URL/);
  });

  it("rejects a plain HTTP URL", () => {
    expect(() => assertCapacitorApiBaseUrlIsSafe("http://api.example.com/api")).toThrow(/must be an HTTPS URL/);
  });

  it("rejects an ephemeral Codespace preview URL even over HTTPS", () => {
    expect(() =>
      assertCapacitorApiBaseUrlIsSafe("https://potential-guacamole-4jjr4v7gwxwwh74vg-3000.app.github.dev/api")
    ).toThrow(/ephemeral Codespace/);
  });

  it("rejects other ephemeral cloud-IDE preview domains", () => {
    expect(() => assertCapacitorApiBaseUrlIsSafe("https://foo.githubpreview.dev/api")).toThrow(/ephemeral Codespace/);
    expect(() => assertCapacitorApiBaseUrlIsSafe("https://foo.gitpod.io/api")).toThrow(/ephemeral Codespace/);
  });

  it("accepts a durable HTTPS URL", () => {
    expect(() => assertCapacitorApiBaseUrlIsSafe("https://api.mizan.example.com/api")).not.toThrow();
  });

  it("allows plain HTTP only for an emulator loopback address, and only when explicitly opted in", () => {
    expect(() => assertCapacitorApiBaseUrlIsSafe("http://10.0.2.2:8000/api")).toThrow(/must be an HTTPS URL/);
    expect(() =>
      assertCapacitorApiBaseUrlIsSafe("http://10.0.2.2:8000/api", { allowInsecure: true })
    ).not.toThrow();
  });

  it("does not let allowInsecure bypass HTTPS for a non-loopback host", () => {
    expect(() =>
      assertCapacitorApiBaseUrlIsSafe("http://api.example.com/api", { allowInsecure: true })
    ).toThrow(/must be an HTTPS URL/);
  });
});

// --- G/H: Capacitor detection stays inert on the web ---------------------

describe("isNativeApp", () => {
  afterEach(() => {
    delete (window as unknown as { Capacitor?: unknown }).Capacitor;
  });

  it("is false in a plain browser/PWA context (no window.Capacitor)", () => {
    expect(isNativeApp()).toBe(false);
  });

  it("is true once Capacitor's runtime bridge injects window.Capacitor", () => {
    (window as unknown as { Capacitor?: unknown }).Capacitor = {};
    expect(isNativeApp()).toBe(true);
  });
});

describe("ServiceWorkerRegistration inside the native shell", () => {
  afterEach(() => {
    delete (window as unknown as { Capacitor?: unknown }).Capacitor;
    cleanup();
    vi.unstubAllGlobals();
  });

  it("never registers the service worker when window.Capacitor is present", () => {
    (window as unknown as { Capacitor?: unknown }).Capacitor = {};
    const register = vi.fn().mockResolvedValue({ waiting: null, active: null, addEventListener: vi.fn() });
    vi.stubGlobal("navigator", {
      ...navigator,
      serviceWorker: { register, addEventListener: vi.fn(), removeEventListener: vi.fn() },
    });

    const { container } = render(<ServiceWorkerRegistration />);

    expect(register).not.toHaveBeenCalled();
    expect(container).toBeEmptyDOMElement();
  });
});

// --- E: no backend secrets ever referenced from frontend source ----------

describe("Frontend source never references backend-only secrets", () => {
  const forbidden = [
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "DATABASE_URL",
    "DATABASE_URL_SYNC",
    "SECRET_KEY",
    "SUPABASE_SERVICE_ROLE_KEY",
    "MARKET_DATA_API_KEY",
  ];

  function sourceFiles(dir: string, out: string[] = []): string[] {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      if (entry.name === "node_modules" || entry.name === ".next" || entry.name === "out") continue;
      const full = join(dir, entry.name);
      if (entry.isDirectory()) {
        sourceFiles(full, out);
      } else if (/\.(ts|tsx|js|mjs)$/.test(entry.name)) {
        out.push(full);
      }
    }
    return out;
  }

  it("contains none of the backend-only environment variable names", () => {
    const root = process.cwd();
    const files = [
      ...sourceFiles(join(root, "app")),
      ...sourceFiles(join(root, "components")),
      ...sourceFiles(join(root, "lib")),
      ...sourceFiles(join(root, "hooks")),
    ];
    for (const file of files) {
      const content = readFileSync(file, "utf-8");
      for (const secret of forbidden) {
        expect(content, `${file} must not reference ${secret}`).not.toContain(secret);
      }
    }
  });

  it("only ever reads NEXT_PUBLIC_API_BASE_URL from process.env", () => {
    const root = process.cwd();
    const files = [
      ...sourceFiles(join(root, "app")),
      ...sourceFiles(join(root, "components")),
      ...sourceFiles(join(root, "lib")),
      ...sourceFiles(join(root, "hooks")),
    ];
    const envReads: string[] = [];
    for (const file of files) {
      const content = readFileSync(file, "utf-8");
      const matches = content.match(/process\.env\.(\w+)/g) ?? [];
      envReads.push(...matches);
    }
    const unique = [...new Set(envReads)];
    expect(unique).toEqual(["process.env.NEXT_PUBLIC_API_BASE_URL"]);
  });
});

// --- H: API requests stay network-authoritative regardless of platform ---

describe("lib/api.ts stays network-authoritative", () => {
  it("still sends every request with cache: no-store", () => {
    const source = readFileSync(join(process.cwd(), "lib", "api.ts"), "utf-8");
    expect(source).toContain('cache: "no-store"');
  });
});
