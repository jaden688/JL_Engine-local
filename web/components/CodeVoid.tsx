"use client";
import { motion } from "framer-motion";

const ENGINE_SNIPPET = `
function analyze_turn!(engine::JLEngineCore, user_message::AbstractString)
    signals = score(engine.signal_scorer, user_message)
    trigger = _derive_trigger(signals)
    engine.current_gait = _infer_gait(signals)
    pressure = calculate(engine.drift_system, drift_input)
    rhythm_state = compute(engine.rhythm_engine; gait=engine.current_gait)
    aperture_state = update_from_signals!(engine.emotional_aperture)
    return projection
end
`.repeat(20);

export default function CodeVoid() {
  return (
    <div className="absolute inset-0 z-0 pointer-events-none overflow-hidden select-none opacity-[0.03]">
      <motion.div
        initial={{ y: 0 }}
        animate={{ y: "-50%" }}
        transition={{ duration: 120, repeat: Infinity, ease: "linear" }}
        className="font-mono text-[10px] leading-relaxed text-purple-400 whitespace-pre"
      >
        {ENGINE_SNIPPET}
        {ENGINE_SNIPPET}
      </motion.div>
    </div>
  );
}
