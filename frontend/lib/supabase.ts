/**
 * Browser Supabase client (P0-3D, Web personal beta).
 *
 * Uses Supabase's standard Web session handling (access + refresh token kept
 * by supabase-js in the browser's storage, access token auto-refreshed). The
 * URL and the ANON key are PUBLIC by design (they ship to every browser; row
 * access is governed by the backend verifying the user's JWT, never by these).
 * Nothing secret is read here: not API_AUTH_TOKEN, not the service-role key.
 *
 * The client is created lazily and only when both public values exist, so a
 * build or test without them (e.g. the Capacitor static export, which is out
 * of scope for this phase) never throws at import time.
 */
import { createClient, type SupabaseClient } from "@supabase/supabase-js";

let client: SupabaseClient | null | undefined;

export function getSupabase(): SupabaseClient | null {
  if (client !== undefined) return client;
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  client =
    url && anonKey
      ? createClient(url, anonKey, { auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: false } })
      : null;
  return client;
}

/** The current access token (JWT), refreshed first if it is about to expire;
 * null when signed out or when auth is not configured. */
export async function getAccessToken(): Promise<string | null> {
  const supabase = getSupabase();
  if (!supabase) return null;
  const { data } = await supabase.auth.getSession();
  return data.session?.access_token ?? null;
}

/** Forces a refresh (used once after a 401, e.g. a token revoked or expired
 * between getSession() and the request). Returns the new token or null. */
export async function refreshAccessToken(): Promise<string | null> {
  const supabase = getSupabase();
  if (!supabase) return null;
  const { data, error } = await supabase.auth.refreshSession();
  return error ? null : (data.session?.access_token ?? null);
}
