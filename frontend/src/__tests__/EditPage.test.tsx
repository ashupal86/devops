import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { loadToken, saveToken } from "../tokens";
import { ada, json, mockFetch, renderAt } from "./helpers";

afterEach(() => vi.unstubAllGlobals());

const header = (init: RequestInit | undefined) =>
  (init?.headers as Record<string, string>)["X-Edit-Token"];

describe("EditPage", () => {
  it("prefills the form and saves with the stored token", async () => {
    saveToken("ada", "good");
    let current = ada;
    const fetch = mockFetch({
      "GET /api/profiles/ada": () => json(200, current),
      "PUT /api/profiles/ada": (init) => {
        current = { ...current, ...JSON.parse(init.body as string) };
        return json(200, current);
      },
    });
    const user = userEvent.setup();
    renderAt("/ada/edit");

    const name = await screen.findByPlaceholderText("Your name");
    expect(name).toHaveValue("Ada Lovelace");
    expect(screen.getByLabelText("Link 1 URL")).toHaveValue("https://github.com/ada");

    await user.clear(name);
    await user.type(name, "Ada L.");
    await user.click(screen.getByRole("button", { name: "Remove link 2" }));
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    // Navigates back to the public page.
    expect(await screen.findByRole("heading", { name: "Ada L." })).toBeInTheDocument();
    const put = fetch.mock.calls.find(([, init]) => init?.method === "PUT")!;
    expect(header(put[1])).toBe("good");
    expect(JSON.parse(put[1]!.body as string)).toEqual({
      display_name: "Ada L.",
      message: ada.message,
      links: [ada.links[0]],
    });
  });

  it("asks for the edit key when none is stored, then uses it", async () => {
    const fetch = mockFetch({
      "GET /api/profiles/ada": () => json(200, ada),
      "PUT /api/profiles/ada": () => json(200, ada),
    });
    const user = userEvent.setup();
    renderAt("/ada/edit");

    await user.type(await screen.findByPlaceholderText(/Paste the key/), "pasted-key");
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await user.click(await screen.findByRole("button", { name: "Save changes" }));

    await screen.findByRole("heading", { name: "Ada Lovelace" });
    const put = fetch.mock.calls.find(([, init]) => init?.method === "PUT")!;
    expect(header(put[1])).toBe("pasted-key");
    expect(loadToken("ada")).toBe("pasted-key");
  });

  it("forgets a rejected key and asks again", async () => {
    saveToken("ada", "stale");
    mockFetch({
      "GET /api/profiles/ada": () => json(200, ada),
      "PUT /api/profiles/ada": () => json(403, { detail: "Invalid edit token" }),
    });
    const user = userEvent.setup();
    renderAt("/ada/edit");

    await user.click(await screen.findByRole("button", { name: "Save changes" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("doesn't match this page");
    expect(screen.getByPlaceholderText(/Paste the key/)).toBeInTheDocument();
    expect(loadToken("ada")).toBeNull();
  });

  it("deletes the page after confirmation", async () => {
    saveToken("ada", "good");
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const fetch = mockFetch({
      "GET /api/profiles/ada": () => json(200, ada),
      "DELETE /api/profiles/ada": () => json(204),
    });
    const user = userEvent.setup();
    renderAt("/ada/edit");

    await user.click(await screen.findByRole("button", { name: "Delete page" }));
    expect(await screen.findByRole("button", { name: "Create my page" })).toBeInTheDocument();
    expect(header(fetch.mock.calls.find(([, i]) => i?.method === "DELETE")![1])).toBe("good");
    expect(loadToken("ada")).toBeNull();
  });

  it("does nothing if delete is cancelled", async () => {
    saveToken("ada", "good");
    vi.spyOn(window, "confirm").mockReturnValue(false);
    const fetch = mockFetch({ "GET /api/profiles/ada": () => json(200, ada) });
    const user = userEvent.setup();
    renderAt("/ada/edit");

    await user.click(await screen.findByRole("button", { name: "Delete page" }));
    expect(fetch.mock.calls.some(([, i]) => i?.method === "DELETE")).toBe(false);
    expect(loadToken("ada")).toBe("good");
  });

  it("shows an error for a missing profile", async () => {
    mockFetch({ "GET /api/profiles/nope": () => json(404, { detail: "Profile not found" }) });
    renderAt("/nope/edit");
    expect(await screen.findByRole("alert")).toHaveTextContent("Profile not found");
  });
});
