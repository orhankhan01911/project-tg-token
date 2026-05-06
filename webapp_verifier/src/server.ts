/**
 * tg-token verifier sidecar.
 *
 * One Express endpoint: POST /verify {message, signature, address, chainId?}
 * → {ok: boolean, error?: string}.
 *
 * Why this is a separate process from the Python backend: viem's
 * `publicClient.verifyMessage` is the canonical EIP-1271 / EIP-6492
 * verifier — it transparently handles plain EOA signatures, smart
 * contract wallets that implement `isValidSignature(hash, signature)`,
 * and counterfactual smart wallets that ship the contract deployment
 * inline via the EIP-6492 wrapper. Re-implementing this in Python
 * means re-implementing several EIP specs by hand — the production-quality
 * bar forbids it.
 *
 * Bound to 127.0.0.1 by default; the Python backend calls us over
 * loopback. Health route at GET /health for systemd watchdog.
 */

import express, { type Request, type Response } from "express";
import { isAddress, type Address, type Hex } from "viem";

import { getClient } from "./chains.js";

const app = express();
app.use(express.json({ limit: "32kb" }));

interface VerifyRequest {
  message?: string;
  signature?: string;
  address?: string;
  chainId?: number;
}

interface VerifyResponse {
  ok: boolean;
  error?: string;
  recovered?: string;
}

app.get("/health", (_req: Request, res: Response) => {
  res.json({ ok: true, version: "0.1.0" });
});

app.post("/verify", async (req: Request, res: Response<VerifyResponse>) => {
  const body = req.body as VerifyRequest;
  const { message, signature, address, chainId } = body || {};

  if (typeof message !== "string" || !message) {
    res.status(400).json({ ok: false, error: "missing_message" });
    return;
  }
  if (typeof signature !== "string" || !signature.startsWith("0x")) {
    res.status(400).json({ ok: false, error: "missing_signature" });
    return;
  }
  if (typeof address !== "string" || !isAddress(address)) {
    res.status(400).json({ ok: false, error: "missing_or_bad_address" });
    return;
  }

  let client;
  try {
    client = getClient(chainId);
  } catch (e: unknown) {
    res.status(400).json({
      ok: false,
      error: e instanceof Error ? e.message : "unsupported_chain",
    });
    return;
  }

  try {
    const ok = await client.verifyMessage({
      address: address as Address,
      message,
      signature: signature as Hex,
    });
    if (!ok) {
      res.json({ ok: false, error: "bad_signature" });
      return;
    }
    res.json({ ok: true, recovered: address });
  } catch (e: unknown) {
    res.status(500).json({
      ok: false,
      error: e instanceof Error ? e.message : "verify_threw",
    });
  }
});

const port = Number(process.env.PORT || 8090);
const host = process.env.HOST || "127.0.0.1";

const server = app.listen(port, host, () => {
  // eslint-disable-next-line no-console
  console.log(JSON.stringify({ event: "verifier_listening", host, port }));
});

const shutdown = (signal: string) => {
  // eslint-disable-next-line no-console
  console.log(JSON.stringify({ event: "verifier_shutdown", signal }));
  server.close(() => process.exit(0));
};
process.on("SIGINT", () => shutdown("SIGINT"));
process.on("SIGTERM", () => shutdown("SIGTERM"));
