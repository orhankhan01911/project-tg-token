/**
 * wagmi config. v0 supports EIP-6963 / injected wallets only (MetaMask,
 * Rabby, OKX, Coinbase Wallet extension, etc.). WalletConnect is
 * deferred until a Reown project ID is provisioned; documented in
 * RUNBOOK.md.
 *
 * The chain set must include any chain a user might attempt to verify
 * on. Adding a chain here without also adding the corresponding RPC
 * override on the verifier sidecar is fine — the sidecar's default is
 * `http()` (public RPC), same as here.
 */

import {
  createConfig,
  fallback,
  http,
  type Config,
  type CreateConfigParameters,
} from "wagmi";
import { base, baseSepolia, bsc, mainnet, polygon, sepolia } from "wagmi/chains";
import { injected } from "wagmi/connectors";

import { getAppKitWagmiConfig, hasReownProjectId } from "./appkit";

const chains = [mainnet, sepolia, base, baseSepolia, bsc, polygon] as const;

const fallbackConfig: Config = createConfig({
  chains,
  connectors: [injected({ shimDisconnect: true })],
  transports: {
    [mainnet.id]: fallback([http()]),
    [sepolia.id]: fallback([http()]),
    [base.id]: fallback([http()]),
    [baseSepolia.id]: fallback([http()]),
    [bsc.id]: fallback([http()]),
    [polygon.id]: fallback([http()]),
  },
} satisfies CreateConfigParameters);

/**
 * Single source of truth for the wagmi `Config` we hand to <WagmiProvider>.
 * - With Reown project ID: AppKit's WagmiAdapter owns the config (it adds
 *   the WalletConnect connector + storage + chain switching glue).
 * - Without: plain injected-only config above.
 */
export const config: Config = hasReownProjectId
  ? (getAppKitWagmiConfig() ?? fallbackConfig)
  : fallbackConfig;

/**
 * Map a numeric chainId to the `chain` enum value the backend's
 * `Chain` model expects (`base-sepolia` etc.). Keep aligned with
 * `app/models/gate.py:Chain`.
 */
export function chainSlug(chainId: number): string {
  switch (chainId) {
    case mainnet.id:
      return "eth";
    case sepolia.id:
      return "eth"; // backend lumps eth + sepolia for v0; revisit
    case base.id:
      return "base";
    case baseSepolia.id:
      return "base-sepolia";
    case bsc.id:
      return "bnb";
    case polygon.id:
      return "polygon";
    default:
      return "base-sepolia";
  }
}
