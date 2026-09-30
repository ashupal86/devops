import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { loadToken } from "../tokens";
import { ada, json, mockFetch, renderAt } from "./helpers";

afterEach(() => vi.unstubAllGlobals());

describe("CreatePage", () => {
  it("shows tag availability as you type", async () => {
    mockFetch({
      "GET /api/profiles/ada/available": () => json(200, { tag: "ada", available: true, reason: null }),
    });
    const user = userEvent.setup();
    renderAt("/");
    await user.type(screen.getByPlaceholderText("yourname"), "ada");
    expect(await screen.findByRole("status")).toHaveTextContent("@ada is available");
  });

  it("shows when a tag is taken", async () => {
    mockFetch({
      "GET /api/profiles/bob/available": () =>
        json(200, { tag: "bob", available: false, reason: "already taken" }),
    });
    const user = userEvent.setup();
    renderAt("/");
    await user.type(screen.getByPlaceholderText("yourname"), "bob");
    expect(await screen.findByRole("status")).toHaveTextContent("not available: already taken");
  });

  it("prefills the tag from ?tag=", () => {
    mockFetch({
      "GET /api/profiles/zed/available": () => json(200, { tag: "zed", available: true, reason: null }),
    });
    renderAt("/?tag=zed");
    expect(screen.getByPlaceholderText("yourname")).toHaveValue("zed");
  });

  it("creates a profile, stores the token and shows it on the new page", async () => {
    const fetch = mockFetch({
      "GET /api/profiles/ada/available": () => json(200, { tag: "ada", available: true, reason: null }),
      "POST /api/profiles": () => json(201, { profile: ada, edit_token: "secret-token" }),
      "GET /api/profiles/ada": () => json(200, ada),
    });
    const user = userEvent.setup();
    renderAt("/");

    await user.type(screen.getByPlaceholderText("yourname"), "Ada");
    await user.type(screen.getByPlaceholderText("Your name"), "Ada Lovelace");
    await user.type(screen.getByPlaceholderText(/Say something/), "Hi!");
    await user.click(screen.getByRole("button", { name: "+ Add link" }));
    await user.type(screen.getByLabelText("Link 1 label"), "GitHub");
    await user.type(screen.getByLabelText("Link 1 URL"), " https://github.com/ada ");
    await user.click(screen.getByRole("button", { name: "Create my page" }));

    expect(await screen.findByRole("heading", { name: "Ada Lovelace" })).toBeInTheDocument();
    expect(screen.getByRole("note")).toHaveTextContent("secret-token");
    expect(loadToken("ada")).toBe("secret-token");

    const post = fetch.mock.calls.find(([, init]) => init?.method === "POST")!;
    expect(JSON.parse(post[1]!.body as string)).toEqual({
      tag: "ada",
      display_name: "Ada Lovelace",
      message: "Hi!",
      links: [{ label: "GitHub", url: "https://github.com/ada" }],
    });
  });

  it("blocks submit with client-side validation errors", async () => {
    const fetch = mockFetch({
      "GET /api/profiles/ada/available": () => json(200, { tag: "ada", available: true, reason: null }),
    });
    const user = userEvent.setup();
    renderAt("/");
    await user.type(screen.getByPlaceholderText("yourname"), "ada");
    await user.click(screen.getByRole("button", { name: "Create my page" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Name is required.");

    await user.type(screen.getByPlaceholderText("Your name"), "Ada");
    await user.click(screen.getByRole("button", { name: "+ Add link" }));
    await user.type(screen.getByLabelText("Link 1 label"), "Evil");
    await user.type(screen.getByLabelText("Link 1 URL"), "javascript:alert(1)");
    await user.click(screen.getByRole("button", { name: "Create my page" }));
    expect(screen.getByRole("alert")).toHaveTextContent("must be a full http(s):// URL");

    expect(fetch.mock.calls.some(([, init]) => init?.method === "POST")).toBe(false);
  });

  it("shows server errors such as a taken tag", async () => {
    mockFetch({
      "GET /api/profiles/ada/available": () => json(200, { tag: "ada", available: true, reason: null }),
      "POST /api/profiles": () => json(409, { detail: "Tag already taken" }),
    });
    const user = userEvent.setup();
    renderAt("/");
    await user.type(screen.getByPlaceholderText("yourname"), "ada");
    await user.type(screen.getByPlaceholderText("Your name"), "Ada");
    await user.click(screen.getByRole("button", { name: "Create my page" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Tag already taken");
    expect(loadToken("ada")).toBeNull();
  });
});
