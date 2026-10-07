import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

type AuthCallback = (event: string, session: unknown) => void;

const mocks = vi.hoisted(() => ({
  getSession: vi.fn(),
  signInWithPassword: vi.fn(),
  signOut: vi.fn(),
  onAuthStateChange: vi.fn(),
  getSupabase: vi.fn(),
  unsubscribe: vi.fn(),
  callback: null as null | ((event: string, session: unknown) => void),
}));

vi.mock("@/lib/supabase", () => ({ getSupabase: mocks.getSupabase }));

import { AuthGate, LogoutButton } from "@/components/auth-gate";

const SESSION = { access_token: "jwt", user: { id: "u1" } };

function App() {
  return (
    <AuthGate>
      <div data-testid="protected">portfolio data</div>
      <LogoutButton />
    </AuthGate>
  );
}

beforeEach(() => {
  vi.resetAllMocks();
  mocks.callback = null;
  mocks.onAuthStateChange.mockImplementation((cb: AuthCallback) => {
    mocks.callback = cb;
    return { data: { subscription: { unsubscribe: mocks.unsubscribe } } };
  });
  mocks.getSupabase.mockReturnValue({
    auth: {
      getSession: mocks.getSession,
      signInWithPassword: mocks.signInWithPassword,
      signOut: mocks.signOut,
      onAuthStateChange: mocks.onAuthStateChange,
    },
  });
});

describe("AuthGate", () => {
  it("renders nothing protected while the session is loading", () => {
    mocks.getSession.mockReturnValue(new Promise(() => {}));
    render(<App />);
    expect(screen.queryByTestId("protected")).toBeNull();
  });

  it("shows the login form and mounts no children when signed out", async () => {
    mocks.getSession.mockResolvedValue({ data: { session: null } });
    render(<App />);
    expect(await screen.findByRole("form", { name: "تسجيل الدخول" })).toBeInTheDocument();
    expect(screen.queryByTestId("protected")).toBeNull();
  });

  it("shows an unconfigured notice, never the app, when Supabase is not configured", async () => {
    mocks.getSupabase.mockReturnValue(null);
    render(<App />);
    expect(await screen.findByText(/غير مُهيّأ/)).toBeInTheDocument();
    expect(screen.queryByTestId("protected")).toBeNull();
  });

  it("renders the app when a session exists", async () => {
    mocks.getSession.mockResolvedValue({ data: { session: SESSION } });
    render(<App />);
    expect(await screen.findByTestId("protected")).toBeInTheDocument();
  });

  it("signs in with email and password, then shows the app", async () => {
    mocks.getSession.mockResolvedValue({ data: { session: null } });
    mocks.signInWithPassword.mockImplementation(async () => {
      mocks.callback?.("SIGNED_IN", SESSION);
      return { error: null };
    });
    render(<App />);
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("البريد الإلكتروني"), "me@example.com");
    await user.type(screen.getByLabelText("كلمة المرور"), "secret-pass");
    await user.click(screen.getByRole("button", { name: "دخول" }));

    expect(mocks.signInWithPassword).toHaveBeenCalledWith({ email: "me@example.com", password: "secret-pass" });
    expect(await screen.findByTestId("protected")).toBeInTheDocument();
  });

  it("shows one generic error on invalid credentials and stays signed out", async () => {
    mocks.getSession.mockResolvedValue({ data: { session: null } });
    mocks.signInWithPassword.mockResolvedValue({ error: { message: "Invalid login credentials" } });
    render(<App />);
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("البريد الإلكتروني"), "me@example.com");
    await user.type(screen.getByLabelText("كلمة المرور"), "wrong");
    await user.click(screen.getByRole("button", { name: "دخول" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("البريد الإلكتروني أو كلمة المرور غير صحيحة.");
    expect(alert).not.toHaveTextContent("Invalid login credentials");
    expect(screen.queryByTestId("protected")).toBeNull();
  });

  it("logout signs out and removes the app from the tree", async () => {
    mocks.getSession.mockResolvedValue({ data: { session: SESSION } });
    mocks.signOut.mockImplementation(async () => {
      mocks.callback?.("SIGNED_OUT", null);
      return { error: null };
    });
    render(<App />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "خروج" }));

    expect(mocks.signOut).toHaveBeenCalled();
    await waitFor(() => expect(screen.queryByTestId("protected")).toBeNull());
    expect(screen.getByRole("form", { name: "تسجيل الدخول" })).toBeInTheDocument();
  });

  it("drops the app when the session is lost elsewhere (expired refresh, other tab)", async () => {
    mocks.getSession.mockResolvedValue({ data: { session: SESSION } });
    render(<App />);
    await screen.findByTestId("protected");
    act(() => mocks.callback?.("SIGNED_OUT", null));
    expect(screen.queryByTestId("protected")).toBeNull();
  });

  it("unsubscribes from auth changes on unmount", async () => {
    mocks.getSession.mockResolvedValue({ data: { session: null } });
    const { unmount } = render(<App />);
    await screen.findByRole("form", { name: "تسجيل الدخول" });
    unmount();
    expect(mocks.unsubscribe).toHaveBeenCalled();
  });
});
