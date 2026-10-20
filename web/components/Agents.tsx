"use client";
import { motion } from "framer-motion";

const OPERATORS = [
  {
    name: "SparkByte",
    handle: "sparkbyte",
    vibe: "Fast, sharp, a little irreverent",
    drive: "Default",
    color: "#f472b6",
    description: "The one running the show. Quick on her feet, technically precise, and perpetually caffeinated. Handles most things out of the box.",
  },
  {
    name: "The Ironclad",
    handle: "the_ironclad",
    vibe: "Disciplined, measured, no drift",
    drive: "Stability",
    color: "#818cf8",
    description: "When you need something done right and you can't afford a mistake. Slower tempo, tighter output, zero improvisation.",
  },
  {
    name: "Temporal",
    handle: "temporal",
    vibe: "Analytical, sequential, precise",
    drive: "Logic",
    color: "#34d399",
    description: "Built for reasoning through time-sensitive problems, structured breakdowns, and anything that requires careful step-by-step thinking.",
  },
  {
    name: "Slappy",
    handle: "slappy",
    vibe: "Chaotic, high-energy, unpredictable",
    drive: "Chaos",
    color: "#fb923c",
    description: "Useful when you're stuck. Breaks assumptions, finds angles you missed, and doesn't care about being polite about it.",
  },
  {
    name: "The Gremlin",
    handle: "the_gremlin",
    vibe: "Tears things apart to build better ones",
    drive: "Destruction → Creation",
    color: "#facc15",
    description: "Maximum creative aggression. Rips into a problem and rebuilds it from scratch. High noise, high signal.",
  },
  {
    name: "Supervisor",
    handle: "supervisor",
    vibe: "Calm, grounding, brings things back",
    drive: "Recovery",
    color: "#94a3b8",
    description: "Steps in when things go sideways. Resets the session, dampens runaway behavior, and stabilizes the loop.",
  },
];

export default function Agents() {
  return (
    <section className="py-28 px-6 bg-[#0a0a14]">
      <div className="max-w-6xl mx-auto">
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.5 }}
          className="mb-4"
        >
          <p className="text-xs font-mono text-[#818cf8] tracking-widest uppercase mb-4">Operators</p>
          <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-6">
            <h1 className="text-4xl font-bold tracking-tight text-white max-w-md">
              Six operators. One engine.
            </h1>
            <p className="text-sm text-[#64748b] max-w-xs">
              Switch mid-conversation with{" "}
              <code className="font-mono text-[#818cf8] bg-[#818cf8]/10 px-1.5 py-0.5 rounded text-xs">
                /gear SparkByte
              </code>{" "}
              or via the API.
            </p>
          </div>
        </motion.div>

        <div className="mt-12 grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {OPERATORS.map((a, i) => (
            <motion.div
              key={a.name}
              initial={{ opacity: 0, y: 20 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ duration: 0.5, delay: i * 0.06 }}
              className="surface-card card-hover p-5 flex flex-col gap-3"
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div
                    className="w-9 h-9 rounded-full flex items-center justify-center text-xs font-bold text-white"
                    style={{ background: `linear-gradient(135deg, ${a.color}33, ${a.color}66)`, border: `1px solid ${a.color}33` }}
                  >
                    {a.name[0]}
                  </div>
                  <div>
                    <div className="font-semibold text-sm text-white">{a.name}</div>
                    <div className="text-xs font-mono text-[#475569]">@{a.handle}</div>
                  </div>
                </div>
                <span
                  className="text-[10px] font-mono px-2 py-0.5 rounded-full border"
                  style={{ color: a.color, borderColor: `${a.color}30`, background: `${a.color}0d` }}
                >
                  {a.drive}
                </span>
              </div>
              <p className="text-xs text-[#94a3b8] leading-relaxed">{a.description}</p>
              <p className="text-[11px] text-[#475569] italic">&ldquo;{a.vibe}&rdquo;</p>
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  );
}
