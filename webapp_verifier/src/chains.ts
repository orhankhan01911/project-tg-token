/**
 * Chain registry for the verifier. Each entry exposes a `viem` PublicClient
 * scoped to the chain — used by `verifyMessage` to call `isValidSignature`
 * on smart-contract wallets (EIP-1271) and to unwrap the EIP-6492 wrapper
 * for counterfactual deployments.
 *
 * RPC URLs use the chain's public RPC by default. For production traffic,
 * set `<CHAIN>_RPC_URL` env vars (mainnet → Alchemy / Base → Alchemy /
 * Base-Sepolia → Alchemy testnet) so we don't hammer the public endpoint.
 */

import { createPublicClient, http, type PublicClient } from "viem";
import {
  base,
  baseSepolia,
  bsc,
  mainnet,
  polygon,
  sepolia,
} from "viem/chains";

const env = (k: string): string | undefined => process.env[k] || undefined;

export const supportedChains = [
  mainnet,
  sepolia,
  base,
  baseSepolia,
  bsc,
  polygon,
] as const;

const rpcOverrides: Record<number, string | undefined> = {
  [mainnet.id]: env("ETH_RPC_URL"),
  [sepolia.id]: env("SEPOLIA_RPC_URL"),
  [base.id]: env("BASE_RPC_URL"),
  [baseSepolia.id]: env("BASE_SEPOLIA_RPC_URL"),
  [bsc.id]: env("BNB_RPC_URL"),
  [polygon.id]: env("POLYGON_RPC_URL"),
};

export const clients: Record<number, PublicClient> = Object.fromEntries(
  supportedChains.map((c) => [
    c.id,
    createPublicClient({
      chain: c,
      transport: http(rpcOverrides[c.id]),
    }) as PublicClient,
  ]),
);

export function getClient(chainId: number | undefined): PublicClient {
  if (chainId == null) {
    return clients[baseSepolia.id]!;
  }
  const c = clients[chainId];
  if (!c) {
    throw new Error(`unsupported_chain:${chainId}`);
  }
  return c;
}
