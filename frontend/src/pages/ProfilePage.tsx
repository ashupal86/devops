import { useEffect, useState } from "react";
import { Link, useLocation, useParams } from "react-router";
import { ApiError, api, isSafeUrl, type Profile } from "../api";
import { ShareBox } from "../components/ShareBox";
import { loadToken } from "../tokens";

type State =
  | { kind: "loading" }
  | { kind: "missing" }
  | { kind: "error"; message: string }
  | { kind: "ok"; profile: Profile };

export function ProfilePage() {
  const { tag = "" } = useParams();
  const location = useLocation();
  const newToken = (location.state as { editToken?: string } | null)?.editToken;
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    setState({ kind: "loading" });
    api
      .getProfile(tag)
      .then((profile) => !cancelled && setState({ kind: "ok", profile }))
      .catch((err) => {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 404) setState({ kind: "missing" });
        else setState({ kind: "error", message: err.message });
      });
    return () => {
      cancelled = true;
    };
  }, [tag]);

  if (state.kind === "loading") return <main className="container muted">Loading…</main>;

  if (state.kind === "missing")
    return (
      <main className="container card center">
        <h2>No one has @{tag.toLowerCase()} yet</h2>
        <Link to={`/?tag=${encodeURIComponent(tag.toLowerCase())}`}>Claim this tag</Link>
      </main>
    );

  if (state.kind === "error")
    return (
      <main className="container card center">
        <p role="alert" className="error">
          Couldn't load profile: {state.message}
        </p>
      </main>
    );

  const { profile } = state;
  const canEdit = !!loadToken(profile.tag);

  return (
    <main className="container">
      {newToken && (
        <div className="card notice" role="note">
          <strong>Your page is live!</strong> Keep this edit key somewhere safe. It's the only
          way to edit your page from another device:
          <code className="token">{newToken}</code>
        </div>
      )}

      <article className="card profile">
        <div className="avatar" aria-hidden>
          {profile.display_name.charAt(0).toUpperCase()}
        </div>
        <h1>{profile.display_name}</h1>
        <p className="muted">@{profile.tag}</p>
        {profile.message && <p className="message">{profile.message}</p>}

        <ul className="links">
          {profile.links.filter((l) => isSafeUrl(l.url)).map((link, i) => (
            <li key={i}>
              <a href={link.url} target="_blank" rel="noopener noreferrer nofollow">
                {link.label}
              </a>
            </li>
          ))}
        </ul>

        <ShareBox tag={profile.tag} />
        {canEdit && (
          <Link className="edit-link" to={`/${profile.tag}/edit`}>
            Edit page
          </Link>
        )}
      </article>

      <p className="center muted">
        <Link to="/">Make your own page</Link>
      </p>
    </main>
  );
}
