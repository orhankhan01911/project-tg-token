import { HeroGeometric } from "@/components/ui/shape-landing-hero";
import { GlowCard } from "@/components/ui/spotlight-card";
import { motion } from "framer-motion";
import { Lock, DollarSign, Shield, UserCheck, Trash2, Link2 } from "lucide-react";

const fadeUp = {
  hidden: { opacity: 0, y: 24 },
  visible: (i = 0) => ({
    opacity: 1, y: 0,
    transition: { duration: 0.7, delay: i * 0.1, ease: "easeOut" as const },
  }),
};

const FEATURES = [
  { icon: Lock, title: "Token-Based Access", desc: "Gate on any ERC-20, SPL, or Jetton. Members must hold the minimum to enter and stay." },
  { icon: DollarSign, title: "USD-Denominated Gates", desc: "Set thresholds in USD. The bot prices tokens live via DexScreener — gate on $50 of value, not raw amounts." },
  { icon: Shield, title: "Secure Wallet Verification", desc: "Ownership proven by a tiny self-transfer. No seed phrases, no extensions, no custody of funds." },
  { icon: UserCheck, title: "Admin Whitelisting", desc: "Permanent access for admins and trusted users without token verification." },
  { icon: Trash2, title: "Automatic Purging", desc: "Monthly sweeps remove users who no longer meet requirements. Fully automatic, no loopholes." },
  { icon: Link2, title: "Multichain Support", desc: "ETH, Base, Solana, TON — one bot, all chains. Bridged tokens treated as a single gate." },
];

const STEPS = [
  { n: "1", title: "Create Your Gate", desc: "Define the token, network, and USD threshold. Takes under 2 minutes." },
  { n: "2", title: "Users Verify", desc: "Users prove wallet ownership via a self-transfer dust proof — no seed phrases, no extensions." },
  { n: "3", title: "Access is Granted", desc: "The bot checks on-chain balance and approves join requests instantly." },
  { n: "4", title: "Purges Maintain Standards", desc: "Monthly sweeps auto-remove members who no longer meet requirements." },
];

const CHAINS = [
  { img: "https://assets.coingecko.com/coins/images/279/small/ethereum.png", name: "Ethereum", sub: "ERC-20" },
  { img: "https://assets.coingecko.com/asset_platforms/images/131/small/base.jpeg", name: "Base", sub: "ERC-20" },
  { img: "https://assets.coingecko.com/coins/images/4128/small/solana.png", name: "Solana", sub: "SPL" },
  { img: "https://assets.coingecko.com/coins/images/17980/small/ton_symbol.png", name: "TON", sub: "Jetton" },
];

const AUDIENCE = [
  { emoji: "🐋", title: "Whale Groups", desc: "Gate your holder community. Sell tokens = lose access automatically on the next sweep.", tags: ["ERC-20", "SPL", "Jetton"] },
  { emoji: "📡", title: "Exclusive Communities", desc: "Monetize your alpha group with a USD threshold. Keep signals exclusive and valuable.", tags: ["USD gate", "Multi-token"] },
  { emoji: "📢", title: "Alpha Callers", desc: "Token-gate your calls channel. Only committed holders get access. No dilution.", tags: ["Multi-chain", "Auto-purge"] },
];

function SectionBadge({ children }: { children: React.ReactNode }) {
  return (
    <div className="inline-flex items-center gap-2 text-xs font-semibold tracking-widest uppercase text-[#7288ae] mb-4">
      <span className="text-[10px]">★</span>
      {children}
    </div>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="text-3xl sm:text-4xl font-bold tracking-tight text-[#eae0cf] mb-3" style={{ letterSpacing: "-0.02em" }}>
      {children}
    </h2>
  );
}

function Hl({ children }: { children: React.ReactNode }) {
  return (
    <span className="bg-clip-text text-transparent bg-gradient-to-r from-[#7288ae] to-[#eae0cf]/90">
      {children}
    </span>
  );
}

