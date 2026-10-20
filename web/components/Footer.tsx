import Link from "next/link";

export default function Footer() {
  return (
    <footer className="border-t border-white/[0.06] py-12 px-6">
      <div className="max-w-6xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-6">
        <div className="flex items-center gap-2.5">
          <span className="w-6 h-6 rounded-md bg-gradient-to-br from-[#818cf8] to-[#34d399] flex items-center justify-center text-[10px] font-bold text-white">
            JL
          </span>
          <span className="text-sm text-[#475569] font-mono">JL Engine · 2025</span>
        </div>
        <div className="flex items-center gap-6 text-xs text-[#475569] font-mono">
          <Link href="/features" className="hover:text-[#94a3b8] transition-colors">Features</Link>
          <Link href="/operators" className="hover:text-[#94a3b8] transition-colors">Operators</Link>
          <Link href="/how-it-works" className="hover:text-[#94a3b8] transition-colors">How it works</Link>
          <Link href="/enterprise" className="hover:text-[#94a3b8] transition-colors">Enterprise</Link>
        </div>
      </div>
    </footer>
  );
}
