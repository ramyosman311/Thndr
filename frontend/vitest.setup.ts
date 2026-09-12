import "@testing-library/jest-dom/vitest";
import { vi } from "vitest";

// next/font/google's Cairo(...) call runs at module scope in app/layout.tsx
// and requires Next's build-time font loader, which isn't present under
// Vitest -- mock it so tests can import app/layout.tsx for its exported
// metadata/viewport without a real font pipeline.
vi.mock("next/font/google", () => ({
  Cairo: () => ({ variable: "--font-cairo", className: "font-cairo" }),
}));
