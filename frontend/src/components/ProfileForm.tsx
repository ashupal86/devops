import { useEffect, useState, type FormEvent } from "react";
import { api, isSafeUrl, type ProfileInput, type TagAvailability } from "../api";
import { LinksEditor } from "./LinksEditor";

export interface ProfileFormValues extends ProfileInput {
  tag: string;
}

interface Props {
  initial?: Partial<ProfileFormValues>;
  /** Show the tag field (create mode). In edit mode the tag is fixed. */
  withTag?: boolean;
  submitLabel: string;
  onSubmit: (values: ProfileFormValues) => Promise<void>;
}

export function validate(values: ProfileFormValues, withTag: boolean): string | null {
  if (withTag && !values.tag.trim()) return "Pick a tag.";
  if (!values.display_name.trim()) return "Name is required.";
  for (const [i, link] of values.links.entries()) {
    if (!link.label.trim()) return `Link ${i + 1} needs a label.`;
    if (!isSafeUrl(link.url.trim())) return `Link ${i + 1} must be a full http(s):// URL.`;
  }
  return null;
}

function useTagAvailability(tag: string, enabled: boolean) {
  const [result, setResult] = useState<TagAvailability | null>(null);
  useEffect(() => {
    setResult(null);
    if (!enabled || !tag.trim()) return;
    let cancelled = false;
    const t = setTimeout(() => {
      api
        .checkTag(tag.trim())
        .then((r) => !cancelled && setResult(r))
        .catch(() => {});
    }, 350);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [tag, enabled]);
  return result;
}

export function ProfileForm({ initial, withTag = false, submitLabel, onSubmit }: Props) {
  const [values, setValues] = useState<ProfileFormValues>({
    tag: initial?.tag ?? "",
    display_name: initial?.display_name ?? "",
    message: initial?.message ?? "",
    links: initial?.links ?? [],
  });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const availability = useTagAvailability(values.tag, withTag);

  const set = <K extends keyof ProfileFormValues>(k: K, v: ProfileFormValues[K]) =>
    setValues((prev) => ({ ...prev, [k]: v }));

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const problem = validate(values, withTag);
    if (problem) return setError(problem);
    setError(null);
    setBusy(true);
    try {
      await onSubmit({
        ...values,
        tag: values.tag.trim().toLowerCase(),
        links: values.links.map((l) => ({ label: l.label.trim(), url: l.url.trim() })),
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="card form" onSubmit={handleSubmit} noValidate>
      {withTag && (
        <label>
          Your tag
          <div className="tag-input">
            <span>@</span>
            <input
              value={values.tag}
              onChange={(e) => set("tag", e.target.value)}
              placeholder="yourname"
              maxLength={30}
              autoCapitalize="none"
              autoComplete="off"
            />
          </div>
          {availability && (
            <small
              role="status"
              className={availability.available ? "ok" : "bad"}
            >
              {availability.available
                ? `@${availability.tag} is available`
                : `@${availability.tag} is not available: ${availability.reason}`}
            </small>
          )}
        </label>
      )}

      <label>
        Name
        <input
          value={values.display_name}
          onChange={(e) => set("display_name", e.target.value)}
          maxLength={80}
          placeholder="Your name"
        />
      </label>

      <label>
        Message
        <textarea
          value={values.message}
          onChange={(e) => set("message", e.target.value)}
          maxLength={500}
          rows={3}
          placeholder="Say something to people who visit your page"
        />
        <small className="muted">{values.message.length}/500</small>
      </label>

      <LinksEditor links={values.links} onChange={(links) => set("links", links)} />

      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}

      <button type="submit" disabled={busy}>
        {busy ? "Saving…" : submitLabel}
      </button>
    </form>
  );
}
