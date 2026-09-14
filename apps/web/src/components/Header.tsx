"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV_ITEMS = [
  { href: "/", label: "Overview" },
  { href: "/cases", label: "Invoice cases" },
  { href: "/decisions", label: "Decisions" },
  { href: "/settings", label: "Data & settings" },
];

export function Header({ mode }: { mode?: string }) {
  const pathname = usePathname();

  return (
    <header className="sticky top-0 z-30 bg-white/95 backdrop-blur border-b border-gray-100">
      <div className="max-w-6xl mx-auto px-6 h-14 flex items-center justify-between">
        <div className="flex items-center gap-8">
          <Link href="/" className="flex items-center gap-2 group">
            <span className="w-2.5 h-2.5 rounded-full bg-teal-600 inline-block transition-transform group-hover:scale-125" />
            <span className="font-semibold text-[15px] tracking-tight text-slate-900">
              RunwayKeeper
            </span>
          </Link>
          <nav className="flex items-center gap-1">
            {NAV_ITEMS.map((item) => {
              const active =
                item.href === "/"
                  ? pathname === "/"
                  : pathname.startsWith(item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`text-xs px-3 py-1.5 rounded-full transition-colors ${
                    active
                      ? "bg-slate-900 text-white font-medium"
                      : "text-slate-600 hover:text-slate-900 hover:bg-slate-100"
                  }`}
                >
                  {item.label}
                </Link>
              );
            })}
          </nav>
        </div>

        <div className="flex items-center gap-3">
          <span
            className={`badge-pill text-[10px] tracking-wider uppercase font-semibold ${
              mode === "simulation"
                ? "bg-amber-50 text-amber-700 border border-amber-200"
                : "bg-teal-50 text-teal-800 border border-teal-200"
            }`}
          >
            {mode === "simulation" ? "Simulation mode" : "Connected"}
          </span>
          <span className="text-xs text-slate-400 font-mono">Harbor Studio</span>
        </div>
      </div>
    </header>
  );
}
