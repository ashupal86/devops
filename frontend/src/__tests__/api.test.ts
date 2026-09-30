import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api, errorMessage, isSafeUrl } from "../api";
import { ada, json, mockFetch } from "./helpers";

afterEach(() => vi.unstubAllGlobals());

describe("errorMessage", () => {
  it("returns string details as-is", () => {
    expect(errorMessage({ detail: "Tag already taken" }, "x")).toBe("Tag already taken");
  });

  it("formats pydantic validation errors with field path", () => {
    const body = {
      detail: [{ loc: ["body", "links", 0, "url"], msg: "Value error, url must be an absolute http(s) URL" }],
    };
    expect(errorMessage(body, "x")).toBe("links.0.url: url must be an absolute http(s) URL");
  });

  it("falls back when body is unusable", () => {
    expect(errorMessage(null, "fallback")).toBe("fallback");
    expect(errorMessage({ detail: [] }, "fallback")).toBe("fallback");
  });
});

describe("isSafeUrl", () => {
  it.each(["https://github.com/a", "http://example.com"])("accepts %s", (u) => {
    expect(isSafeUrl(u)).toBe(true);
  });
  it.each(["javascript:alert(1)", "ftp://x.com", "example.com", "", "data:text/html,hi"])(
    "rejects %s",
    (u) => expect(isSafeUrl(u)).toBe(false),
  );
});

describe("api client", () => {
  it("GETs a profile and URL-encodes the tag", async () => {
    const fetch = mockFetch({ "GET /api/profiles/a%2Fb": () => json(200, ada) });
    await expect(api.getProfile("a/b")).resolves.toEqual(ada);
    expect(fetch).toHaveBeenCalledOnce();
  });

  it("POSTs JSON when creating", async () => {
    const fetch = mockFetch({
      "POST /api/profiles": () => json(201, { profile: ada, edit_token: "tok" }),
    });
    const input = { tag: "ada", display_name: "Ada", message: "", links: [] };
    await api.createProfile(input);
    const init = fetch.mock.calls[0][1]!;
    expect(JSON.parse(init.body as string)).toEqual(input);
    expect((init.headers as Record<string, string>)["Content-Type"]).toBe("application/json");
  });

  it("sends the edit token header on update and delete", async () => {
    const fetch = mockFetch({
      "PUT /api/profiles/ada": () => json(200, ada),
      "DELETE /api/profiles/ada": () => json(204),
    });
    await api.updateProfile("ada", { display_name: "A", message: "", links: [] }, "secret");
    await expect(api.deleteProfile("ada", "secret")).resolves.toBeUndefined();
    for (const [, init] of fetch.mock.calls) {
      expect((init!.headers as Record<string, string>)["X-Edit-Token"]).toBe("secret");
    }
  });

  it("does not send a token header on public reads", async () => {
    const fetch = mockFetch({ "GET /api/profiles/ada": () => json(200, ada) });
    await api.getProfile("ada");
    expect(fetch.mock.calls[0][1]!.headers).not.toHaveProperty("X-Edit-Token");
  });

  it("throws ApiError with status and server message", async () => {
    mockFetch({ "GET /api/profiles/nope": () => json(404, { detail: "Profile not found" }) });
    const err = await api.getProfile("nope").catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(404);
    expect(err.message).toBe("Profile not found");
  });

  it("handles non-JSON error bodies", async () => {
    mockFetch({ "GET /api/profiles/x": () => new Response("<html>502</html>", { status: 502 }) });
    await expect(api.getProfile("x")).rejects.toThrow("Request failed (502)");
  });
});
