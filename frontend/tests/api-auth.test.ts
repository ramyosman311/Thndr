import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  getAccessToken: vi.fn(),
  refreshAccessToken: vi.fn(),
}));

vi.mock("@/lib/supabase", () => mocks);

import { api } from "@/lib/api";

const fetchMock = vi.fn();

beforeEach(() => {
  vi.resetAllMocks();
  vi.stubGlobal("fetch", fetchMock);
});

function ok(body: unknown = []) {
  return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
}

function authHeader(call: number): string | undefined {
  const init = fetchMock.mock.calls[call][1] as { headers: Record<string, string> };
  return init.headers.Authorization;
}

describe("api requests carry the Supabase JWT", () => {
  it("sends Authorization: Bearer <access token>", async () => {
    mocks.getAccessToken.mockResolvedValue("jwt-1");
    fetchMock.mockResolvedValue(ok());
    await api.listNotifications();
    expect(authHeader(0)).toBe("Bearer jwt-1");
  });

  it("sends no Authorization header when signed out", async () => {
    mocks.getAccessToken.mockResolvedValue(null);
    fetchMock.mockResolvedValue(ok());
    await api.listNotifications();
    expect(authHeader(0)).toBeUndefined();
  });

  it("refreshes once on 401 and retries with the new token", async () => {
    mocks.getAccessToken.mockResolvedValue("old");
    mocks.refreshAccessToken.mockResolvedValue("new");
    fetchMock.mockResolvedValueOnce(new Response("{}", { status: 401 })).mockResolvedValueOnce(ok());
    await api.listNotifications();
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(authHeader(0)).toBe("Bearer old");
    expect(authHeader(1)).toBe("Bearer new");
  });

  it("does not loop: a second 401 after refresh is surfaced as an error", async () => {
    mocks.getAccessToken.mockResolvedValue("old");
    mocks.refreshAccessToken.mockResolvedValue("new");
    fetchMock.mockResolvedValue(new Response("{}", { status: 401 }));
    await expect(api.listNotifications()).rejects.toBeTruthy();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("surfaces the 401 without retry when no refresh is possible", async () => {
    mocks.getAccessToken.mockResolvedValue("old");
    mocks.refreshAccessToken.mockResolvedValue(null);
    fetchMock.mockResolvedValue(new Response("{}", { status: 401 }));
    await expect(api.listNotifications()).rejects.toBeTruthy();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
