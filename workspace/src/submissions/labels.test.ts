import { describe, expect, it } from "vitest";
import { formatSize, statusLook, wordCount } from "./labels";

describe("submission labels", () => {
  it("formats file sizes", () => {
    expect(formatSize(512)).toBe("512 B");
    expect(formatSize(20 * 1024)).toBe("20 KB");
    expect(formatSize(5.25 * 1024 * 1024)).toBe("5.3 MB");
  });

  it("counts words the way the server does", () => {
    expect(wordCount("")).toBe(0);
    expect(wordCount("   \n ")).toBe(0);
    expect(wordCount(" Soil  carbon\nin the steppe ")).toBe(5);
  });

  it("names the status an author sees", () => {
    expect(statusLook({ status: "draft", stage: "submission" }).label).toBe("Draft");
    expect(statusLook({ status: "queued", stage: "submission" }).label).toBe("Submitted");
    expect(statusLook({ status: "queued", stage: "review" }).label).toBe("In review");
    expect(statusLook({ status: "declined", stage: "review" }).color).toBe("red");
  });
});
