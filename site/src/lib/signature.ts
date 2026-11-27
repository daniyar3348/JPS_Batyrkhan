/** Requests from the platform to rebuild pages are signed: HMAC-SHA256 of the body with a shared secret. */
import { createHmac, timingSafeEqual } from "node:crypto";

/** How old a request may be: a captured request cannot be replayed later. */
export const MAX_AGE_SECONDS = 300;

export function sign(secret: string, body: string): string {
  return `sha256=${createHmac("sha256", secret).update(body, "utf8").digest("hex")}`;
}

export function validSignature(secret: string, body: string, header: string | null): boolean {
  if (!header) return false;
  const expected = Buffer.from(sign(secret, body));
  const given = Buffer.from(header.trim());
  return expected.length === given.length && timingSafeEqual(expected, given);
}

export interface RevalidationRequest {
  paths: string[];
  sent_at: string;
}

/** The body, if it is well formed and recent; otherwise null. */
export function parseRequest(body: string, now: Date = new Date()): RevalidationRequest | null {
  let data: unknown;
  try {
    data = JSON.parse(body);
  } catch {
    return null;
  }
  if (typeof data !== "object" || data === null) return null;
  const { paths, sent_at } = data as Record<string, unknown>;
  if (
    !Array.isArray(paths) ||
    !paths.every((p) => typeof p === "string" && (p === "*" || p.startsWith("/")))
  ) {
    return null;
  }
  if (typeof sent_at !== "string") return null;
  const sent = Date.parse(sent_at);
  if (Number.isNaN(sent)) return null;
  const age = (now.getTime() - sent) / 1000;
  if (age > MAX_AGE_SECONDS || age < -60) return null;
  return { paths: paths as string[], sent_at };
}
