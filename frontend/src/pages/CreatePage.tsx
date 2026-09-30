import { useNavigate, useSearchParams } from "react-router";
import { api } from "../api";
import { ProfileForm, type ProfileFormValues } from "../components/ProfileForm";
import { saveToken } from "../tokens";

export function CreatePage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();

  async function create(values: ProfileFormValues) {
    const { profile, edit_token } = await api.createProfile(values);
    saveToken(profile.tag, edit_token);
    navigate(`/${profile.tag}`, { state: { editToken: edit_token } });
  }

  return (
    <main className="container">
      <header className="hero">
        <h1>social-links</h1>
        <p>One page for your message and all your socials. Share it with a single tag.</p>
      </header>
      <ProfileForm
        withTag
        initial={{ tag: params.get("tag") ?? "" }}
        submitLabel="Create my page"
        onSubmit={create}
      />
    </main>
  );
}
