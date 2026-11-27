import { describe, expect, it } from "vitest";
import { parseRequest, sign, validSignature } from "./signature";

describe("revalidation requests", () => {
  const body = JSON.stringify({ paths: ["/", "/articles/a"], sent_at: "2026-11-27T10:00:00+00:00" });

  it("accepts the platform's signature and nothing else", () => {
    const header = sign("shared-secret", body);
    expect(header).toMatch(/^sha256=[0-9a-f]{64}$/);
    expect(validSignature("shared-secret", body, header)).toBe(true);
    expect(validSignature("other-secret", body, header)).toBe(false);
    expect(validSignature("shared-secret", `${body} `, header)).toBe(false);
    expect(validSignature("shared-secret", body, null)).toBe(false);
    expect(validSignature("shared-secret", body, "sha256=short")).toBe(false);
  });

  it("accepts only recent, well-formed bodies", () => {
    const now = new Date("2026-11-27T10:02:00Z");
    expect(parseRequest(body, now)?.paths).toEqual(["/", "/articles/a"]);
    expect(parseRequest(body, new Date("2026-11-27T10:06:00Z"))).toBeNull(); // too old: a replay
    expect(
      parseRequest(JSON.stringify({ paths: ["*"], sent_at: "2026-11-27T10:01:00Z" }), now)?.paths,
    ).toEqual(["*"]);
    expect(
      parseRequest(JSON.stringify({ paths: ["articles"], sent_at: "2026-11-27T10:01:00Z" }), now),
    ).toBeNull();
    expect(parseRequest("not json", now)).toBeNull();
  });
});
