import type { Metadata, Viewport } from "next";
import { Cairo } from "next/font/google";
import Link from "next/link";
import "./globals.css";
import { ThemeProvider } from "@/components/theme-provider";
import { ThemeToggle } from "@/components/theme-toggle";
import { BottomNav, TopNav } from "@/components/nav";

const cairo = Cairo({
  variable: "--font-cairo",
  subsets: ["arabic", "latin"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "THNDR Smart Portfolio",
  description: "متابعة محفظتك الاستثمارية المصرية بذكاء — بدون تنفيذ تلقائي للصفقات.",
  manifest: "/manifest.webmanifest",
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f7f8fa" },
    { media: "(prefers-color-scheme: dark)", color: "#0b0d12" },
  ],
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ar" dir="rtl" suppressHydrationWarning className={`${cairo.variable} h-full`}>
      <body className="min-h-full antialiased">
        <ThemeProvider attribute="class" defaultTheme="system" enableSystem>
          <div className="flex min-h-full flex-col">
            <header className="safe-top sticky top-0 z-30 border-b border-border bg-card/95 backdrop-blur">
              <div className="mx-auto flex max-w-4xl items-center justify-between gap-3 px-4 py-3">
                <Link href="/" className="flex items-center gap-2">
                  <span className="grid h-8 w-8 place-items-center rounded-xl bg-primary text-sm font-bold text-primary-foreground">
                    ث
                  </span>
                  <span className="text-sm font-bold text-foreground">THNDR Smart Portfolio</span>
                </Link>
                <div className="flex items-center gap-2">
                  <TopNav />
                  <ThemeToggle />
                </div>
              </div>
            </header>

            <main className="mx-auto w-full max-w-4xl flex-1 px-4 pb-24 pt-4 md:pb-10">{children}</main>

            <BottomNav />
          </div>
        </ThemeProvider>
      </body>
    </html>
  );
}
