"""Read-only production Web E2E verification (run from a GitHub runner).

Part A (no credentials): site reachable, login page, built bundle secret scan,
proxy/Render 401 behaviour, forged internal-token rejection.
Part B (only when E2E_PASSWORD is set): real browser login as the owner, then
GET-only checks, logout, re-login, reload. Never creates or changes data; never
prints the password, tokens or API_AUTH_TOKEN.
"""

import base64
import json
import os
import re
import sys
import urllib.error
import urllib.request

SITE = os.environ["E2E_SITE"].rstrip("/")
EMAIL = os.environ["E2E_EMAIL"]
PASSWORD = os.environ.get("E2E_PASSWORD", "")
EXPECTED_UUID = os.environ.get("E2E_EXPECTED_UUID", "")
RENDER = "https://mizan-backend-5e7b.onrender.com/api"
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" -- {detail}" if detail else ""), flush=True)


def get(url, headers=None):
    req = urllib.request.Request(url, headers={"User-Agent": "mizan-e2e", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read().decode("utf-8", "replace"), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace"), dict(e.headers)
    except Exception as e:  # noqa: BLE001
        return f"ERR {e.__class__.__name__}", "", {}


def jwt_sub(token: str) -> str:
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload))["sub"]


def part_a() -> str | None:
    status, html, _ = get(SITE + "/")
    check("1. production URL reachable", status == 200, f"HTTP {status}")
    scripts = re.findall(r'src="(/_next/static/[^"]+\.js)"', html)
    bundle = html
    for s in scripts:
        st, body, _ = get(SITE + s)
        bundle += body if st == 200 else ""
    check("   JS bundles fetched", len(scripts) > 0, f"{len(scripts)} files")
    for needle in ("API_AUTH_TOKEN", "x-internal-proxy-token", "X-Internal-Proxy-Token", "service_role", "SUPABASE_SERVICE_ROLE"):
        check(f"15. bundle does not contain {needle!r}", needle not in bundle)
    check("   deployed build contains the login gate code (P0-3D)", "useAuth must be used inside" in bundle)
    m = re.search(r"https://([a-z0-9]{20})\.supabase\.co", bundle)
    check("   bundle has Supabase project URL (login configured)", bool(m), m.group(0) if m else "NOT FOUND -> NEXT_PUBLIC_SUPABASE_URL missing in build")
    anon = re.search(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}|sb_publishable_[A-Za-z0-9_-]+", bundle)
    check("   bundle has public anon key", bool(anon))
    if anon:
        # a bundled JWT must be the anon role, never service_role
        tok = anon.group(0)
        if tok.startswith("eyJ"):
            p = tok.split(".")[1] + "=" * (-len(tok.split(".")[1]) % 4)
            role = json.loads(base64.urlsafe_b64decode(p)).get("role")
            check("15. bundled key role is 'anon' (not service_role)", role == "anon", f"role={role}")

    st, body, _ = get(SITE + "/api/health")
    check("   proxy /api/health -> Render", st == 200, f"HTTP {st} {body[:120]}")
    st, _, _ = get(SITE + "/api/assets")
    check("14. unauthenticated API via Vercel proxy -> 401", st == 401, f"HTTP {st}")
    st, _, _ = get(SITE + "/api/portfolio/config", {"X-Internal-Proxy-Token": "forged-by-browser"})
    check("6. browser-supplied X-Internal-Proxy-Token does not authenticate", st == 401, f"HTTP {st}")
    st, _, _ = get(RENDER + "/assets", {"X-Internal-Proxy-Token": "forged", "Authorization": "Bearer not.a.jwt"})
    check("14. Render direct with forged token + garbage JWT -> 401", st == 401, f"HTTP {st}")
    st, _, _ = get(RENDER + "/assets")
    check("14. Render direct, no credentials -> 401", st == 401, f"HTTP {st}")
    return m.group(0) if m else None


