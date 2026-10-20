"use client";
import { motion } from "framer-motion";

interface ToolPaneProps {
  name: string;
  delay: number;
  position: string;
}

export default function ToolPane({ name, delay, position }: ToolPaneProps) {
  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.95, y: 10 }}
      animate={{ opacity: 1, scale: 1, y: 0 }}
      transition={{ 
        delay, 
        duration: 1.2, 
        ease: [0.16, 1, 0.3, 1] 
      }}
      className={`absolute ${position} z-10 w-[180px] bg-white/[0.02] backdrop-blur-md border border-white/10 rounded-lg p-4 shadow-2xl`}
    >
      <div className="flex justify-between items-center mb-3">
        <span className="font-mono text-[8px] tracking-[0.2em] text-purple-400/60 uppercase">{name}</span>
        <div className="flex space-x-1.5">
          <div className="w-1 h-1 rounded-full bg-white/10" />
          <div className="w-1 h-1 rounded-full bg-white/10" />
        </div>
      </div>
      
      <div className="h-[1px] w-full bg-gradient-to-r from-transparent via-white/10 to-transparent mb-3" />
      
      <div className="space-y-1.5">
        <div className="flex justify-between items-center font-mono text-[7px] tracking-widest text-slate-500 uppercase">
          <span>Status</span>
          <span className="text-emerald-500/40">Ready</span>
        </div>
        <div className="flex justify-between items-center font-mono text-[7px] tracking-widest text-slate-500 uppercase">
          <span>Bridge</span>
          <span className="text-purple-500/40">Linked</span>
        </div>
      </div>
    </motion.div>
  );
}
