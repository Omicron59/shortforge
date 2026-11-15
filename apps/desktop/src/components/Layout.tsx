// Cadre de l'application : menu lateral, projet ouvert, etat du moteur local et messages.
import type { ReactNode } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { keys, useProject } from "../api/hooks";
import { useProjectStore } from "../stores/project";
import { useToasts } from "../stores/toasts";
import type { ProjectDetail } from "../api/types";
import { Empty, Button, Loading, ErrorBox } from "./ui";

const NAV = [
  { to: "/", label: "Tableau de bord", icon: "◧" },
  { to: "/idees", label: "Niche et idées", icon: "✦" },
  { to: "/script", label: "Éditeur de script", icon: "✎" },
  { to: "/scenes", label: "Revue des scènes", icon: "▦" },
  { to: "/voix", label: "Voix et sous-titres", icon: "♪" },
  { to: "/apercu", label: "Aperçu vidéo", icon: "▶" },
  { to: "/production", label: "File de production", icon: "≡" },
  { to: "/historique", label: "Historique", icon: "↺" },
  { to: "/statistiques", label: "Statistiques", icon: "▲" },
  { to: "/parametres", label: "Paramètres", icon: "⚙" },
];

export function Layout({ children }: { children: ReactNode }) {
  const health = useQuery({ queryKey: ["health"], queryFn: api.health, refetchInterval: 10_000, retry: false });
  const projects = useQuery({ queryKey: keys.projects, queryFn: api.projects, enabled: health.isSuccess });
  const { currentId, setCurrent } = useProjectStore();
  const toasts = useToasts();

  return (
    <div className="flex h-screen overflow-hidden">
      <aside className="flex w-60 shrink-0 flex-col border-r border-zinc-800 bg-zinc-950">
        <div className="px-5 py-5">
          <p className="text-lg font-bold tracking-tight">ShortForge</p>
          <p className="text-xs text-zinc-500">YouTube Shorts avec IA, en local</p>
        </div>
        <div className="px-3 pb-3">
          <select
            className="w-full rounded-lg border border-zinc-800 bg-zinc-900 px-2 py-2 text-sm"
            value={currentId ?? ""}
            onChange={(e) => setCurrent(e.target.value || null)}
            aria-label="Projet ouvert"
          >
            <option value="">— Aucun projet ouvert —</option>
            {projects.data?.map((p) => <option key={p.id} value={p.id}>{p.title}</option>)}
          </select>
        </div>
        <nav className="flex-1 space-y-0.5 overflow-y-auto px-3">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/"}
              className={({ isActive }) =>
                `flex items-center gap-3 rounded-lg px-3 py-2 text-sm ${isActive ? "bg-violet-600/20 text-violet-200" : "text-zinc-400 hover:bg-zinc-900 hover:text-zinc-100"}`}
            >
              <span className="w-4 text-center">{item.icon}</span>
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="border-t border-zinc-800 px-5 py-3 text-xs">
          {health.isSuccess ? (
            <span className="text-emerald-400">● Moteur local connecté (v{health.data.version})</span>
          ) : health.isLoading ? (
            <span className="text-zinc-500">Connexion au moteur local…</span>
          ) : (
            <span className="text-red-400">● Moteur local injoignable</span>
          )}
          <p className="mt-1 text-zinc-500">
            Publication YouTube : {health.data?.youtube_publish_enabled ? "activée" : "désactivée"}
          </p>
        </div>
      </aside>

      <main className="flex-1 overflow-y-auto">
        {health.isError ? <Offline /> : <div className="mx-auto max-w-6xl p-8">{children}</div>}
      </main>

      <div className="fixed bottom-4 right-4 z-50 flex w-96 flex-col gap-2">
        {toasts.toasts.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => toasts.dismiss(t.id)}
            className={`rounded-lg px-4 py-3 text-left text-sm shadow-lg ${t.kind === "error" ? "bg-red-900 text-red-100" : "bg-zinc-800 text-zinc-100"}`}
          >
            {t.message}
          </button>
        ))}
      </div>
    </div>
  );
}

function Offline() {
  return (
    <div className="flex h-full items-center justify-center p-8">
      <div className="max-w-md text-center">
        <p className="text-xl font-semibold">Moteur local injoignable</p>
        <p className="mt-2 text-sm text-zinc-400">
          L'interface n'arrive pas à joindre le backend sur http://127.0.0.1:8787. Lance-le dans un terminal :
        </p>
        <pre className="mt-3 rounded-lg bg-zinc-900 p-3 text-left text-sm">cd backend{"\n"}.venv\Scripts\python -m shortforge</pre>
        <p className="mt-3 text-xs text-zinc-500">Nouvel essai automatique toutes les 10 secondes.</p>
      </div>
    </div>
  );
}

/** Affiche `children` seulement si un projet est ouvert ; sinon propose d'en creer un. */
export function WithProject({ children }: { children: (project: ProjectDetail) => ReactNode }) {
  const currentId = useProjectStore((s) => s.currentId);
  const setCurrent = useProjectStore((s) => s.setCurrent);
  const project = useProject(currentId);
  const navigate = useNavigate();

  if (!currentId) {
    return (
      <Empty action={<Button variant="primary" onClick={() => navigate("/idees")}>Créer un projet</Button>}>
        Aucun projet ouvert. Choisis-en un dans le menu à gauche ou crée-en un nouveau.
      </Empty>
    );
  }
  if (project.isLoading) return <Loading />;
  if (project.isError) {
    return (
      <div className="space-y-3">
        <ErrorBox error={project.error} />
        <Button onClick={() => setCurrent(null)}>Fermer ce projet</Button>
      </div>
    );
  }
  return <>{project.data && children(project.data)}</>;
}
