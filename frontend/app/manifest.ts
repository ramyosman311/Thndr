import type { MetadataRoute } from "next";

/**
 * PWA-ready manifest (Phase 9 scope: metadata + icons only). The
 * installable service-worker/offline-cache behavior is explicitly
 * Phase 11 per the README Phase Plan — this file only makes the app
 * PWA-installable-ready without adding offline caching now.
 */
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "THNDR Smart Portfolio",
    short_name: "THNDR",
    description: "متابعة محفظتك الاستثمارية المصرية بذكاء",
    start_url: "/",
    display: "standalone",
    background_color: "#0b0d12",
    theme_color: "#0f766e",
    lang: "ar",
    dir: "rtl",
    icons: [
      { src: "/icon", sizes: "512x512", type: "image/png" },
    ],
  };
}
