import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { ApiError, api, type Profile } from "../api";
import { ProfileForm, type ProfileFormValues } from "../components/ProfileForm";
import { clearToken, loadToken, saveToken } from "../tokens";

export function EditPage() {
  const { tag = "" } = useParams();
  const navigate = useNavigate();
  const [profile, setProfile] = useState<Profile | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [token, setToken] = useState<string | null>(() => loadToken(tag));
  const [keyInput, setKeyInput] = useState("");
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [keyError, setKeyError] = useState<string | null>(null);

  useEffect(() => {
    api
      .getProfile(tag)
      .then(setProfile)
      .catch((err) => setLoadError(err.message));
  }, [tag]);

  function forgetBadToken(err: unknown) {
    if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
      clearToken(tag);
      setToken(null);
      setKeyError("That edit key doesn't match this page.");
    }
  }

  async function save(values: ProfileFormValues) {
    try {
      const updated = await api.updateProfile(
        tag,
        { display_name: values.display_name, message: values.message, links: values.links },
        token!,
      );
      saveToken(tag, token!);
      navigate(`/${updated.tag}`);
    } catch (err) {
      forgetBadToken(err);
      throw err;
    }
  }

  async function remove() {
    if (!window.confirm(`Delete @${tag}? This cannot be undone.`)) return;
    try {
      await api.deleteProfile(tag, token!);
      clearToken(tag);
      navigate("/");
    } catch (err) {
      forgetBadToken(err);
      setDeleteError(err instanceof Error ? err.message : "Delete failed.");
    }
  }

  function submitKey(e: FormEvent) {
    e.preventDefault();
    if (!keyInput.trim()) return;
    setKeyError(null);
    setDeleteError(null);
    setToken(keyInput.trim());
  }

  if (loadError)
    return (
      <main className="container card center">
        <p role="alert" className="error">
          {loadError}
        </p>
        <Link to="/">Home</Link>
      </main>
    );
  if (!profile) return <main className="container muted">Loading…</main>;

  if (!token)
    return (
      <main className="container">
        <form className="card form" onSubmit={submitKey}>
          <h2>Edit @{profile.tag}</h2>
          {keyError && (
            <p role="alert" className="error">
              {keyError}
            </p>
          )}
          <label>
            Edit key
            <input
              value={keyInput}
              onChange={(e) => setKeyInput(e.target.value)}
              placeholder="Paste the key you got when creating the page"
            />
          </label>
          <button type="submit">Continue</button>
        </form>
      </main>
    );

  return (
    <main className="container">
      <h2>
        Edit <Link to={`/${profile.tag}`}>@{profile.tag}</Link>
      </h2>
      <ProfileForm initial={profile} submitLabel="Save changes" onSubmit={save} />
      <div className="danger-zone">
        {deleteError && (
          <p role="alert" className="error">
            {deleteError}
          </p>
        )}
        <button type="button" className="danger" onClick={remove}>
          Delete page
        </button>
      </div>
    </main>
  );
}
