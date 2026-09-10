import { ImageResponse } from "next/og";

export const size = { width: 512, height: 512 };
export const contentType = "image/png";

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
