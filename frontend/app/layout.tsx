import type { Metadata } from "next";
import Link from "next/link";

import "./globals.css";
import { Providers } from "./providers";

export const metadata: Metadata = {
  title: "Regime Trader",
  description: "Self-learning, regime-aware paper trading dashboard",
};

const NAV: [string, string][] = [
  ["/", "Dashboard"],
  ["/strategies", "Strategies"],
  ["/approvals", "Approvals"],
  ["/alerts", "Alerts"],
  ["/settings", "Settings"],
];

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-zinc-950 text-zinc-100 antialiased">
        <Providers>
          <div className="flex min-h-screen">
            <aside className="w-52 shrink-0 border-r border-zinc-800 p-4">
              <div className="mb-6 text-lg font-semibold">📈 Regime Trader</div>
              <nav className="flex flex-col gap-1">
                {NAV.map(([href, label]) => (
                  <Link
                    key={href}
                    href={href}
                    className="rounded px-3 py-2 text-sm text-zinc-300 hover:bg-zinc-900"
                  >
                    {label}
                  </Link>
                ))}
              </nav>
              <div className="mt-6 rounded bg-amber-500/10 px-2 py-1 text-center text-xs text-amber-400">
                Paper only
              </div>
            </aside>
            <main className="flex-1 p-8">{children}</main>
          </div>
        </Providers>
      </body>
    </html>
  );
}
