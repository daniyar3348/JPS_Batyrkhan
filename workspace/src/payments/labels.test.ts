import { describe, expect, it } from "vitest";
import { money } from "./labels";

describe("money", () => {
  it("groups thousands like the invoice does", () => {
    expect(money("112000.00", "KZT")).toBe("112 000.00 KZT");
    expect(money("0.5", "USD")).toBe("0.50 USD");
    expect(money(1234567.891, "EUR")).toBe("1 234 567.89 EUR");
  });
});
