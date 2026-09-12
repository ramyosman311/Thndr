import { ImageResponse } from "next/og";

export const size = { width: 512, height: 512 };
export const contentType = "image/png";
// Required for `output: "export"` (the Phase 22 Capacitor build) to
// prerender this route handler; a no-op for the normal web build, which
// already statically optimizes it since it takes no dynamic input.
export const dynamic = "force-static";

/** MIZAN monogram: a plain, bold "M" letterform on the existing brand
 * background -- deliberately minimal (no wordmark, no external asset,
 * no new dependency) so it stays legible at favicon size and as a
 * PWA/home-screen icon. See DECISIONS.md, "MIZAN Brand Migration". */
export default function Icon() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "#0f766e",
          borderRadius: 96,
          color: "#ffffff",
          fontSize: 280,
          fontWeight: 700,
          fontFamily: "sans-serif",
        }}
      >
        M
      </div>
    ),
    { ...size }
  );
}
