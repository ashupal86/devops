import { describe, expect, it } from "vitest";
import { validate } from "../components/ProfileForm";

const base = { tag: "ada", display_name: "Ada", message: "", links: [] };

describe("validate", () => {
  it("accepts a valid profile", () => {
    expect(validate(base, true)).toBeNull();
  });

  it("requires a tag only in create mode", () => {
    expect(validate({ ...base, tag: " " }, true)).toBe("Pick a tag.");
    expect(validate({ ...base, tag: "" }, false)).toBeNull();
  });

  it("requires a name", () => {
    expect(validate({ ...base, display_name: "  " }, true)).toBe("Name is required.");
  });

  it("requires link labels and http(s) URLs", () => {
    expect(validate({ ...base, links: [{ label: "", url: "https://a.com" }] }, true)).toBe(
      "Link 1 needs a label.",
    );
    expect(validate({ ...base, links: [{ label: "x", url: "javascript:alert(1)" }] }, true)).toBe(
      "Link 1 must be a full http(s):// URL.",
    );
  });
});
