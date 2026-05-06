/**
 * Reown AppKit (formerly WalletConnect Web3Modal) wiring.
 *
 * Two modes:
 *
 * 1. **With project ID** (`VITE_REOWN_PROJECT_ID` set): registers the
 *    WagmiAdapter, exposes a polished modal that lists every WC v2
 *    wallet plus any injected wallet on the page. This is the path
 *    that lets a Telegram-mobile-webview user pick their phone wallet.
 *
 * 2. **Without project ID** (env var empty): we don't initialize AppKit
 *    at all and `openAppKit()` becomes a no-op. The app falls back to
 *    plain wagmi `useConnect()` against the `injected()` connector.
 *    Useful for unit tests, local dev without a Reown account, and as
 *    a clean failure mode if the relay is down.
 *
 * Decision rationale: the production-quality bar says "no silent
 * degradation". Splitting the modes explicitly means both paths are
 * testable, and the codebase doesn't carry dead WalletConnect setup
 * when it's intentionally disabled.
 */

import { createAppKit } from "@reown/appkit/react";
import { base, baseSepolia, bsc, mainnet, polygon, sepolia } from "@reown/appkit/networks";
import { WagmiAdapter } from "@reown/appkit-adapter-wagmi";
import type { Config } from "wagmi";

const projectId = import.meta.env.VITE_REOWN_PROJECT_ID ?? "";
export const hasReownProjectId = projectId.length > 0;

const networks = [mainnet, sepolia, base, baseSepolia, bsc, polygon] as const;

let modalOpenFn: (() => void) | null = null;
let appKitWagmiConfig: Config | null = null;

if (hasReownProjectId) {
  const adapter = new WagmiAdapter({
    projectId,
    networks: [...networks],
  });
  appKitWagmiConfig = adapter.wagmiConfig as Config;

  const modal = createAppKit({
    adapters: [adapter],
    networks: [...networks],
    projectId,
    metadata: {
      name: "tg-token verify",
      description: "Verify wallet ownership for a gated Telegram chat.",
      url: typeof window !== "undefined" ? window.location.origin : "",
      icons: [],
    },
    features: {
      analytics: false,
      email: false,
      socials: false,
    },
  });

  modalOpenFn = () => modal.open();
}

export function getAppKitWagmiConfig(): Config | null {
  return appKitWagmiConfig;
}

/** Open the AppKit modal. Returns false if AppKit isn't initialized. */
export function openAppKit(): boolean {
  if (!modalOpenFn) return false;
  modalOpenFn();
  return true;
}
