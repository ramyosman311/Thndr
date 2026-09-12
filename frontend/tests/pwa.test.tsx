import { describe, expect, it, afterEach } from "vitest";
import { render, cleanup, act } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import manifest from "@/app/manifest";
import IconMaskable, { size as maskableSize, contentType as maskableContentType } from "@/app/icon1";
import AppleIcon, { size as appleSize, contentType as appleContentType } from "@/app/apple-icon";
import { size as iconSize, contentType as iconContentType } from "@/app/icon";
import RootLayout, { metadata, viewport } from "@/app/layout";
import { ServiceWorkerRegistration } from "@/components/service-worker-registration";
import { OfflineBanner } from "@/components/offline-banner";

afterEach(() => {
  cleanup();
});

// --- A/C/D/E/G: manifest -----------------------------------------------------

describe("PWA manifest", () => {
  const result = manifest();

  it("declares the MIZAN name and short name", () => {
    expect(result.name).toBe("MIZAN Smart Portfolio Manager");
    expect(result.short_name).toBe("MIZAN");
  });

  it("is configured for a standalone, portrait, installed experience", () => {
    expect(result.display).toBe("standalone");
    expect(result.orientation).toBe("portrait-primary");
    expect(result.start_url).toBe("/");
  });

  it("carries RTL/Arabic metadata", () => {
    expect(result.lang).toBe("ar");
    expect(result.dir).toBe("rtl");
  });

  it("lists both a standard and a maskable icon", () => {
    const purposes = result.icons?.map((icon) => icon.purpose);
    expect(purposes).toContain("any");
    expect(purposes).toContain("maskable");
    for (const icon of result.icons ?? []) {
      expect(icon.sizes).toBe("512x512");
      expect(icon.type).toBe("image/png");
    }
  });
});

// --- E: icon route metadata ---------------------------------------------------

describe("Icon routes", () => {
  it("icon.tsx renders at 512x512 PNG", () => {
    expect(iconSize).toEqual({ width: 512, height: 512 });
    expect(iconContentType).toBe("image/png");
  });

  it("icon1.tsx (maskable variant) renders at 512x512 PNG and is a valid image response", () => {
    expect(maskableSize).toEqual({ width: 512, height: 512 });
    expect(maskableContentType).toBe("image/png");
    expect(() => IconMaskable()).not.toThrow();
  });

  it("apple-icon.tsx renders at 180x180 PNG (Apple touch icon convention)", () => {
    expect(appleSize).toEqual({ width: 180, height: 180 });
    expect(appleContentType).toBe("image/png");
    expect(() => AppleIcon()).not.toThrow();
  });
});

// --- B/C/D/F/G: layout metadata + viewport ------------------------------------

describe("Root metadata", () => {
  it("has a title, description, and manifest link", () => {
    expect(metadata.title).toBeTruthy();
    expect(metadata.description).toBeTruthy();
    expect(metadata.manifest).toBe("/manifest.webmanifest");
  });

  it("marks the app as an installable, standalone-capable Apple web app", () => {
    expect(metadata.appleWebApp).toMatchObject({
      capable: true,
      title: "MIZAN",
      statusBarStyle: "black-translucent",
    });
  });

  it("enables safe-area coverage for notch/Dynamic Island/home indicator", () => {
    expect(viewport.viewportFit).toBe("cover");
  });
});

describe("RootLayout root element", () => {
  it("renders the html element with RTL Arabic attributes", () => {
    const element = RootLayout({ children: null }) as unknown as {
      props: { lang: string; dir: string };
    };
    expect(element.props.lang).toBe("ar");
    expect(element.props.dir).toBe("rtl");
  });
});

// --- I/J: service worker never treats /api/ or mutations as cacheable --------

describe("Service worker source (public/sw.js)", () => {
  const source = readFileSync(join(process.cwd(), "public", "sw.js"), "utf-8");

  it("never intercepts non-GET requests", () => {
    expect(source).toMatch(/request\.method !== ["']GET["']\)\s*return;/);
  });

  it("excludes /api/ requests from any cache read or write", () => {
    expect(source).toMatch(/pathname\.startsWith\(["']\/api\/["']\)/);
    expect(source).toMatch(/isApiRequest\(url\)\)\s*return;/);
  });

  it("purges old caches on activate for correct update hygiene", () => {
    expect(source).toContain("activate");
    expect(source).toContain("caches.delete");
  });
});

// --- L: service worker registration never breaks normal rendering ------------

describe("ServiceWorkerRegistration", () => {
  it("renders nothing and does not throw when navigator.serviceWorker is unavailable", () => {
    const { container } = render(<ServiceWorkerRegistration />);
    expect(container).toBeEmptyDOMElement();
  });
});

// --- K: offline UX -------------------------------------------------------------

describe("OfflineBanner", () => {
  it("shows nothing while online", () => {
    Object.defineProperty(navigator, "onLine", { value: true, configurable: true });
    const { container } = render(<OfflineBanner />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows a clear Arabic notice that financial data cannot refresh when offline", () => {
    Object.defineProperty(navigator, "onLine", { value: false, configurable: true });
    const { getByRole } = render(<OfflineBanner />);
    expect(getByRole("alert").textContent).toContain("لا يمكن تحديث بيانات المحفظة");
  });

  it("clears the banner once the online event fires", () => {
    Object.defineProperty(navigator, "onLine", { value: false, configurable: true });
    const { container } = render(<OfflineBanner />);
    expect(container).not.toBeEmptyDOMElement();

    Object.defineProperty(navigator, "onLine", { value: true, configurable: true });
    act(() => {
      window.dispatchEvent(new Event("online"));
    });
    expect(container).toBeEmptyDOMElement();
  });
});
