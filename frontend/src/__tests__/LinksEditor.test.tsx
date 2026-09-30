import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import { MAX_LINKS, type SocialLink } from "../api";
import { LinksEditor } from "../components/LinksEditor";

function Harness({ initial = [] as SocialLink[] }) {
  const [links, setLinks] = useState(initial);
  return (
    <>
      <LinksEditor links={links} onChange={setLinks} />
      <output data-testid="value">{JSON.stringify(links)}</output>
    </>
  );
}

const value = () => JSON.parse(screen.getByTestId("value").textContent!);

describe("LinksEditor", () => {
  it("shows an empty state", () => {
    render(<Harness />);
    expect(screen.getByText("No links yet.")).toBeInTheDocument();
  });

  it("adds and edits a link", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByRole("button", { name: "+ Add link" }));
    await user.type(screen.getByLabelText("Link 1 label"), "GitHub");
    await user.type(screen.getByLabelText("Link 1 URL"), "https://github.com/me");
    expect(value()).toEqual([{ label: "GitHub", url: "https://github.com/me" }]);
  });

  it("removes the right link", async () => {
    const user = userEvent.setup();
    render(
      <Harness
        initial={[
          { label: "A", url: "https://a.com" },
          { label: "B", url: "https://b.com" },
          { label: "C", url: "https://c.com" },
        ]}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Remove link 2" }));
    expect(value().map((l: SocialLink) => l.label)).toEqual(["A", "C"]);
  });

  it(`disables adding past ${MAX_LINKS} links`, () => {
    const many = Array.from({ length: MAX_LINKS }, (_, i) => ({ label: `L${i}`, url: `https://x.com/${i}` }));
    render(<Harness initial={many} />);
    expect(screen.getByRole("button", { name: "+ Add link" })).toBeDisabled();
    expect(screen.getByText(`Maximum of ${MAX_LINKS} links.`)).toBeInTheDocument();
  });
});
