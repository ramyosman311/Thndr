import { ImageResponse } from "next/og";

export const size = { width: 180, height: 180 };
export const contentType = "image/png";
// Required for `output: "export"` (the Phase 22 Capacitor build) to
// prerender this route handler; a no-op for the normal web build, which
// already statically optimizes it since it takes no dynamic input.
export const dynamic = "force-static";

/** Apple touch icon: same MIZAN monogram brand styling as app/icon.tsx,
 * but full-bleed (no border radius) since iOS applies its own corner
 * mask to the supplied image -- a pre-rounded square would double up. */
export default function AppleIcon() {
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
          color: "#ffffff",
          fontSize: 98,
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
