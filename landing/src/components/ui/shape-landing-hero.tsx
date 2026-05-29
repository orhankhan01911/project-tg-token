"use client";

import { motion } from "framer-motion";
import { Circle } from "lucide-react";
import { cn } from "@/lib/utils";

function ElegantShape({
  className,
  delay = 0,
  width = 400,
  height = 100,
  rotate = 0,
  gradient = "from-white/[0.08]",
}: {
  className?: string;
  delay?: number;
  width?: number;
  height?: number;
  rotate?: number;
  gradient?: string;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: -150, rotate: rotate - 15 }}
      animate={{ opacity: 1, y: 0, rotate: rotate }}
      transition={{
        duration: 2.4,
        delay,
        ease: [0.23, 0.86, 0.39, 0.96],
        opacity: { duration: 1.2 },
      }}
      className={cn("absolute", className)}
    >
      <motion.div
        animate={{ y: [0, 15, 0] }}
        transition={{ duration: 12, repeat: Infinity, ease: "easeInOut" }}
        style={{ width, height }}
        className="relative"
      >
        <div
          className={cn(
            "absolute inset-0 rounded-full",
            "bg-gradient-to-r to-transparent",
            gradient,
            "backdrop-blur-[2px] border-2 border-white/[0.12]",
            "shadow-[0_8px_32px_0_rgba(114,136,174,0.15)]",
            "after:absolute after:inset-0 after:rounded-full",
            "after:bg-[radial-gradient(circle_at_50%_50%,rgba(234,224,207,0.08),transparent_70%)]"
          )}
        />
      </motion.div>
    </motion.div>
  );
}

