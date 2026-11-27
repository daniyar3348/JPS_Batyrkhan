/**
 * Runs once when the server starts. Pages built by `next build` had no API to read from, so the server
 * asks itself to rebuild every page as soon as it is up (signed like the platform's own requests).
 */
export async function register() {
  if (process.env.NEXT_RUNTIME !== "nodejs" || process.env.NODE_ENV !== "production") return;
  const secret = process.env.JPS_REVALIDATE_SECRET;
  if (!secret) return;
  const { sign } = await import("./lib/signature");
  const port = process.env.PORT ?? "3000";
  setTimeout(async () => {
    const body = JSON.stringify({ paths: ["*"], sent_at: new Date().toISOString() });
    try {
      await fetch(`http://127.0.0.1:${port}/api/revalidate`, {
        method: "POST",
        body,
        headers: { "Content-Type": "application/json", "X-JPS-Signature": sign(secret, body) },
      });
    } catch {
      // The pages still refresh on their own within a minute.
    }
  }, 2000);
}
