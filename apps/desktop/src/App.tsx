// Routes de l'interface. HashRouter : fonctionne tel quel dans la fenetre Tauri.
import { HashRouter, Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import Dashboard from "./pages/Dashboard";
import Ideas from "./pages/Ideas";
import ScriptEditor from "./pages/ScriptEditor";
import Scenes from "./pages/Scenes";
import VoiceSubtitles from "./pages/VoiceSubtitles";
import Preview from "./pages/Preview";
import Queue from "./pages/Queue";
import Settings from "./pages/Settings";
import History from "./pages/History";
import Stats from "./pages/Stats";
import Planning from "./pages/Planning";
import Inbox from "./pages/Inbox";
import Formats from "./pages/Formats";
import LongVideo from "./pages/LongVideo";
import MyStyle from "./pages/MyStyle";
import Onboarding from "./pages/Onboarding";
import SettingsAI from "./pages/SettingsAI";
import BriefPage from "./pages/create/Brief";
import IdeasPage from "./pages/create/Ideas";
import Resume from "./pages/create/Resume";
import ScriptPage from "./pages/create/Script";
import StudioPage from "./pages/create/Studio";

export default function App() {
  return (
    <HashRouter>
      <Layout>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/idees" element={<Ideas />} />
          <Route path="/script" element={<ScriptEditor />} />
          <Route path="/scenes" element={<Scenes />} />
          <Route path="/voix" element={<VoiceSubtitles />} />
          <Route path="/apercu" element={<Preview />} />
          <Route path="/production" element={<Queue />} />
          <Route path="/parametres" element={<Settings />} />
          <Route path="/parametres/ia" element={<SettingsAI />} />
          {/* Nouveau parcours de creation ; l'ancien (idees, script, scenes, voix, apercu) reste disponible. */}
          <Route path="/creer" element={<BriefPage />} />
          <Route path="/creer/:id" element={<Resume />} />
          <Route path="/creer/:id/brief" element={<BriefPage />} />
          <Route path="/creer/:id/idees" element={<IdeasPage />} />
          <Route path="/creer/:id/script" element={<ScriptPage />} />
          <Route path="/creer/:id/studio" element={<StudioPage />} />
          <Route path="/historique" element={<History />} />
          <Route path="/statistiques" element={<Stats />} />
          <Route path="/planning" element={<Planning />} />
          <Route path="/a-valider" element={<Inbox />} />
          <Route path="/formats" element={<Formats />} />
          <Route path="/video-longue" element={<LongVideo />} />
          <Route path="/style" element={<MyStyle />} />
          <Route path="/bienvenue" element={<Onboarding />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Layout>
    </HashRouter>
  );
}
