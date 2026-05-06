import "@testing-library/jest-dom/vitest";
import { vi } from "vitest";

// Stub Reown AppKit at the module level. The real packages have a deep
// dependency on `@walletconnect/logger` which trips vitest's CJS/ESM
// interop in node/happy-dom test envs. We never want the real WC relay
// reaching out from a unit test anyway — the integration boundary is
// the live live smoke in RUNBOOK.
vi.mock("@reown/appkit/react", () => ({
  createAppKit: vi.fn(() => ({ open: vi.fn(), close: vi.fn() })),
}));
vi.mock("@reown/appkit-adapter-wagmi", () => ({
  WagmiAdapter: vi.fn().mockImplementation(() => ({ wagmiConfig: null })),
}));
vi.mock("@reown/appkit/networks", () => ({
  mainnet: { id: 1 },
  sepolia: { id: 11155111 },
  base: { id: 8453 },
  baseSepolia: { id: 84532 },
  bsc: { id: 56 },
  polygon: { id: 137 },
}));
