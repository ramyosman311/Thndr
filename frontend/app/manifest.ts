import type { MetadataRoute } from "next";

/**
 * PWA manifest (Phase 21: installable app metadata + icons). Offline/cache
 * behavior lives in the service worker (public/sw.js), not here — this file
 * only describes the installed app's identity, display mode, and icon set.
 */
// Required for `output: "export"` (the Phase 22 Capacitor build) to
// prerender this route; a no-op for the normal web build, which already
// statically optimizes it since it takes no dynamic input.
export const dynamic = "force-static";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "MIZAN Smart Portfolio Manager",
    short_name: "MIZAN",
    description: "متابعة محفظتك الاستثمارية المصرية بذكاء",
    start_url: "/",
    display: "standalone",
    orientation: "portrait-primary",
    background_color: "#0b0d12",
    theme_color: "#0f766e",
    lang: "ar",
    dir: "rtl",
    icons: [
      { src: "/icon", sizes: "512x512", type: "image/png", purpose: "any" },
      { src: "/icon1", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
  };
}