function HeroGeometric({
  badge = "Token-Gated Telegram",
  title1 = "Secure Your Community",
  title2 = "With Blockchain Access",
}: {
  badge?: string;
  title1?: string;
  title2?: string;
}) {
  const fadeUpVariants = {
    hidden: { opacity: 0, y: 30 },
    visible: (i: number) => ({
      opacity: 1,
      y: 0,
      transition: {
        duration: 1,
        delay: 0.5 + i * 0.2,
        ease: "easeOut" as const,
      },
    }),
  };

  return (
    <div className="relative min-h-screen w-full flex items-center justify-center overflow-hidden bg-[#0c1235]">
      {/* Gradient mesh */}
      <div className="absolute inset-0 bg-gradient-to-br from-[#4b5694]/[0.15] via-transparent to-[#7288ae]/[0.08] blur-3xl" />

      {/* Floating shapes */}
      <div className="absolute inset-0 overflow-hidden">
        <ElegantShape
          delay={0.3} width={600} height={140} rotate={12}
          gradient="from-[#4b5694]/[0.2]"
          className="left-[-10%] md:left-[-5%] top-[15%] md:top-[20%]"
        />
        <ElegantShape
          delay={0.5} width={500} height={120} rotate={-15}
          gradient="from-[#7288ae]/[0.18]"
          className="right-[-5%] md:right-[0%] top-[70%] md:top-[75%]"
        />
        <ElegantShape
          delay={0.4} width={300} height={80} rotate={-8}
          gradient="from-[#4b5694]/[0.15]"
          className="left-[5%] md:left-[10%] bottom-[5%] md:bottom-[10%]"
        />
        <ElegantShape
          delay={0.6} width={200} height={60} rotate={20}
          gradient="from-[#7288ae]/[0.15]"
          className="right-[15%] md:right-[20%] top-[10%] md:top-[15%]"
        />
        <ElegantShape
          delay={0.7} width={150} height={40} rotate={-25}
          gradient="from-[#eae0cf]/[0.08]"
          className="left-[20%] md:left-[25%] top-[5%] md:top-[10%]"
        />
      </div>

      {/* Content */}
      <div className="relative z-10 container mx-auto px-4 md:px-6">
        <div className="max-w-3xl mx-auto text-center">
          <motion.div
            custom={0}
            variants={fadeUpVariants}
            initial="hidden"
            animate="visible"
            className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-white/[0.04] border border-white/[0.08] mb-8 md:mb-10"
          >
            <Circle className="h-2 w-2 fill-[#7288ae]" />
            <span className="text-sm text-[#eae0cf]/60 tracking-wide font-medium">
              {badge}
            </span>
          </motion.div>

          <motion.div custom={1} variants={fadeUpVariants} initial="hidden" animate="visible">
            <h1 className="text-4xl sm:text-6xl md:text-7xl font-bold mb-6 md:mb-8 tracking-tight">
              <span className="bg-clip-text text-transparent bg-gradient-to-b from-[#eae0cf] to-[#eae0cf]/80">
                {title1}
              </span>
              <br />
              <span className="bg-clip-text text-transparent bg-gradient-to-r from-[#7288ae] via-[#eae0cf]/90 to-[#4b5694]">
                {title2}
              </span>
            </h1>
          </motion.div>

          <motion.div custom={2} variants={fadeUpVariants} initial="hidden" animate="visible">
            <p className="text-base sm:text-lg md:text-xl text-[#eae0cf]/40 mb-10 leading-relaxed font-light tracking-wide max-w-xl mx-auto px-4">
              Non-custodial wallet verification. Automatic monthly purges. Zero manual moderation.
            </p>
          </motion.div>

          <motion.div
            custom={3}
            variants={fadeUpVariants}
            initial="hidden"
            animate="visible"
            className="flex gap-4 justify-center flex-wrap"
          >
            <a
              href="https://web.telegram.org/k/#@derivativesmonkey"
              className="inline-flex items-center gap-2 bg-gradient-to-r from-[#4b5694] to-[#7288ae] text-[#eae0cf] font-semibold text-base px-7 py-3.5 rounded-xl transition-all hover:opacity-90 hover:-translate-y-0.5 shadow-lg shadow-[#4b5694]/30"
            >
              <svg className="w-4 h-4" viewBox="0 0 24 24" fill="currentColor">
                <path d="M12 0C5.373 0 0 5.373 0 12s5.373 12 12 12 12-5.373 12-12S18.627 0 12 0zm5.562 8.248l-2.04 9.61c-.148.658-.537.818-1.084.508l-3-2.21-1.447 1.394c-.16.16-.295.295-.605.295l.213-3.053 5.56-5.023c.242-.213-.054-.333-.373-.12l-6.871 4.326-2.962-.924c-.643-.204-.657-.643.136-.953l11.57-4.461c.537-.194 1.006.131.903.611z"/>
              </svg>
              Get Started Now
            </a>
            <a
              href="#how-it-works"
              className="inline-flex items-center gap-2 bg-white/[0.04] border border-white/[0.1] text-[#eae0cf]/70 font-semibold text-base px-7 py-3.5 rounded-xl transition-all hover:bg-white/[0.08] hover:border-white/[0.2] hover:-translate-y-0.5"
            >
              ▶ How It Works
            </a>
          </motion.div>

          {/* Chain chips */}
          <motion.div
            custom={4}
            variants={fadeUpVariants}
            initial="hidden"
            animate="visible"
            className="flex items-center justify-center gap-3 mt-12 flex-wrap"
          >
            <span className="text-xs text-[#eae0cf]/30 font-medium tracking-wide">Powered by</span>
            {[
              { dot: "#627eea", name: "Ethereum" },
              { dot: "#5b8fff", name: "Base" },
              { dot: "#9945ff", name: "Solana" },
              { dot: "#0098ea", name: "TON" },
            ].map((c) => (
              <div
                key={c.name}
                className="inline-flex items-center gap-1.5 bg-white/[0.04] border border-white/[0.08] px-3 py-1 rounded-full text-xs font-medium text-[#eae0cf]/60"
              >
                <span className="w-1.5 h-1.5 rounded-full" style={{ background: c.dot }} />
                {c.name}
              </div>
            ))}
          </motion.div>
        </div>
      </div>

      {/* Top/bottom fade */}
      <div className="absolute inset-0 bg-gradient-to-t from-[#0c1235] via-transparent to-[#0c1235]/60 pointer-events-none" />
    </div>
  );
}

export { HeroGeometric };
