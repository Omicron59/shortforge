// Assistant de premier lancement : verifie chaque outil et explique quoi faire, pas a pas.
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { useAction } from "../api/hooks";
import { Alert, Button, Card, PageHeader } from "../components/ui";
import { openPath } from "../lib/open";

export default function Onboarding() {
  const state = useQuery({ queryKey: ["onboarding"], queryFn: api.onboarding, refetchInterval: 5000 });
  const navigate = useNavigate();
  const done = useAction(() => api.onboardingDone());
  const s = state.data;
  if (!s) return null;
  const mac = s.platform === "darwin";

  return (
    <>
      <PageHeader title="Bienvenue dans ShortForge" subtitle="Vérifions ensemble ce qui est prêt. Tu pourras revenir ici à tout moment." />
      <div className="space-y-4">
        <Card title="Ce qu'il faut sur ton ordinateur">
          <ul className="space-y-3">
            {s.steps.map((step) => (
              <li key={step.id} className="flex gap-3 text-sm">
                <span className={step.ok ? "text-emerald-400" : "text-amber-400"}>{step.ok ? "✓" : "○"}</span>
                <div>
                  <p className="font-medium">{step.label}</p>
                  {!step.ok && <p className="text-zinc-400">{step.help}</p>}
                </div>
              </li>
            ))}
          </ul>
          <p className="mt-4 text-xs text-zinc-500">Nouvelle vérification toutes les 5 secondes. Espace libre : {s.free_space_gb} Go.</p>
        </Card>
        <Card title="Tes réglages et tes clés">
          <p className="text-sm text-zinc-300">
            Les clés API (Gemini, ElevenLabs, YouTube, Postiz…) et les options se règlent dans un fichier texte sur ton ordinateur, jamais dans l'application.
          </p>
          <p className="mt-2 break-all rounded bg-zinc-950 p-2 text-xs">{s.env_file}</p>
          <div className="mt-3 flex flex-wrap gap-2">
            <Button onClick={() => void openPath(s.env_file)}>Ouvrir le fichier de réglages</Button>
            <Button variant="ghost" onClick={() => void openPath(s.data_dir)}>Ouvrir le dossier des projets</Button>
          </div>
          <p className="mt-3 text-xs text-zinc-500">Après une modification, quitte et relance ShortForge.</p>
        </Card>
        <Alert tone="blue">
          {mac
            ? "Sur Mac : installe FFmpeg avec Homebrew (brew install ffmpeg), Ollama depuis ollama.com et ComfyUI Desktop depuis comfy.org (puces Apple)."
            : "Sur Windows : installe FFmpeg (winget install Gyan.FFmpeg), Ollama depuis ollama.com et ComfyUI Desktop depuis comfy.org (carte NVIDIA conseillée)."}
          {" "}La publication est désactivée par défaut : tu peux tout tester sans risque.
        </Alert>
        <Button variant="primary" busy={done.isPending} onClick={() => done.mutate(undefined, { onSuccess: () => navigate("/") })}>C'est parti</Button>
      </div>
    </>
  );
}