def part_b() -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context()
        page = ctx.new_page()
        console_errors: list[str] = []
        bad_responses: list[str] = []
        api_requests: list[tuple[str, dict]] = []
        page.on("console", lambda m: console_errors.append(m.text[:200]) if m.type == "error" else None)
        page.on("pageerror", lambda e: console_errors.append(f"pageerror: {str(e)[:200]}"))

        def on_request(req):
            if "/api/" in req.url:
                api_requests.append((req.url, req.headers))

        def on_response(resp):
            if "/api/" in resp.url and resp.status >= 400:
                bad_responses.append(f"{resp.status} {resp.url.replace(SITE, '')}")
            for h in resp.headers:
                if h.lower() == "x-internal-proxy-token":
                    bad_responses.append(f"LEAK header {h} on {resp.url}")

        page.on("request", on_request)
        page.on("response", on_response)

        page.goto(SITE + "/", wait_until="networkidle")
        form = page.get_by_role("form", name="تسجيل الدخول")
        check("2. login page loads", form.count() == 1)
        check("   no protected /api request before login", len(api_requests) == 0, f"{len(api_requests)} requests")

        def login(label: str):
            page.get_by_label("البريد الإلكتروني").fill(EMAIL)
            page.get_by_label("كلمة المرور").fill(PASSWORD)
            page.get_by_role("button", name="دخول").click()
            try:
                page.get_by_role("button", name="خروج").wait_for(timeout=45000)
                return True
            except Exception:  # noqa: BLE001
                err = page.get_by_role("alert")
                check(f"{label} login", False, "alert: " + (err.inner_text() if err.count() else "none shown"))
                return False

        if not login("3."):
            browser.close()
            return
        check("3. login succeeds with the Supabase account", True)

        def session_token():
            return page.evaluate(
                """() => { for (const k of Object.keys(localStorage)) { if (/^sb-.*-auth-token$/.test(k)) {
                    const v = JSON.parse(localStorage.getItem(k)); return v.access_token || (v.currentSession||{}).access_token || null; } } return null; }"""
            )

        token = session_token()
        check("4. Supabase session/JWT established in browser", bool(token))
        if token:
            sub = jwt_sub(token)
            check("8. JWT subject equals the expected user UUID", sub == EXPECTED_UUID, f"sub={sub}")

        def api(path):
            return page.evaluate(
                """async (p) => { const t = (()=>{for (const k of Object.keys(localStorage)) { if (/^sb-.*-auth-token$/.test(k)) { const v = JSON.parse(localStorage.getItem(k)); return v.access_token; } }})();
                   const r = await fetch('/api'+p, {headers: {Authorization: 'Bearer '+t}, cache: 'no-store'});
                   let b = null; try { b = await r.json(); } catch (e) {} return {status: r.status, body: b}; }""",
                path,
            )

        cfg = api("/portfolio/config")
        check("7/9. Render accepts proxied request; Main Portfolio returned", cfg["status"] == 200 and (cfg["body"] or {}).get("name") == "Main Portfolio", f"HTTP {cfg['status']} name={(cfg['body'] or {}).get('name')}")
        check("   portfolio emergency_excluded", (cfg["body"] or {}).get("emergency_excluded") is True)

        buckets = {b["id"]: b["name"] for b in (api("/strategy/buckets")["body"] or [])}
        targets = api("/strategy/targets")["body"] or []
        by = {buckets.get(t["strategy_bucket_id"]): t for t in targets}
        D = lambda v: None if v is None else float(v)  # noqa: E731
        ok = (
            D(by["Growth / Investment Funds"]["target_percent"]) == 55
            and D(by["Defensive / Fixed Income"]["target_percent"]) == 25
            and D(by["Free Cash"]["target_percent"]) == 0
            and by["Individual Stocks"]["target_percent"] is None
            and D(by["Individual Stocks"]["maximum_percent"]) == 20
            and D(by["Gold"]["target_percent"]) == 0
            and by["Gold"]["allow_new_buy"] is False
            and "Emergency Cash" not in by
        )
        check("11. stored strategy values (API)", ok, json.dumps({k: [t["target_percent"], t["maximum_percent"], t["allow_new_buy"]] for k, t in by.items()}))
        val = api("/portfolio/strategy/validation")
        check("   strategy total 80% not normalised", val["status"] == 200 and float(val["body"]["total_target_percent"]) == 80, str((val["body"] or {}).get("total_target_percent")))
        for p in ("/portfolio/summary", "/portfolio/allocation", "/portfolio/recommendations", "/portfolio/notifications", "/portfolio/rebalancing"):
            r = api(p)
            check(f"   GET {p}", r["status"] == 200, f"HTTP {r['status']}")

        for path, label in (("/", "Dashboard"), ("/portfolio", "Portfolio"), ("/allocation", "Allocation"), ("/watchlist", "Watchlist"), ("/settings", "Settings"), ("/inflow", "Inflow")):
            before = len(bad_responses), len(console_errors)
            page.goto(SITE + path, wait_until="networkidle")
            page.wait_for_timeout(1500)
            new_bad = bad_responses[before[0]:]
            new_err = console_errors[before[1]:]
            check(f"10. {label} page loads without API errors", len(new_bad) == 0 and len(new_err) == 0, "; ".join(new_bad + new_err)[:300])
        page.goto(SITE + "/settings", wait_until="networkidle")
        body_text = page.inner_text("body")
        for needle in ("Growth / Investment Funds", "Defensive / Fixed Income", "Individual Stocks", "Gold", "Free Cash"):
            check(f"11. Settings shows bucket {needle!r}", needle in body_text)

        rel = all(u.startswith(SITE + "/api/") for u, _ in api_requests)
        check("5. browser API calls use the relative /api path (same origin)", rel and len(api_requests) > 0, f"{len(api_requests)} requests")
        check("6. forwarded browser requests carry Authorization: Bearer", all(h.get("authorization", "").startswith("Bearer ") for _, h in api_requests))
        check("6. browser never sends X-Internal-Proxy-Token", all("x-internal-proxy-token" not in {k.lower() for k in h} for _, h in api_requests))
        check("15. no internal-token leak / API error in responses", not [b for b in bad_responses if b.startswith("LEAK")])

        page.get_by_role("button", name="خروج").click()
        page.get_by_role("form", name="تسجيل الدخول").wait_for(timeout=15000)
        check("12. logout returns to login screen", True)
        check("12. session removed from browser storage", session_token() is None)
        st, _, _ = get(SITE + "/api/portfolio/config")
        check("12. API without session -> 401", st == 401, f"HTTP {st}")

        if login("13."):
            check("13. login again succeeds", True)
            page.reload(wait_until="networkidle")
            still = page.get_by_role("button", name="خروج")
            still.wait_for(timeout=30000)
            check("13. session persists across page refresh", still.count() == 1)
            check("13. API works after refresh", api("/portfolio/config")["status"] == 200)
        browser.close()


def main() -> int:
    print("== Part A (no credentials)")
    part_a()
    if PASSWORD:
        print("== Part B (browser, authenticated, GET-only)")
        part_b()
    else:
        print("== Part B skipped: E2E_PASSWORD secret is not set")
    failed = [r for r in results if not r[1]]
    print(f"\nSUMMARY: {len(results) - len(failed)} passed, {len(failed)} failed" + ("" if PASSWORD else " (authenticated part NOT run)"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
