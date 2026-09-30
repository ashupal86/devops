import { Route, Routes } from "react-router";
import { CreatePage } from "./pages/CreatePage";
import { EditPage } from "./pages/EditPage";
import { ProfilePage } from "./pages/ProfilePage";

export function App() {
  return (
    <Routes>
      <Route path="/" element={<CreatePage />} />
      <Route path="/:tag" element={<ProfilePage />} />
      <Route path="/:tag/edit" element={<EditPage />} />
    </Routes>
  );
}
