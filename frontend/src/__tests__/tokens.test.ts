import { describe, expect, it, vi } from "vitest";
import { clearToken, loadToken, saveToken } from "../tokens";

describe("token storage", () => {
  it("saves, loads and clears per tag (case-insensitive)", () => {
    saveToken("Ada", "t1");
    saveToken("bob", "t2");
    expect(loadToken("ada")).toBe("t1");
    expect(loadToken("BOB")).toBe("t2");
    clearToken("ADA");
    expect(loadToken("ada")).toBeNull();
    expect(loadToken("bob")).toBe("t2");
  });

  it("survives storage being unavailable", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(() => saveToken("ada", "t")).not.toThrow();
    expect(loadToken("ada")).toBeNull();
  });
});
