/**
 * Backend client for `/siwe/nonce` and `/siwe/verify`.
 *
 * Both routes require Telegram `initData` for auth. We pass it on every
 * call. In dev, with `vite dev` proxying `/api/*` to `http://127.0.0.1:8001`,
 * relative paths work out of the box. In production, `VITE_API_URL` is
 * the absolute URL (e.g. `https://api.tg-token.example.com`).
 */

const baseUrl = import.meta.env.VITE_API_URL?.replace(/\/$/, "") ?? "";

export interface NonceResponse {
  nonce: string;
  ttl_seconds: number;
}

export interface VerifyResponse {
  ok: boolean;
  address?: string;
  approved_join?: boolean;
  reason?: string;
}

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly body: unknown,
  ) {
    super(`api ${status}`);
  }
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${baseUrl}${path}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  let data: unknown;
  try {
    data = await res.json();
  } catch {
    data = undefined;
  }
  if (!res.ok) {
    throw new ApiError(res.status, data);
  }
  return data as T;
}

export function fetchNonce(args: {
  initData: string;
  chatId: number;
}): Promise<NonceResponse> {
  return post<NonceResponse>("/api/siwe/nonce", {
    initData: args.initData,
    chat_id: args.chatId,
  });
}

export function postVerify(args: {
  initData: string;
  chatId: number;
  message: string;
  signature: string;
  address: string;
  chain: string;
}): Promise<VerifyResponse> {
  return post<VerifyResponse>("/api/siwe/verify", {
    initData: args.initData,
    chat_id: args.chatId,
    message: args.message,
    signature: args.signature,
    address: args.address,
    chain: args.chain,
  });
}
