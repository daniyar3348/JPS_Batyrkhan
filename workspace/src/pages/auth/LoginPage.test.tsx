import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { json, mockApi, renderPage } from "../../test/render";
import { LoginPage, safeNext } from "./LoginPage";

const ME = {
  user: { id: 1, email: "asel@example.org", full_name: "Asel Author" },
  roles: ["author"],
  capabilities: [],
  csrf_token: "csrf-123",
};

describe("safeNext", () => {
  it("only allows paths inside the app", () => {
    expect(safeNext("/admin/users?q=1")).toBe("/admin/users?q=1");
    expect(safeNext("https://evil.example")).toBe("/");
    expect(safeNext("//evil.example")).toBe("/");
    expect(safeNext(null)).toBe("/");
  });
});

describe("LoginPage", () => {
  it("validates the form before sending anything", async () => {
    const calls = mockApi({ "GET /api/v1/me": () => json(401, { code: "unauthorized", detail: "No" }) });
    renderPage(<LoginPage />, { path: "/login" });

    await userEvent.click(await screen.findByRole("button", { name: "Sign in" }));

    expect(await screen.findByText("Enter a valid e-mail address")).toBeInTheDocument();
    expect(screen.getByText("Enter your password")).toBeInTheDocument();
    expect(calls.filter((call) => call.path === "/api/v1/auth/login")).toHaveLength(0);
  });

  it("shows the server's message when the credentials are wrong", async () => {
    mockApi({
      "GET /api/v1/me": () => json(401, { code: "unauthorized", detail: "No" }),
      "POST /api/v1/auth/login": () =>
        json(401, { code: "invalid_credentials", detail: "The e-mail address or password is incorrect." }),
    });
    renderPage(<LoginPage />, { path: "/login" });

    await userEvent.type(await screen.findByLabelText(/E-mail address/), "asel@example.org");
    await userEvent.type(screen.getByLabelText(/Password/), "wrong-password");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByText("The e-mail address or password is incorrect.")).toBeInTheDocument();
  });

  it("signs in and continues to the requested page", async () => {
    const calls = mockApi({
      "GET /api/v1/me": () => json(401, { code: "unauthorized", detail: "No" }),
      "POST /api/v1/auth/login": () => json(200, ME),
    });
    const { router } = renderPage(<LoginPage />, { path: "/login", url: "/login?next=%2Fadmin%2Fusers" });

    await userEvent.type(await screen.findByLabelText(/E-mail address/), "asel@example.org");
    await userEvent.type(screen.getByLabelText(/Password/), "correct-password");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    await waitFor(() => expect(router.state.location.pathname).toBe("/admin/users"));
    const login = calls.find((call) => call.path === "/api/v1/auth/login");
    expect(login?.body).toEqual({ email: "asel@example.org", password: "correct-password" });
  });
});
