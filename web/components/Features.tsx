"use client";
import { motion } from "framer-motion";

const FEATURES = [
  {
    icon: "⬡",
    accent: "#818cf8",
    title: "Behavior that actually changes",
    body: "20 named states that shift in real time based on what's happening in the conversation. Tone, pacing, creativity, and restraint all adjust automatically — or you can dial them manually.",
    tag: "State engine",
  },
  {
    icon: "⚡",
    accent: "#34d399",
    title: "Builds its own tools on the fly",
    body: "Write a new capability in plain language and the engine turns it into working code, tests it, and loads it live — without restarting. What it can do grows as you use it.",
    tag: "Tool forge",
  },
  {
    icon: "◎",
    accent: "#f472b6",
    title: "Controls a real browser",
    body: "Give it a task and it opens a browser, navigates, clicks, fills forms, and screenshots the results back to you in real time. Useful for research, testing, and anything that needs a human hand.",
    tag: "Browser control",
  },
  {
    icon: "⇌",
    accent: "#818cf8",
    title: "Talks to other systems",
    body: "Open JSON-RPC protocol on a dedicated port. Send tasks, check status, pull billing data, or connect it into your own stack. Works with anything that can make an HTTP request.",
    tag: "Open protocol",
  },
  {
    icon: "◈",
    accent: "#34d399",
    title: "Plugs into your existing tools",
    body: "Native bridge to Claude Desktop, Cursor, Windsurf, VS Code, and more. Engine state, memory, and tools all surface where you're already working.",
    tag: "Integrations",
  },
  {
    icon: "◉",
    accent: "#f472b6",
    title: "Keeps working when you're not watching",
    body: "Runs on a configurable heartbeat. Checks its own state, picks what to do next, does it, and logs what happened. Plans, drafts, researches — without being prompted.",
    tag: "Always on",
  },
];

export default function Features() {
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
          <p className="text-xs font-mono text-[#818cf8] tracking-widest uppercase mb-4">What it does</p>
          <h1 className="text-4xl font-bold tracking-tight text-white max-w-xl">
            What it does.
          </h1>
        </motion.div>

        <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-4">
          {FEATURES.map((f, i) => (
            <motion.div
              key={f.title}
              initial={{ opacity: 0, y: 20 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ duration: 0.5, delay: i * 0.07 }}
              className="surface-card card-hover p-6 flex flex-col gap-4"
            >
              <div className="flex items-start justify-between">
                <span
                  className="w-9 h-9 rounded-lg flex items-center justify-center text-lg"
                  style={{ background: `${f.accent}14`, color: f.accent }}
                >
                  {f.icon}
                </span>
                <span
                  className="text-[10px] font-mono tracking-wider uppercase px-2 py-1 rounded-md"
                  style={{ background: `${f.accent}10`, color: f.accent }}
                >
                  {f.tag}
                </span>
              </div>
              <div>
                <h3 className="font-semibold text-white mb-2">{f.title}</h3>
                <p className="text-sm text-[#94a3b8] leading-relaxed">{f.body}</p>
              </div>
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  );
}
