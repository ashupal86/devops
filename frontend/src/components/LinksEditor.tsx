import { MAX_LINKS, type SocialLink } from "../api";

interface Props {
  links: SocialLink[];
  onChange: (links: SocialLink[]) => void;
}

export function LinksEditor({ links, onChange }: Props) {
  const update = (i: number, patch: Partial<SocialLink>) =>
    onChange(links.map((l, idx) => (idx === i ? { ...l, ...patch } : l)));

  return (
    <fieldset className="links-editor">
      <legend>Social links</legend>
      {links.length === 0 && <p className="muted">No links yet.</p>}
      {links.map((link, i) => (
        <div className="link-row" key={i}>
          <input
            aria-label={`Link ${i + 1} label`}
            placeholder="Label (e.g. GitHub)"
            value={link.label}
            maxLength={40}
            onChange={(e) => update(i, { label: e.target.value })}
          />
          <input
            aria-label={`Link ${i + 1} URL`}
            placeholder="https://…"
            type="url"
            value={link.url}
            onChange={(e) => update(i, { url: e.target.value })}
          />
          <button
            type="button"
            className="ghost"
            aria-label={`Remove link ${i + 1}`}
            onClick={() => onChange(links.filter((_, idx) => idx !== i))}
          >
            ✕
          </button>
        </div>
      ))}
      <button
        type="button"
        className="secondary"
        disabled={links.length >= MAX_LINKS}
        onClick={() => onChange([...links, { label: "", url: "" }])}
      >
        + Add link
      </button>
      {links.length >= MAX_LINKS && <p className="muted">Maximum of {MAX_LINKS} links.</p>}
    </fieldset>
  );
}
