"use client";
import { useState, useEffect } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/features",      label: "Features" },
  { href: "/operators",     label: "Operators" },
  { href: "/how-it-works",  label: "How it works" },
  { href: "/enterprise",    label: "Enterprise" },
];

export default function Nav() {
  const [scrolled, setScrolled] = useState(false);
  const pathname = usePathname();

  useEffect(() => {
    const handler = () => setScrolled(window.scrollY > 20);
    window.addEventListener("scroll", handler, { passive: true });
    return () => window.removeEventListener("scroll", handler);
  }, []);

  return (
    <header
      className={`fixed top-0 inset-x-0 z-50 transition-all duration-300 ${
        scrolled
          ? "bg-[#08080f]/90 backdrop-blur-md border-b border-white/[0.06]"
          : "bg-transparent"
      }`}
    >
      <div className="max-w-6xl mx-auto px-6 h-16 flex items-center justify-between">
        <Link href="/" className="flex items-center gap-2.5 group">
          <span className="w-7 h-7 rounded-md bg-gradient-to-br from-[#818cf8] to-[#34d399] flex items-center justify-center text-xs font-bold text-white shadow-lg shadow-indigo-500/20">
            JL
          </span>
          <span className="font-semibold text-sm tracking-tight text-white">
            JL Engine
          </span>
        </Link>

        <nav className="hidden md:flex items-center gap-6 text-sm">
          {LINKS.map((l) => (
            <Link
              key={l.href}
              href={l.href}
              className={`transition-colors ${
                pathname === l.href
                  ? "text-white"
                  : "text-[#94a3b8] hover:text-white"
              }`}
            >
              {l.label}
            </Link>
          ))}
        </nav>

        <div className="flex items-center gap-3">
<Link
            href="/enterprise"
            className="inline-flex items-center gap-1.5 bg-[#818cf8] hover:bg-[#6366f1] text-white text-sm font-medium px-4 py-2 rounded-lg transition-colors shadow-lg shadow-indigo-500/20"
          >
            Get Access
          </Link>
        </div>
      </div>
    </header>
  );
}
