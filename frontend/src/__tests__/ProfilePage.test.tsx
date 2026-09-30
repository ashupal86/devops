import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { saveToken } from "../tokens";
import { ada, json, mockFetch, renderAt } from "./helpers";

afterEach(() => vi.unstubAllGlobals());

describe("ProfilePage", () => {
  it("renders the profile, message and links", async () => {
    mockFetch({ "GET /api/profiles/ada": () => json(200, ada) });
    renderAt("/ada");

    expect(await screen.findByRole("heading", { name: "Ada Lovelace" })).toBeInTheDocument();
    expect(screen.getByText("@ada")).toBeInTheDocument();
    expect(screen.getByText("First programmer. Say hi!")).toBeInTheDocument();

    const gh = screen.getByRole("link", { name: "GitHub" });
    expect(gh).toHaveAttribute("href", "https://github.com/ada");
    expect(gh).toHaveAttribute("target", "_blank");
    expect(gh.getAttribute("rel")).toContain("noopener");
    expect(screen.getByRole("link", { name: "X" })).toBeInTheDocument();
  });

  it("never renders unsafe link URLs even if the API returns them", async () => {
    mockFetch({
      "GET /api/profiles/ada": () =>
        json(200, { ...ada, links: [{ label: "Evil", url: "javascript:alert(1)" }] }),
    });
    renderAt("/ada");
    await screen.findByRole("heading", { name: "Ada Lovelace" });
    expect(screen.queryByRole("link", { name: "Evil" })).not.toBeInTheDocument();
  });

  it("shows a claim link for unknown tags", async () => {
    mockFetch({ "GET /api/profiles/Ghost": () => json(404, { detail: "Profile not found" }) });
    renderAt("/Ghost");
    expect(await screen.findByText("No one has @ghost yet")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Claim this tag" })).toHaveAttribute("href", "/?tag=ghost");
  });

  it("shows an error when the API fails", async () => {
    mockFetch({ "GET /api/profiles/ada": () => json(500, { detail: "boom" }) });
    renderAt("/ada");
    expect(await screen.findByRole("alert")).toHaveTextContent("boom");
  });

  it("hides the edit link for visitors", async () => {
    mockFetch({ "GET /api/profiles/ada": () => json(200, ada) });
    renderAt("/ada");
    await screen.findByRole("heading", { name: "Ada Lovelace" });
    expect(screen.queryByRole("link", { name: "Edit page" })).not.toBeInTheDocument();
    expect(screen.queryByRole("note")).not.toBeInTheDocument();
  });

  it("shows the edit link for the owner", async () => {
    saveToken("ada", "tok");
    mockFetch({ "GET /api/profiles/ada": () => json(200, ada) });
    renderAt("/ada");
    expect(await screen.findByRole("link", { name: "Edit page" })).toHaveAttribute("href", "/ada/edit");
  });

  it("copies the share link", async () => {
    mockFetch({ "GET /api/profiles/ada": () => json(200, ada) });
    const user = userEvent.setup();
    renderAt("/ada");
    await screen.findByRole("heading", { name: "Ada Lovelace" });

    const url = `${window.location.origin}/ada`;
    expect(screen.getByLabelText("Share link")).toHaveTextContent(url);
    await user.click(screen.getByRole("button", { name: "Copy link" }));
    expect(await navigator.clipboard.readText()).toBe(url);
    expect(screen.getByRole("button", { name: "Copied!" })).toBeInTheDocument();
  });
});