export default function App() {
  return (
    <div className="bg-[#0c1235] min-h-screen overflow-x-hidden relative">
      {/* Full-page background mesh */}
      <div className="fixed inset-0 z-0 pointer-events-none"
        style={{
          background: `
            radial-gradient(ellipse 80% 40% at 50% 0%, rgba(75,86,148,0.3) 0%, transparent 60%),
            radial-gradient(ellipse 60% 30% at 80% 50%, rgba(114,136,174,0.1) 0%, transparent 50%),
            radial-gradient(ellipse 50% 30% at 10% 80%, rgba(75,86,148,0.08) 0%, transparent 50%),
            radial-gradient(ellipse 70% 40% at 50% 100%, rgba(75,86,148,0.12) 0%, transparent 60%)
          `
        }}
      />
      {/* NAV */}
      <nav className="fixed top-0 left-0 right-0 z-50 bg-[#0c1235]/85 backdrop-blur-xl border-b border-white/[0.06]">
        <div className="max-w-6xl mx-auto px-6 h-16 flex items-center justify-between">
          <a href="/" className="flex items-center gap-2.5 no-underline">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-[#4b5694] to-[#7288ae] flex items-center justify-center">
              <svg width="16" height="16" viewBox="0 0 18 18" fill="none">
                <rect x="4" y="2" width="10" height="7" rx="1.5" stroke="#eae0cf" strokeWidth="1.6"/>
                <rect x="2.5" y="8" width="13" height="8" rx="1.5" fill="#eae0cf" fillOpacity=".15" stroke="#eae0cf" strokeWidth="1.2"/>
                <circle cx="9" cy="12" r="1.8" fill="#eae0cf"/>
              </svg>
            </div>
            <span className="text-[#eae0cf] font-bold text-base tracking-tight">
              Gate<span className="text-[#7288ae]">kept</span>
            </span>
          </a>
          <div className="hidden md:flex items-center gap-7">
            {["#features", "#how-it-works", "#chains"].map((href, i) => (
              <a key={i} href={href} className="text-[#eae0cf]/50 hover:text-[#eae0cf] text-sm font-medium transition-colors no-underline">
                {["Features", "How It Works", "Chains"][i]}
              </a>
            ))}
          </div>
          <a
            href="https://web.telegram.org/k/#@derivativesmonkey"
            className="inline-flex items-center gap-2 bg-gradient-to-r from-[#5568b0] to-[#8099c8] text-[#eae0cf] text-sm font-semibold px-4 py-2 rounded-lg hover:opacity-90 transition-all no-underline min-h-[36px] shadow-[0_4px_24px_rgba(85,104,176,0.5)] hover:shadow-[0_8px_32px_rgba(85,104,176,0.7)]"
          >
            <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="currentColor">
              <path d="M12 0C5.373 0 0 5.373 0 12s5.373 12 12 12 12-5.373 12-12S18.627 0 12 0zm5.562 8.248l-2.04 9.61c-.148.658-.537.818-1.084.508l-3-2.21-1.447 1.394c-.16.16-.295.295-.605.295l.213-3.053 5.56-5.023c.242-.213-.054-.333-.373-.12l-6.871 4.326-2.962-.924c-.643-.204-.657-.643.136-.953l11.57-4.461c.537-.194 1.006.131.903.611z"/>
            </svg>
            Get Started
          </a>
        </div>
      </nav>

      {/* HERO */}
      <HeroGeometric
        badge="Token-Gated Telegram · Non-custodial"
        title1="Secure Your Community"
        title2="With Blockchain Access"
      />

      {/* FEATURES */}
      <section id="features" className="py-20 px-6 relative z-10">
        <div className="max-w-6xl mx-auto">
          <motion.div className="text-center mb-14" initial="hidden" whileInView="visible" viewport={{ once: true }}>
            <SectionBadge>Key Features</SectionBadge>
            <SectionTitle>Powerful <Hl>Token Gates</Hl></SectionTitle>
            <p className="text-[#eae0cf]/65 text-base max-w-lg mx-auto">
              Everything you need to run an exclusive, always-enforced token community.
            </p>
          </motion.div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5 items-stretch">
            {FEATURES.map((f, i) => (
              <motion.div
                key={i} custom={i * 0.1}
                variants={fadeUp} initial="hidden" whileInView="visible" viewport={{ once: true }}
                className="h-full"
              >
                <GlowCard customSize glowColor="indigo" className="w-full !grid-rows-none !aspect-auto block p-7">
                  <div className="w-11 h-11 rounded-xl bg-gradient-to-br from-[#4b5694]/30 to-[#7288ae]/20 flex items-center justify-center mb-5">
                    <f.icon className="w-5 h-5 text-[#7288ae]" />
                  </div>
                  <div className="font-bold text-[#eae0cf] mb-2">{f.title}</div>
                  <div className="text-[#eae0cf]/80 text-sm leading-relaxed">{f.desc}</div>
                </GlowCard>
              </motion.div>
            ))}
          </div>
        </div>
      </section>

      {/* HOW IT WORKS */}
      <section id="how-it-works" className="py-16 px-6 border-t border-white/[0.05] relative z-10">
        <div className="max-w-6xl mx-auto">
          <div className="text-center mb-14">
            <SectionBadge>Simple Process</SectionBadge>
            <SectionTitle>How It <Hl>Works</Hl></SectionTitle>
            <p className="text-[#eae0cf]/65 text-base max-w-md mx-auto">
              4-step process to secure your Telegram community with blockchain-powered access control.
            </p>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-12 items-center">
            <div className="space-y-0">
              {STEPS.map((s, i) => (
                <motion.div
                  key={i} custom={i * 0.15}
                  variants={fadeUp} initial="hidden" whileInView="visible" viewport={{ once: true }}
                  className="flex gap-5 py-6 border-b border-white/[0.06] last:border-0"
                >
                  <div className="flex flex-col items-center gap-0 flex-shrink-0">
                    <div className="w-9 h-9 rounded-full bg-gradient-to-br from-[#4b5694] to-[#7288ae] flex items-center justify-center text-[#eae0cf] font-bold text-sm">
                      {s.n}
                    </div>
                    {i < STEPS.length - 1 && (
                      <div className="w-px flex-1 min-h-[24px] bg-white/[0.06] mt-1" />
                    )}
                  </div>
                  <div className="pt-1.5">
                    <div className="font-bold text-[#eae0cf] mb-1.5">{s.title}</div>
                    <div className="text-[#eae0cf]/50 text-sm leading-relaxed">{s.desc}</div>
                  </div>
                </motion.div>
              ))}
            </div>

            {/* Verification panel */}
            <motion.div
              variants={fadeUp} initial="hidden" whileInView="visible" viewport={{ once: true }}
              className="bg-white/[0.03] border border-white/[0.08] rounded-2xl p-6"
            >
              <div className="font-mono text-[11px] tracking-widest uppercase text-[#eae0cf]/30 mb-5">
                Live verification · gatekept-agent
              </div>
              {[
                { icon: "⛓️", label: "Chain", value: "Base Mainnet" },
                { icon: "💰", label: "Token gate", value: "$50 USDC min" },
                { icon: "👛", label: "Wallet", value: "0x4f2b…9e1c" },
                { icon: "📊", label: "Balance", value: "$847 USDC" },
                { icon: "✓", label: "Threshold check", value: null, pass: true },
                { icon: "🚀", label: "Result", value: null, granted: true },
              ].map((r, i) => (
                <div key={i} className="flex items-center gap-3 py-3 border-b border-white/[0.05] last:border-0">
                  <div className="w-8 h-8 rounded-lg bg-white/[0.05] flex items-center justify-center text-sm flex-shrink-0">
                    {r.icon}
                  </div>
                  <span className="text-[#eae0cf]/50 text-sm flex-1">{r.label}</span>
                  {r.value && <span className="font-mono text-xs text-[#eae0cf]/80">{r.value}</span>}
                  {r.pass && <span className="font-mono text-[11px] px-2 py-0.5 rounded bg-green-500/10 border border-green-500/20 text-green-400">PASS</span>}
                  {r.granted && <span className="font-mono text-[11px] px-2 py-0.5 rounded bg-green-500/10 border border-green-500/20 text-green-400">ACCESS GRANTED</span>}
                </div>
              ))}
            </motion.div>
          </div>
        </div>
      </section>

      {/* CHAINS */}
      <section id="chains" className="py-16 px-6 border-t border-white/[0.05] relative z-10">
        <div className="max-w-6xl mx-auto text-center">
          <SectionBadge>Multi-Chain Support</SectionBadge>
          <SectionTitle>Supported <Hl>Blockchains</Hl></SectionTitle>
          <p className="text-[#eae0cf]/65 text-base max-w-sm mx-auto mb-12">
            Multi-chain support for flexible token gating across different networks.
          </p>
          <div className="flex gap-5 justify-center flex-wrap">
            {CHAINS.map((c, i) => (
              <motion.div
                key={i} custom={i * 0.1}
                variants={fadeUp} initial="hidden" whileInView="visible" viewport={{ once: true }}
                className="bg-white/[0.03] border border-white/[0.07] rounded-2xl px-8 py-6 text-center min-w-[130px] hover:border-white/[0.15] hover:-translate-y-1 transition-all"
              >
                <img src={c.img} alt={c.name} className="w-10 h-10 rounded-full object-contain mb-3 mx-auto" />
                <div className="font-bold text-[#eae0cf] text-sm">{c.name}</div>
                <div className="font-mono text-[10px] text-[#eae0cf]/30 mt-1 tracking-wider">{c.sub}</div>
              </motion.div>
            ))}
          </div>
        </div>
      </section>

      {/* AUDIENCE */}
      <section className="py-16 px-6 border-t border-white/[0.05] relative z-10">
        <div className="max-w-6xl mx-auto">
          <div className="text-center mb-14">
            <SectionBadge>Target Audience</SectionBadge>
            <SectionTitle>Who's It <Hl>For?</Hl></SectionTitle>
            <p className="text-[#eae0cf]/65 text-base max-w-md mx-auto">
              Perfect for creators, communities, and projects looking to gate access.
            </p>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
            {AUDIENCE.map((a, i) => (
              <motion.div
                key={i} custom={i * 0.1}
                variants={fadeUp} initial="hidden" whileInView="visible" viewport={{ once: true }}
                className="bg-white/[0.03] border border-white/[0.07] rounded-2xl p-7 hover:border-white/[0.15] hover:-translate-y-1 transition-all"
              >
                <span className="text-3xl mb-4 block">{a.emoji}</span>
                <div className="font-bold text-[#eae0cf] text-base mb-2">{a.title}</div>
                <div className="text-[#eae0cf]/50 text-sm leading-relaxed mb-4">{a.desc}</div>
                <div className="flex flex-wrap gap-2">
                  {a.tags.map((t) => (
                    <span key={t} className="text-[10px] font-semibold tracking-widest uppercase text-[#7288ae] bg-[#4b5694]/10 border border-[#4b5694]/20 px-2 py-1 rounded">
                      {t}
                    </span>
                  ))}
                </div>
              </motion.div>
            ))}
          </div>
        </div>
      </section>

      {/* CTA */}
      <section id="contact" className="py-16 px-6 border-t border-white/[0.05] relative z-10">
        <div className="max-w-6xl mx-auto">
          <div className="relative bg-white/[0.03] border border-white/[0.08] rounded-3xl p-16 text-center overflow-hidden">
            <div className="absolute top-0 left-1/2 -translate-x-1/2 w-96 h-40 bg-gradient-to-b from-[#4b5694]/20 to-transparent blur-2xl pointer-events-none" />
            <div className="relative z-10">
              <SectionBadge>Get Started</SectionBadge>
              <h2 className="text-3xl sm:text-4xl font-bold text-[#eae0cf] mb-4 tracking-tight" style={{ letterSpacing: "-0.02em" }}>
                Start Building Your <Hl>Gate</Hl>
              </h2>
              <p className="text-[#eae0cf]/65 text-base mb-8 max-w-sm mx-auto">
                We'll configure your token gate in under 2 minutes. Contact us on Telegram.
              </p>
              <a
                href="https://web.telegram.org/k/#@derivativesmonkey"
                className="inline-flex items-center gap-2.5 bg-gradient-to-r from-[#5568b0] to-[#8099c8] text-[#eae0cf] font-semibold text-base px-8 py-4 rounded-xl hover:opacity-90 hover:-translate-y-0.5 transition-all shadow-[0_4px_24px_rgba(85,104,176,0.5)] hover:shadow-[0_8px_32px_rgba(85,104,176,0.7)] no-underline min-h-[44px]"
              >
                <svg className="w-4 h-4" viewBox="0 0 24 24" fill="currentColor">
                  <path d="M12 0C5.373 0 0 5.373 0 12s5.373 12 12 12 12-5.373 12-12S18.627 0 12 0zm5.562 8.248l-2.04 9.61c-.148.658-.537.818-1.084.508l-3-2.21-1.447 1.394c-.16.16-.295.295-.605.295l.213-3.053 5.56-5.023c.242-.213-.054-.333-.373-.12l-6.871 4.326-2.962-.924c-.643-.204-.657-.643.136-.953l11.57-4.461c.537-.194 1.006.131.903.611z"/>
                </svg>
                Contact us on Telegram
              </a>
              <div className="font-mono text-xs text-[#eae0cf]/25 mt-4 tracking-wide">
                Response within a few hours · Setup takes ~2 minutes
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* FOOTER */}
      <footer className="border-t border-white/[0.05] py-8 px-6 relative z-10">
        <div className="max-w-6xl mx-auto flex items-center justify-between flex-wrap gap-4">
          <div className="font-semibold text-sm text-[#eae0cf]/30 tracking-wide">
            <span className="text-[#7288ae]">Gatekept</span> · Token-gated Telegram · Non-custodial
          </div>
          <div className="flex gap-6">
            {[["#features", "Features"], ["#how-it-works", "How it works"], ["https://web.telegram.org/k/#@derivativesmonkey", "Contact"]].map(([href, label]) => (
              <a key={href} href={href} className="text-xs text-[#eae0cf]/30 hover:text-[#eae0cf]/70 transition-colors no-underline font-medium">
                {label}
              </a>
            ))}
          </div>
        </div>
      </footer>
    </div>
  );
}
