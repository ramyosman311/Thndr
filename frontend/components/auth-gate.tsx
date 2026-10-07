"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type FormEvent, type ReactNode } from "react";
import type { Session } from "@supabase/supabase-js";
import { getSupabase } from "@/lib/supabase";
import { Card, CardBody, CardHeader } from "@/components/ui/card";

type AuthState =
  | { status: "loading" }
  | { status: "unconfigured" }
  | { status: "signed_out" }
  | { status: "signed_in"; session: Session };

interface AuthContextValue {
  state: AuthState;
  signIn: (email: string, password: string) => Promise<string | null>;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthGate>");
  return ctx;
}

const inputClass =
  "w-full rounded-xl border border-border bg-background px-3 py-2.5 text-sm text-foreground outline-none focus:border-primary";

function LoginScreen({ signIn }: { signIn: AuthContextValue["signIn"] }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    const failure = await signIn(email.trim(), password);
    if (failure) setError(failure);
    setSubmitting(false);
  }

  return (
    <div className="mx-auto flex min-h-screen w-full max-w-sm items-center px-4">
      <Card className="w-full">
        <CardHeader title="تسجيل الدخول إلى ميزان" subtitle="MIZAN Smart Portfolio Manager" />
        <CardBody>
          <form onSubmit={onSubmit} className="space-y-3" aria-label="تسجيل الدخول">
            <label className="block space-y-1">
              <span className="text-xs font-medium text-muted-foreground">البريد الإلكتروني</span>
              <input
                type="email"
                autoComplete="username"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className={inputClass}
                dir="ltr"
              />
            </label>
            <label className="block space-y-1">
              <span className="text-xs font-medium text-muted-foreground">كلمة المرور</span>
              <input
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className={inputClass}
                dir="ltr"
              />
            </label>
            {error ? (
              <p role="alert" className="text-xs text-red-600">
                {error}
              </p>
            ) : null}
            <button
              type="submit"
              disabled={submitting}
              className="w-full rounded-xl bg-primary px-4 py-2.5 text-sm font-semibold text-primary-foreground disabled:opacity-60"
            >
              {submitting ? "جارٍ الدخول..." : "دخول"}
            </button>
          </form>
        </CardBody>
      </Card>
    </div>
  );
}

function Notice({ children }: { children: ReactNode }) {
  return (
    <div className="mx-auto flex min-h-screen w-full max-w-sm items-center justify-center px-4 text-center text-sm text-muted-foreground">
      {children}
    </div>
  );
}

/**
 * Renders NOTHING of the application until a Supabase session exists: the
 * children (and so every request that fetches portfolio data) are mounted only
 * when signed in. Signed out -> login screen at whatever URL was requested.
 * Enforcement of who may see which data is still the backend's job (JWT +
 * ownership); this only guarantees the UI never asks before authenticating.
 */
export function AuthGate({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({ status: "loading" });

  useEffect(() => {
    const supabase = getSupabase();
    if (!supabase) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- one-time initialisation from an external system (the Supabase session).
      setState({ status: "unconfigured" });
      return;
    }
    let active = true;
    supabase.auth.getSession().then(({ data }) => {
      if (active) setState(data.session ? { status: "signed_in", session: data.session } : { status: "signed_out" });
    });
    const { data: subscription } = supabase.auth.onAuthStateChange((_event, session) => {
      setState(session ? { status: "signed_in", session } : { status: "signed_out" });
    });
    return () => {
      active = false;
      subscription.subscription.unsubscribe();
    };
  }, []);

  const signIn = useCallback(async (email: string, password: string) => {
    const supabase = getSupabase();
    if (!supabase) return "تسجيل الدخول غير مُهيّأ.";
    const { error } = await supabase.auth.signInWithPassword({ email, password });
    // One generic message for every failure: never reveal whether the email exists.
    return error ? "البريد الإلكتروني أو كلمة المرور غير صحيحة." : null;
  }, []);

  const signOut = useCallback(async () => {
    await getSupabase()?.auth.signOut();
  }, []);

  const value = useMemo(() => ({ state, signIn, signOut }), [state, signIn, signOut]);

  let content: ReactNode;
  if (state.status === "loading") content = <Notice>جارٍ التحميل...</Notice>;
  else if (state.status === "unconfigured") content = <Notice>تسجيل الدخول غير مُهيّأ على هذا الخادم.</Notice>;
  else if (state.status === "signed_out") content = <LoginScreen signIn={signIn} />;
  else content = children;

  return <AuthContext.Provider value={value}>{content}</AuthContext.Provider>;
}

export function LogoutButton() {
  const { signOut } = useAuth();
  return (
    <button
      type="button"
      onClick={() => void signOut()}
      className="rounded-lg border border-border px-2.5 py-1.5 text-xs font-medium text-muted-foreground hover:text-foreground"
    >
      خروج
    </button>
  );
}
