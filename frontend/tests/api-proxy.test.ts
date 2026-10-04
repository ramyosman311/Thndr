// @vitest-environment node
/**
 * P0-3C: the server-side proxy (app/api/[...path]/route.ts) forwards the
 * user's Supabase JWT untouched and adds the server-only internal token --
 * and never lets a browser supply or learn that token.
 */
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";


// Loaded through a non-literal specifier on purpose: the Capacitor static-export
// build temporarily moves app/api out of the tree (see scripts/build-capacitor.mjs)
// while `next build` type-checks every tests/**/*.ts, so a literal import of the
// route module would fail that build. Vitest resolves it at runtime as normal.
const ROUTE_PATH = "../app/api/[...path]/route";
type RouteHandler = (request: NextRequest, ctx: { params: Promise<{ path: string[] }> }) => Promise<Response>;
let GET: RouteHandler;
let POST: RouteHandler;

beforeAll(async () => {
  const route = await import(/* @vite-ignore */ ROUTE_PATH);
  GET = route.GET;
  POST = route.POST;
});

const USER_JWT = "header.payload.signature";

let upstreamHeaders: Headers;
let upstreamUrl: string;

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: { headers: Headers }) => {
      upstreamUrl = url;
      upstreamHeaders = init.headers;
      return new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    })
  );
  vi.stubEnv("BACKEND_API_URL", "https://backend.example/api");
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

function request(headers: Record<string, string> = {}, method = "GET") {
  return new NextRequest("http://localhost/api/portfolio/summary?x=1", { method, headers });
}

const ctx = { params: Promise.resolve({ path: ["portfolio", "summary"] }) };

describe("api proxy header handling", () => {
  it("forwards the user's Authorization (Supabase JWT) unchanged", async () => {
    vi.stubEnv("API_AUTH_TOKEN", "server-only-secret");
    await GET(request({ authorization: `Bearer ${USER_JWT}` }), ctx);

    expect(upstreamHeaders.get("authorization")).toBe(`Bearer ${USER_JWT}`);
    expect(upstreamUrl).toBe("https://backend.example/api/portfolio/summary?x=1");
  });

  it("never sends API_AUTH_TOKEN as the Authorization credential", async () => {
    vi.stubEnv("API_AUTH_TOKEN", "server-only-secret");
    await GET(request(), ctx);

    expect(upstreamHeaders.get("authorization")).toBeNull();
    expect(upstreamHeaders.get("authorization") ?? "").not.toContain("server-only-secret");
  });

  it("adds the server-only token as X-Internal-Proxy-Token", async () => {
    vi.stubEnv("API_AUTH_TOKEN", "server-only-secret");
    await GET(request({ authorization: `Bearer ${USER_JWT}` }), ctx);

    expect(upstreamHeaders.get("x-internal-proxy-token")).toBe("server-only-secret");
  });

  it("drops an X-Internal-Proxy-Token supplied by the browser", async () => {
    vi.stubEnv("API_AUTH_TOKEN", "server-only-secret");
    await GET(
      request({ authorization: `Bearer ${USER_JWT}`, "x-internal-proxy-token": "attacker-guess" }),
      ctx
    );

    expect(upstreamHeaders.get("x-internal-proxy-token")).toBe("server-only-secret");
  });

  it("does not forward a browser-supplied internal token when none is configured", async () => {
    vi.stubEnv("API_AUTH_TOKEN", "");
    await GET(request({ "x-internal-proxy-token": "attacker-guess" }), ctx);

    expect(upstreamHeaders.get("x-internal-proxy-token")).toBeNull();
  });

  it("sends no internal token when API_AUTH_TOKEN is unset (local dev)", async () => {
    vi.stubEnv("API_AUTH_TOKEN", "");
    await GET(request({ authorization: `Bearer ${USER_JWT}` }), ctx);

    expect(upstreamHeaders.get("x-internal-proxy-token")).toBeNull();
    expect(upstreamHeaders.get("authorization")).toBe(`Bearer ${USER_JWT}`);
  });

  it("never exposes the internal token in the response to the browser", async () => {
    vi.stubEnv("API_AUTH_TOKEN", "server-only-secret");
    const response = await POST(
      new NextRequest("http://localhost/api/transactions", {
        method: "POST",
        body: JSON.stringify({}),
        headers: { authorization: `Bearer ${USER_JWT}`, "content-type": "application/json" },
      }),
      { params: Promise.resolve({ path: ["transactions"] }) }
    );

    expect(response.headers.get("x-internal-proxy-token")).toBeNull();
    expect(await response.text()).not.toContain("server-only-secret");
  });
});
