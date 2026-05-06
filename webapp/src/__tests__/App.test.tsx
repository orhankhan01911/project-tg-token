/**
 * Smoke + key-state tests for the App component.
 *
 * Wagmi providers are mocked at the hook level via `vi.mock("wagmi")` —
 * we don't need a real WagmiProvider in the tree for unit tests.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../App";

const mocks = vi.hoisted(() => ({
  useAccount: vi.fn(),
  useChainId: vi.fn(),
  useConnect: vi.fn(),
  useDisconnect: vi.fn(),
  useSignMessage: vi.fn(),
}));

vi.mock("wagmi", async (importOriginal) => {
  const actual = await importOriginal<typeof import("wagmi")>();
  return { ...actual, ...mocks };
});

function renderApp(): void {
  const qc = new QueryClient();
  render(
    <QueryClientProvider client={qc}>
      <App />
    </QueryClientProvider>,
  );
}

describe("App", () => {
  beforeEach(() => {
    mocks.useAccount.mockReturnValue({ address: undefined, isConnected: false });
    mocks.useChainId.mockReturnValue(84532);
    mocks.useConnect.mockReturnValue({
      connectAsync: vi.fn(),
      connectors: [{}],
    });
    mocks.useDisconnect.mockReturnValue({ disconnect: vi.fn() });
    mocks.useSignMessage.mockReturnValue({ signMessageAsync: vi.fn() });
    window.history.replaceState({}, "", "/?chat_id=-100123");
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("renders the Connect wallet CTA when not connected", () => {
    renderApp();
    expect(screen.getByText("Verify your wallet")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /connect wallet/i })).toBeInTheDocument();
  });

  it("renders error UI when chat_id is missing", () => {
    window.history.replaceState({}, "", "/");
    renderApp();
    expect(screen.getByText(/missing/i)).toBeInTheDocument();
  });

  it("shows the address card and Sign button when connected", () => {
    mocks.useAccount.mockReturnValue({
      address: "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045",
      isConnected: true,
    });
    renderApp();
    expect(
      screen.getByText("0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /sign and verify/i }),
    ).toBeInTheDocument();
  });
});
