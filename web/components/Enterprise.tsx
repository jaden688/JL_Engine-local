"use client";
import { motion } from "framer-motion";

const FEATURES = [
  "Managed deployment",
  "SSO and access controls",
  "Custom operator setup and tuning",
  "Uptime SLA",
  "Audit logs",
  "Direct line to the team",
  "Architecture review session",
];

export default function Enterprise() {
  return (
    <section className="py-28 px-6">
      <div className="max-w-6xl mx-auto">
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.5 }}
          className="mb-16"
        >
          <p className="text-xs font-mono text-[#818cf8] tracking-widest uppercase mb-4">Get access</p>
          <h1 className="text-4xl font-bold tracking-tight text-white max-w-xl">
            Built for teams that need it to work.
          </h1>
          <p className="mt-4 text-[#64748b] max-w-lg leading-relaxed">
            Reach out and we&apos;ll figure out what actually makes sense for your setup.
          </p>
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.5 }}
          className="relative p-8 rounded-xl bg-[#818cf8]/5 border border-[#818cf8]/25 max-w-md"
        >
          <div className="absolute -top-px left-8 right-8 h-px bg-gradient-to-r from-transparent via-[#818cf8]/60 to-transparent" />

          <ul className="flex flex-col gap-3 mb-8">
            {FEATURES.map((f) => (
              <li key={f} className="flex items-center gap-3 text-sm text-[#94a3b8]">
                <svg className="w-4 h-4 flex-shrink-0 text-[#818cf8]" viewBox="0 0 20 20" fill="currentColor" aria-hidden>
                  <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                </svg>
                {f}
              </li>
            ))}
          </ul>

          <a
            href="mailto:jadenlindenbach@gmail.com?subject=JL Engine Access"
            className="inline-flex items-center justify-center w-full px-5 py-3 rounded-lg text-sm font-semibold bg-[#818cf8] hover:bg-[#6366f1] text-white transition-colors shadow-lg shadow-indigo-500/20"
          >
            Get in touch
          </a>
        </motion.div>
      </div>
    </section>
  );
}
