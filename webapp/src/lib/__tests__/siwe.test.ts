import { describe, expect, it } from "vitest";

import { buildSiweMessage } from "../siwe";

describe("buildSiweMessage", () => {
  const issued = new Date("2026-05-07T00:00:00.000Z");
  const expiry = new Date("2026-05-07T00:05:00.000Z");
  const args = {
    domain: "miniapp.example.com",
    address: "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045" as const,
    uri: "https://miniapp.example.com",
    chainId: 84532,
    nonce: "abc12345",
    statement: "Sign in",
    issuedAt: issued,
    expirationTime: expiry,
  };

  it("emits the canonical EIP-4361 layout with statement", () => {
    const out = buildSiweMessage(args);
    expect(out).toBe(
      [
        "miniapp.example.com wants you to sign in with your Ethereum account:",
        "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045",
        "",
        "Sign in",
        "",
        "URI: https://miniapp.example.com",
        "Version: 1",
        "Chain ID: 84532",
        "Nonce: abc12345",
        "Issued At: 2026-05-07T00:00:00Z",
        "Expiration Time: 2026-05-07T00:05:00Z",
      ].join("\n"),
    );
  });

  it("omits Statement block when no statement is given", () => {
    const out = buildSiweMessage({ ...args, statement: undefined });
    expect(out).toContain(
      "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045\n\nURI: https://miniapp.example.com",
    );
    expect(out).not.toContain("Sign in");
  });

  it("omits Expiration Time when no expiry is given", () => {
    const out = buildSiweMessage({ ...args, expirationTime: undefined });
    expect(out).not.toContain("Expiration Time:");
  });

  it("normalises ISO timestamps to second precision (no millis)", () => {
    const ts = new Date("2026-05-07T12:34:56.789Z");
    const out = buildSiweMessage({ ...args, issuedAt: ts, expirationTime: ts });
    expect(out).toContain("Issued At: 2026-05-07T12:34:56Z");
    expect(out).toContain("Expiration Time: 2026-05-07T12:34:56Z");
  });
});
