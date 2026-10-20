"use client";
import { motion, AnimatePresence } from "framer-motion";
import { useEffect, useState } from "react";

interface MainTerminalProps {
  phase: "idle" | "init" | "seal" | "run" | "cascade";
}

export default function MainTerminal({ phase }: MainTerminalProps) {
  const [typedCmd, setTypedCmd] = useState("");
  const fullCmd = "./sparkbyte.jl";

  useEffect(() => {
    if (phase === "run") {
      let i = 0;
      const interval = setInterval(() => {
        setTypedCmd(fullCmd.slice(0, i + 1));
        i++;
        if (i === fullCmd.length) clearInterval(interval);
      }, 70);
      return () => clearInterval(interval);
    }
  }, [phase]);

  return (
    <motion.div
      initial={{ opacity: 0, y: 20, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ duration: 1.5, ease: [0.16, 1, 0.3, 1] }}
      className="relative z-20 w-full max-w-[520px] aspect-[16/10] bg-black/60 backdrop-blur-3xl border border-purple-500/20 rounded-xl overflow-hidden shadow-[0_0_80px_-20px_rgba(168,85,247,0.15)] p-8 flex flex-col"
    >
      {/* Header */}
      <div className="flex justify-between items-center mb-8">
        <div className="flex items-center space-x-3">
          <div className="w-2.5 h-2.5 rounded-full bg-purple-500 shadow-[0_0_10px_rgba(168,85,247,0.8)] animate-pulse-slow" />
          <span className="font-mono text-[10px] tracking-[0.3em] text-purple-300/50 uppercase">SparkByte_Runtime</span>
        </div>
        <span className="font-mono text-[9px] text-white/20 uppercase tracking-widest italic">L1_Orchestration</span>
      </div>

      {/* Terminal Area */}
      <div className="flex-grow font-mono text-[13px] space-y-4">
        <AnimatePresence mode="wait">
          {phase === "init" && (
            <motion.div
              key="init"
              initial={{ opacity: 0 }}
              animate={{ opacity: 0.4 }}
              exit={{ opacity: 0 }}
              className="text-purple-200"
            >
              connecting to lattice...
            </motion.div>
          )}
        </AnimatePresence>

        {(phase === "seal" || phase === "run" || phase === "cascade") && (
          <div className="flex flex-col space-y-3">
            <div className="flex items-center space-x-2">
              <span className="text-purple-500">█</span>
              <motion.span 
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ delay: 0.5 }}
                className="text-white font-bold"
              >
                .
              </motion.span>
            </div>

            {(phase === "run" || phase === "cascade") && (
              <div className="flex items-center space-x-3 text-slate-300">
                <span className="text-emerald-500/60 font-bold tracking-tighter">{">"}</span>
                <span>{typedCmd}</span>
                {typedCmd.length < fullCmd.length && (
                  <motion.div 
                    animate={{ opacity: [1, 0] }}
                    transition={{ repeat: Infinity, duration: 0.8 }}
                    className="w-1.5 h-4 bg-purple-500/40"
                  />
                )}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Footer / Status */}
      <div className="mt-8 pt-6 border-t border-white/5 flex justify-between font-mono text-[9px] tracking-widest text-white/20 uppercase">
        <div className="flex space-x-6">
          <span>Gait: Sprint</span>
          <span>Entropy: 0.042</span>
        </div>
        <div className="flex space-x-4">
          <span>Secure</span>
          <span className="text-emerald-500/30">Active</span>
        </div>
      </div>
    </motion.div>
  );
}
