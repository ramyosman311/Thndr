/**
 * Server-side proxy to the FastAPI backend (P0-2).
 *
 * The browser only ever calls this Next.js app's own origin at a relative
 * `/api/...` path (see lib/api.ts, unchanged) -- this Route Handler runs
 * on Vercel's server, forwards the request to BACKEND_API_URL, and
 * attaches `Authorization: Bearer ${API_AUTH_TOKEN}` itself. Neither env
 * var is ever read by client code or prefixed NEXT_PUBLIC_, so the token
 * is never present in anything shipped to the browser.
 *
 * Local development: both env vars are typically unset. BACKEND_API_URL
 * then falls back to the co-located dev backend at 127.0.0.1:8000, and
 * since that backend runs with DEV_MODE=true it doesn't require a token
 * anyway -- see app/core/auth.py on the backend.
 *
 * This does not apply to a Capacitor native build (BUILD_TARGET=capacitor,
 * see next.config.ts): that ships as a static export with no server of
 * its own, so it still calls the backend directly using an explicit
 * NEXT_PUBLIC_API_BASE_URL -- see lib/capacitor-build-guard.ts. This file
 * is never reachable from that build (a static export can't include a
 * dynamic Route Handler like this one).
 *
 * Migration to Supabase Auth later: this file stops injecting a shared
 * secret and instead forwards the signed-in user's real session token
 * instead -- the browser-to-proxy-to-backend shape doesn't change. See
 * DEPLOYMENT.md, "Authentication".
 */
import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";

const DEV_FALLBACK_BACKEND_URL = "http://127.0.0.1:8000/api";

// Never forwarded from the incoming request: hop-by-hop/framing headers
// that don't make sense to replay verbatim, and any Authorization a
// (untrusted) client might have sent -- this proxy always sets its own.
const SKIPPED_REQUEST_HEADERS = new Set(["host", "connection", "content-length", "authorization"]);

function buildForwardHeaders(request: NextRequest): Headers {
  const headers = new Headers();
  request.headers.forEach((value, key) => {
    if (!SKIPPED_REQUEST_HEADERS.has(key.toLowerCase())) {
      headers.set(key, value);
    }
  });

  const token = process.env.API_AUTH_TOKEN;
  if (token) {
    headers.set("authorization", `Bearer ${token}`);
  }

  return headers;
}

async function forward(request: NextRequest, path: string[]): Promise<NextResponse> {
  const backendBaseUrl = process.env.BACKEND_API_URL || DEV_FALLBACK_BACKEND_URL;
  const targetUrl = `${backendBaseUrl}/${path.join("/")}${request.nextUrl.search}`;

  const hasBody = request.method !== "GET" && request.method !== "HEAD";

  let response: Response;
  try {
    response = await fetch(targetUrl, {
      method: request.method,
      headers: buildForwardHeaders(request),
      body: hasBody ? await request.arrayBuffer() : undefined,
      cache: "no-store",
    });
  } catch {
    return NextResponse.json({ detail: "Unable to reach the backend service." }, { status: 502 });
  }

  // Only Content-Type is replayed -- Content-Encoding/Content-Length/
  // Transfer-Encoding describe the wire representation `fetch` already
  // decoded away when producing this ArrayBuffer, so copying them
  // verbatim would mislabel the response actually being sent.
  const responseHeaders = new Headers();
  const contentType = response.headers.get("content-type");
  if (contentType) {
    responseHeaders.set("content-type", contentType);
  }

  const body = await response.arrayBuffer();
  return new NextResponse(body, { status: response.status, headers: responseHeaders });
}

type RouteContext = { params: Promise<{ path: string[] }> };

export async function GET(request: NextRequest, ctx: RouteContext) {
  return forward(request, (await ctx.params).path);
}

export async function POST(request: NextRequest, ctx: RouteContext) {
  return forward(request, (await ctx.params).path);
}

export async function PUT(request: NextRequest, ctx: RouteContext) {
  return forward(request, (await ctx.params).path);
}

export async function PATCH(request: NextRequest, ctx: RouteContext) {
  return forward(request, (await ctx.params).path);
}

export async function DELETE(request: NextRequest, ctx: RouteContext) {
  return forward(request, (await ctx.params).path);
}
