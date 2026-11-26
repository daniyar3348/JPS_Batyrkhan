import { describe, expect, it } from "vitest";
import { ApiError, api, setCsrfToken, unwrap } from "./api";
import { json, mockApi } from "./test/render";

describe("api client", () => {
  it("sends the CSRF token only with state-changing requests", async () => {
    const calls = mockApi({
      "GET /api/v1/journal": () => json(200, { name: "J" }),
      "POST /api/v1/auth/logout": () => new Response(null, { status: 204 }),
    });
    setCsrfToken("token-1");

    await unwrap(api.GET("/api/v1/journal"));
    await unwrap(api.POST("/api/v1/auth/logout"));

    expect(calls[0]?.headers.get("X-CSRF-Token")).toBeNull();
    expect(calls[1]?.headers.get("X-CSRF-Token")).toBe("token-1");
    setCsrfToken(null);
  });

  it("turns problem responses into ApiError with field messages", async () => {
    mockApi({
      "PATCH /api/v1/me": () =>
        json(422, {
          code: "validation_failed",
          detail: "Check the highlighted fields.",
          status: 422,
          title: "Some fields are invalid",
          type: "urn:jps:error:validation_failed",
          errors: [{ field: "orcid", message: "Value error, This ORCID iD has an invalid check digit" }],
        }),
    });

    const error = await unwrap(api.PATCH("/api/v1/me", { body: { orcid: "x" } })).catch((e: unknown) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(422);
    expect((error as ApiError).fieldErrors.orcid).toContain("invalid check digit");
  });

  it("reports network failures clearly", async () => {
    mockApi({});
    const error = await unwrap(api.GET("/api/v1/me")).catch((e: unknown) => e);
    expect((error as ApiError).code).toBe("network_error");
  });
});
