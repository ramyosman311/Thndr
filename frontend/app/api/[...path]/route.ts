/**
 * Server-side proxy to the FastAPI backend (P0-2, updated P0-3C).
 *
 * The browser only ever calls this Next.js app's own origin at a relative
 * `/api/...` path (see lib/api.ts) -- this Route Handler runs on Vercel's
 * server and forwards the request to BACKEND_API_URL.
 *
 * Two distinct credentials, never confused:
 *   - `Authorization: Bearer <Supabase JWT>` is the USER's identity. It is
 *     forwarded exactly as the browser sent it; the backend verifies it
 *     cryptographically and derives the user (and so every ownership
 *     decision) from it. This proxy never inspects, mints, or replaces it.
 *   - `X-Internal-Proxy-Token: ${API_AUTH_TOKEN}` is a server-to-server
 *     trust signal added HERE. It is not identity and can never stand in
 *     for the JWT -- the backend still requires a valid JWT either way.
 *     API_AUTH_TOKEN is only ever read in this server-side file (never
 *     NEXT_PUBLIC_, never bundled for the browser), and any
 *     `X-Internal-Proxy-Token` a browser tries to send is dropped, so a
 *     client can neither read nor supply it.
 *
 * Local development: both env vars are typically unset. BACKEND_API_URL
 * then falls back to the co-located dev backend at 127.0.0.1:8000, and no
 * internal token is sent (it is optional on the backend).
 *
 * This does not apply to a Capacitor native build (BUILD_TARGET=capacitor,
 * see next.config.ts): that ships as a static export with no server of
 * its own, so it calls the backend directly with only the user's
 * `Authorization: Bearer <Supabase JWT>` -- it never has, and must never
 * have, API_AUTH_TOKEN. This file is never reachable from that build (a
 * static export can't include a dynamic Route Handler like this one).
 */
import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";

const DEV_FALLBACK_BACKEND_URL = "http://127.0.0.1:8000/api";

// Never forwarded from the incoming request: hop-by-hop/framing headers
// that don't make sense to replay verbatim, and any internal-proxy token a
// (untrusted) client might have sent -- only this server may set that one.
// `authorization` is deliberately NOT skipped: it is the user's own Supabase
// JWT and must reach the backend untouched.
const SKIPPED_REQUEST_HEADERS = new Set(["host", "connection", "content-length", "x-internal-proxy-token"]);

function buildForwardHeaders(request: NextRequest): Headers {
  const headers = new Headers();
  request.headers.forEach((value, key) => {
    if (!SKIPPED_REQUEST_HEADERS.has(key.toLowerCase())) {
      headers.set(key, value);
    }
  });

  const internalToken = process.env.API_AUTH_TOKEN;
  if (internalToken) {
    headers.set("x-internal-proxy-token", internalToken);
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
