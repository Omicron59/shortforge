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
          <Route path="/historique" element={<History />} />
          <Route path="/statistiques" element={<Stats />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Layout>
    </HashRouter>
  );
}
