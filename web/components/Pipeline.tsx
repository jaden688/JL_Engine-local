"use client";
import { motion } from "framer-motion";

const STEPS = [
  {
    id: "01",
    name: "Signal Scoring",
    desc: "The engine reads the incoming message before anything else — urgency, complexity, emotional weight, what kind of response it's pulling for.",
    accent: "#818cf8",
  },
  {
    id: "02",
    name: "State Selection",
    desc: "Based on the signal score and the history of the conversation, the engine picks one of 20 named behavior states. This controls everything downstream.",
    accent: "#818cf8",
  },
  {
    id: "03",
    name: "Drift Check",
    desc: "Tracks how far the session has traveled from baseline. High drift softens the output. Extreme drift hands control to Supervisor.",
    accent: "#a78bfa",
  },
  {
    id: "04",
    name: "Rhythm Engine",
    desc: "Sets the pace — how fast to respond, how much to say, how dense to go. A sprint sounds different from a crawl even with the same words.",
    accent: "#a78bfa",
  },
  {
    id: "05",
    name: "Emotional Aperture",
    desc: "Opens or closes the expressive range. Wide aperture means more character and color. Narrow means precise and clipped.",
    accent: "#c084fc",
  },
  {
    id: "06",
    name: "Response",
    desc: "The model sees a fully conditioned prompt. It knows the state, the aperture, the memory, the operator identity, and the available tools. Then it talks.",
    accent: "#34d399",
  },
];

export default function Pipeline() {
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
          <p className="text-xs font-mono text-[#818cf8] tracking-widest uppercase mb-4">How it works</p>
          <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-6">
            <h1 className="text-4xl font-bold tracking-tight text-white max-w-xl">
              Six things happen before<br />the model says a word.
            </h1>
            <p className="text-sm text-[#64748b] max-w-xs">
              Every message runs through the full pipeline. Nothing skips.
            </p>
          </div>
        </motion.div>

        <div className="relative">
          <div className="absolute left-[28px] top-8 bottom-8 w-px bg-gradient-to-b from-[#818cf8]/40 via-[#a78bfa]/20 to-[#34d399]/40 hidden md:block" />

          <div className="flex flex-col gap-4">
            {STEPS.map((step, i) => (
              <motion.div
                key={step.id}
                initial={{ opacity: 0, x: -16 }}
                whileInView={{ opacity: 1, x: 0 }}
                viewport={{ once: true }}
                transition={{ duration: 0.5, delay: i * 0.07 }}
                className="flex gap-5 items-start"
              >
                <div
                  className="flex-shrink-0 w-14 h-14 rounded-xl flex items-center justify-center font-mono text-xs font-bold border relative z-10"
                  style={{
                    background: `${step.accent}0d`,
                    borderColor: `${step.accent}22`,
                    color: step.accent,
                  }}
                >
                  {step.id}
                </div>
                <div className="surface-card card-hover flex-1 p-5">
                  <div className="font-semibold text-white mb-1">{step.name}</div>
                  <p className="text-sm text-[#94a3b8] leading-relaxed">{step.desc}</p>
                </div>
              </motion.div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
