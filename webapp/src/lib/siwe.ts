/**
 * Build a SIWE (EIP-4361) message string client-side.
 *
 * The backend re-parses (with our regex parser) and re-validates every
 * field. This file produces the canonical wire form the wallet will sign.
 * We do *not* depend on any SIWE npm package — the format is small, fixed,
 * and stable. Same reasoning as the Python regex parser in
 * `app/auth/siwe_parse.py`.
 */

export interface SiweArgs {
  domain: string;
  address: `0x${string}`;
  uri: string;
  chainId: number;
  nonce: string;
  statement?: string;
  issuedAt: Date;
  expirationTime?: Date;
}

function iso(d: Date): string {
  // SIWE wants ISO8601 with second precision and a trailing Z.
  return d.toISOString().replace(/\.\d{3}Z$/, "Z");
}

export function buildSiweMessage(args: SiweArgs): string {
  const lines: string[] = [
    `${args.domain} wants you to sign in with your Ethereum account:`,
    args.address,
    "",
  ];
  if (args.statement) {
    lines.push(args.statement, "");
  }
  lines.push(
    `URI: ${args.uri}`,
    `Version: 1`,
    `Chain ID: ${args.chainId}`,
    `Nonce: ${args.nonce}`,
    `Issued At: ${iso(args.issuedAt)}`,
  );
  if (args.expirationTime) {
    lines.push(`Expiration Time: ${iso(args.expirationTime)}`);
  }
  return lines.join("\n");
}
