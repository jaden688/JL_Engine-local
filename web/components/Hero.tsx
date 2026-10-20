// ─────────────────────────────────────────────────────────────────────────────
// NAMING RULE: MPF = Modular Personality Frame.
// Agents are "MPF operator frames". Use "character frame" or "operator identity" in copy.
// "personalities" → "MPF operator frames".
// This rule applies to all files in web/components/.
// ─────────────────────────────────────────────────────────────────────────────
"use client";
import { motion } from "framer-motion";
import Link from "next/link";


export default function Hero() {
  return (
    <section className="relative min-h-screen flex flex-col justify-center pt-24 pb-16 dot-grid overflow-hidden">
      <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
        <div className="w-[800px] h-[500px] rounded-full bg-[#818cf8]/5 blur-[120px]" />
      </div>

      <div className="relative z-10 max-w-6xl mx-auto px-6">
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
          className="inline-flex items-center gap-2 border border-[#818cf8]/20 bg-[#818cf8]/5 rounded-full px-3.5 py-1.5 mb-8"
        >
          <span className="w-1.5 h-1.5 rounded-full bg-[#34d399] animate-pulse-slow" />
          <span className="text-xs text-[#94a3b8] font-mono tracking-wide">
            Self-hosted · Production ready
          </span>
        </motion.div>

        <motion.h1
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.1 }}
          className="text-5xl sm:text-6xl lg:text-7xl font-bold tracking-tight leading-[1.08] max-w-4xl"
        >
          Your AI. Running
          <br />
          <span className="gradient-text">the way you want.</span>
        </motion.h1>

        <motion.p
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.2 }}
          className="mt-6 text-lg text-[#94a3b8] max-w-xl leading-relaxed"
        >
          JL Engine shapes how your AI thinks, responds, and acts —
          before it ever says a word. Real browser control, live tool creation,
          six built-in MPF operator frames, and a protocol to connect it to anything.
        </motion.p>

        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.3 }}
          className="mt-10 flex flex-wrap items-center gap-4"
        >
          <Link
            href="/enterprise"
            className="inline-flex items-center gap-2 bg-white hover:bg-gray-100 text-[#08080f] font-semibold text-sm px-5 py-2.5 rounded-lg transition-colors shadow-lg"
          >
            Get early access
          </Link>
          <Link
            href="/how-it-works"
            className="inline-flex items-center gap-2 border border-white/10 hover:border-white/20 text-[#e2e8f0] text-sm font-medium px-5 py-2.5 rounded-lg transition-colors"
          >
            See how it works
          </Link>
        </motion.div>

      </div>
    </section>
  );
}
