import { ImageResponse } from "next/og";

export const size = { width: 512, height: 512 };
export const contentType = "image/png";

/** Maskable variant of the MIZAN monogram (see app/icon.tsx for the base
 * brand asset). Named icon1.tsx per Next's numbered-icon convention --
 * "icon-maskable.tsx" is not a recognized file-convention name and
 * silently produces no route at all. Android/PWA launchers may crop a
 * maskable icon to an arbitrary shape outside a ~80%-diameter safe zone,
 * so the background fills the canvas edge-to-edge (no border radius --
 * the OS supplies the shape) and the glyph is sized well inside that
 * safe zone. */
export default function IconMaskable() {
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
          fontSize: 200,
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
