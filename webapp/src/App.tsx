import { useEffect, useMemo, useState } from "react";
import {
  useAccount,
  useChainId,
  useConnect,
  useDisconnect,
  useSignMessage,
} from "wagmi";

import { fetchNonce, postVerify } from "./lib/api";
import { hasReownProjectId, openAppKit } from "./lib/appkit";
import { buildSiweMessage } from "./lib/siwe";
import { getWebApp } from "./lib/telegram";
import { chainSlug } from "./lib/wagmi";

type Phase = "idle" | "connecting" | "signing" | "verifying" | "success" | "error";

interface ChatContext {
  chatId: number;
}

function readChatContext(): ChatContext | null {
  // Mini App URL: https://<host>/?chat_id=-100…
  const params = new URLSearchParams(window.location.search);
  const raw = params.get("chat_id");
  if (!raw) return null;
  const chatId = Number(raw);
  if (!Number.isFinite(chatId) || chatId === 0) return null;
  return { chatId };
}

export function App() {
  const webapp = getWebApp();
  const [phase, setPhase] = useState<Phase>("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [okMessage, setOkMessage] = useState<string | null>(null);

  const ctx = useMemo(readChatContext, []);

  const { address, isConnected } = useAccount();
  const chainId = useChainId();
  const { connectAsync, connectors } = useConnect();
  const { signMessageAsync } = useSignMessage();
  const { disconnect } = useDisconnect();

  useEffect(() => {
    webapp.ready();
    webapp.expand();
  }, [webapp]);

  if (!ctx) {
    return (
      <main>
        <h1>tg-token verify</h1>
        <p className="error">
          Missing <code>chat_id</code> in URL. Open this page from the bot's
          "Verify your wallet" button.
        </p>
      </main>
    );
  }

  async function onConnect(): Promise<void> {
    setErrorMessage(null);

    // When AppKit is configured, we delegate the whole connect UX to it.
    // The modal handles WalletConnect + injected + chain switching, then
    // wagmi state updates and `isConnected` flips on its own.
    if (hasReownProjectId && openAppKit()) {
      // Don't switch to "connecting" — the modal owns the UX from here.
      return;
    }

    setPhase("connecting");
    const connector = connectors[0];
    if (!connector) {
      setErrorMessage("No wallet connector available.");
      setPhase("error");
      return;
    }
    try {
      await connectAsync({ connector });
      setPhase("idle");
    } catch (e) {
      setErrorMessage(humanizeError(e, "Could not connect wallet"));
      setPhase("error");
    }
  }

  async function onSignAndVerify(): Promise<void> {
    if (!address) return;
    setErrorMessage(null);
    setPhase("signing");
    try {
      const initData = webapp.initData;
      if (!initData) {
        throw new Error(
          "Telegram initData is empty. Open this page from the bot button, not directly.",
        );
      }
      const nonceResp = await fetchNonce({ initData, chatId: ctx!.chatId });
      const message = buildSiweMessage({
        domain: window.location.host,
        address,
        uri: window.location.origin,
        chainId,
        nonce: nonceResp.nonce,
        statement: "Verify wallet ownership for the gated Telegram chat.",
        issuedAt: new Date(),
        expirationTime: new Date(Date.now() + nonceResp.ttl_seconds * 1000),
      });
      const signature = await signMessageAsync({ message });

      setPhase("verifying");
      const verifyResp = await postVerify({
        initData,
        chatId: ctx!.chatId,
        message,
        signature,
        address,
        chain: chainSlug(chainId),
      });
      if (!verifyResp.ok) {
        throw new Error(`Backend rejected: ${verifyResp.reason ?? "unknown"}`);
      }
      setPhase("success");
      setOkMessage(
        verifyResp.approved_join
          ? "Verified ✓ You've been approved into the chat."
          : "Verified ✓ Your wallet is bound. Open the invite link to join.",
      );
      webapp.HapticFeedback?.notificationOccurred("success");
    } catch (e) {
      webapp.HapticFeedback?.notificationOccurred("error");
      setErrorMessage(humanizeError(e, "Verification failed"));
      setPhase("error");
    }
  }

  return (
    <main>
      <h1>Verify your wallet</h1>
      <p>
        To join the gated chat, prove you control an eligible wallet. Tap below
        to connect and sign — no transaction, no gas.
      </p>

      <div className="spacer" />

      {phase === "success" && okMessage && <p className="ok">{okMessage}</p>}
      {phase === "error" && errorMessage && <p className="error">{errorMessage}</p>}

      {address && (
        <div className="card">
          <div>{address}</div>
        </div>
      )}

      {!isConnected && phase !== "success" && (
        <button onClick={onConnect} disabled={phase === "connecting"}>
          {phase === "connecting" ? "Connecting…" : "Connect wallet"}
        </button>
      )}

      {isConnected && phase !== "success" && (
        <button
          onClick={onSignAndVerify}
          disabled={phase === "signing" || phase === "verifying"}
        >
          {phase === "signing"
            ? "Sign in your wallet…"
            : phase === "verifying"
              ? "Verifying…"
              : "Sign and verify"}
        </button>
      )}

      {isConnected && phase !== "success" && (
        <button className="secondary" onClick={() => disconnect()}>
          Disconnect
        </button>
      )}

      {phase === "success" && (
        <button onClick={() => webapp.close()}>Close</button>
      )}
    </main>
  );
}

function humanizeError(e: unknown, fallback: string): string {
  if (e instanceof Error) {
    if (e.message.includes("User rejected")) return "You rejected the request.";
    if (e.message.includes("init_data_invalid")) return "Telegram session expired. Re-open the verifier from the bot.";
    return e.message;
  }
  return fallback;
}
