// Tableau de bord : services locaux, budget, projets et etat du projet ouvert.
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { keys, useProject } from "../api/hooks";
import { NextAction, PipelineTimeline } from "../components/Pipeline";
import { Badge, Button, Card, Empty, Meter, PageHeader, Stat } from "../components/ui";
import { PROJECT_STATUS_LABELS, dateTime, usd } from "../lib/format";
import { useProjectStore } from "../stores/project";

export default function Dashboard() {
  const status = useQuery({ queryKey: ["status"], queryFn: api.status, refetchInterval: 15_000 });
  const budget = useQuery({ queryKey: ["budget"], queryFn: api.budget });
  const projects = useQuery({ queryKey: keys.projects, queryFn: api.projects });
  const { currentId, setCurrent } = useProjectStore();
  const project = useProject(currentId);
  const navigate = useNavigate();

  const s = status.data;
  const services = s
    ? [
        { name: "ComfyUI", ok: s.comfyui.running, detail: s.comfyui.running ? s.comfyui.url : "pas lancé" },
        { name: "Ollama", ok: s.ollama.running && !!s.ollama.model, detail: !s.ollama.running ? "pas lancé" : s.ollama.model || "aucun modèle choisi (OLLAMA_MODEL)" },
        { name: "FFmpeg", ok: s.ffmpeg.available, detail: s.ffmpeg.available ? "installé" : "introuvable" },
        { name: "Carte graphique", ok: s.gpu.available, detail: s.gpu.available ? `${s.gpu.name} · ${Math.round(s.gpu.vram_free_mb / 1024)} / ${Math.round(s.gpu.vram_total_mb / 1024)} Go libres` : "non détectée" },
      ]
    : [];

  return (
    <>
      <PageHeader
        title="Tableau de bord"
        subtitle="Vue d'ensemble de ta production de Shorts."
        actions={<Button variant="primary" onClick={() => navigate("/idees")}>Nouveau Short</Button>}
      />

      <div className="grid gap-4 md:grid-cols-4">
        {services.map((svc) => (
          <div key={svc.name} className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-4">
            <p className="flex items-center gap-2 text-sm font-medium">
              <span className={svc.ok ? "text-emerald-400" : "text-red-400"}>●</span> {svc.name}
            </p>
            <p className="mt-1 truncate text-xs text-zinc-400" title={svc.detail}>{svc.detail}</p>
          </div>
        ))}
        {status.isLoading && <p className="text-sm text-zinc-500">Vérification des services…</p>}
      </div>

      {budget.data && (
        <div className="mt-4 grid gap-4 md:grid-cols-2">
          <Card title="Budget du jour">
            <p className="mb-2 text-sm">{usd(budget.data.spent_today)} dépensés sur {usd(budget.data.budget_max_per_day)}</p>
            <Meter value={budget.data.spent_today} max={budget.data.budget_max_per_day} />
          </Card>
          <Card title="Budget du mois">
            <p className="mb-2 text-sm">{usd(budget.data.spent_month)} dépensés sur {usd(budget.data.budget_max_per_month)}</p>
            <Meter value={budget.data.spent_month} max={budget.data.budget_max_per_month} />
          </Card>
        </div>
      )}

      <div className="mt-6 grid gap-6 lg:grid-cols-5">
        <div className="space-y-4 lg:col-span-3">
          {project.data ? (
            <>
              <div>
                <h2 className="text-lg font-medium">{project.data.title}</h2>
                <p className="text-sm text-zinc-400">{project.data.niche || "Sans niche"} · créé le {dateTime(project.data.created_at)}</p>
              </div>
              <NextAction project={project.data} />
              <PipelineTimeline project={project.data} />
            </>
          ) : (
            <Empty action={<Button variant="primary" onClick={() => navigate("/idees")}>Créer un projet</Button>}>
              Aucun projet ouvert.
            </Empty>
          )}
        </div>
        <div className="lg:col-span-2">
          <Card title="Projets">
            {projects.data?.length ? (
              <ul className="divide-y divide-zinc-800">
                {projects.data.map((p) => (
                  <li key={p.id}>
                    <button
                      type="button"
                      onClick={() => setCurrent(p.id)}
                      className={`flex w-full items-center justify-between gap-2 px-1 py-2 text-left text-sm hover:text-violet-200 ${p.id === currentId ? "text-violet-300" : ""}`}
                    >
                      <span className="truncate">{p.title}</span>
                      <Badge tone={p.status === "done" ? "green" : p.status === "cancelled" ? "zinc" : "violet"}>
                        {PROJECT_STATUS_LABELS[p.status] ?? p.status}
                      </Badge>
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-zinc-500">Pas encore de projet.</p>
            )}
          </Card>
          <div className="mt-4 grid grid-cols-2 gap-4">
            <Stat label="Projets" value={projects.data?.length ?? "—"} />
            <Stat label="Terminés" value={projects.data?.filter((p) => p.status === "done").length ?? "—"} />
          </div>
        </div>
      </div>
    </>
  );
}
