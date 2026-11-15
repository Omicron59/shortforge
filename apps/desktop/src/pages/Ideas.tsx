// Choix de la niche, generation des idees avec Ollama et choix de l'idee.
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { useAction, useProject } from "../api/hooks";
import type { Idea, ProjectDetail, VideoMode } from "../api/types";
import { NextAction, stepOf } from "../components/Pipeline";
import { Alert, Badge, Button, Card, Empty, Field, PageHeader, inputClass } from "../components/ui";
import { LANGUAGES, REUSE_RISK_LABELS, VIDEO_MODE_LABELS, seconds } from "../lib/format";
import { useProjectStore } from "../stores/project";

const NICHE_SUGGESTIONS = ["Humour du quotidien", "Animaux", "Faits insolites", "Histoire", "Science", "Cuisine", "Motivation", "Technologie"];

export default function Ideas() {
  const currentId = useProjectStore((s) => s.currentId);
  const project = useProject(currentId);
  const [creating, setCreating] = useState(false);

  return (
    <>
      <PageHeader
        title="Niche et idées"
        subtitle="Les tendances servent d'inspiration : chaque idée doit avoir un angle original."
        actions={project.data && !creating && <Button onClick={() => setCreating(true)}>Nouveau projet</Button>}
      />
      {!project.data || creating ? (
        <NewProject onDone={() => setCreating(false)} onCancel={project.data ? () => setCreating(false) : undefined} />
      ) : (
        <IdeaList project={project.data} />
      )}
    </>
  );
}

function NewProject({ onDone, onCancel }: { onDone: () => void; onCancel?: () => void }) {
  const [title, setTitle] = useState("");
  const [niche, setNiche] = useState("");
  const [language, setLanguage] = useState("fr");
  const [mode, setMode] = useState<VideoMode>("economique");
  const setCurrent = useProjectStore((s) => s.setCurrent);
  const create = useAction(async () => {
    const project = await api.createProject({ title: title.trim(), niche: niche.trim(), language, video_mode: mode });
    setCurrent(project.id);
    await api.advance(project.id); // lance tout de suite la generation des idees
    return project;
  }, "Projet créé : génération des idées lancée.");

  return (
    <Card title="Nouveau Short">
      <div className="grid gap-4 md:grid-cols-2">
        <Field label="Nom du projet">
          <input className={inputClass} value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Ex. : Le grille-pain qui chante" />
        </Field>
        <Field label="Langue de la vidéo">
          <select className={inputClass} value={language} onChange={(e) => setLanguage(e.target.value)}>
            {Object.entries(LANGUAGES).map(([code, label]) => <option key={code} value={code}>{label}</option>)}
          </select>
        </Field>
        <Field label="Niche" hint="Le thème de ta chaîne ou de ce Short.">
          <input className={inputClass} value={niche} onChange={(e) => setNiche(e.target.value)} placeholder="Ex. : humour du quotidien" />
          <div className="mt-2 flex flex-wrap gap-1">
            {NICHE_SUGGESTIONS.map((n) => (
              <button key={n} type="button" onClick={() => setNiche(n)} className="rounded-full bg-zinc-800 px-2 py-0.5 text-xs text-zinc-300 hover:bg-zinc-700">{n}</button>
            ))}
          </div>
        </Field>
        <Field label="Mode vidéo" hint="Modifiable plus tard dans la revue des scènes.">
          <select className={inputClass} value={mode} onChange={(e) => setMode(e.target.value as VideoMode)}>
            {Object.entries(VIDEO_MODE_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </Field>
      </div>
      <div className="mt-5 flex gap-2">
        <Button variant="primary" disabled={!title.trim()} busy={create.isPending} onClick={() => create.mutate(undefined, { onSuccess: onDone })}>
          Créer et générer des idées
        </Button>
        {onCancel && <Button variant="ghost" onClick={onCancel}>Annuler</Button>}
      </div>
    </Card>
  );
}

const RISK_TONES = { low: "green", medium: "yellow", high: "red" } as const;

function IdeaList({ project }: { project: ProjectDetail }) {
  const ideas = useQuery({ queryKey: ["ideas", project.id], queryFn: () => api.ideas(project.id) });
  const select = useAction((idea: Idea) => api.selectIdea(project.id, idea.id), "Idée choisie.");
  const navigate = useNavigate();
  const generate = stepOf(project, "generate_ideas");
  const choose = stepOf(project, "select_idea");
  const locked = choose?.status === "done";
  const warnings = (generate?.output?.warnings as string[] | undefined) ?? [];

  return (
    <div className="space-y-4">
      <div className="text-sm text-zinc-400">Projet <span className="text-zinc-100">{project.title}</span> · niche « {project.niche || "aucune"} »</div>
      {!locked && <NextAction project={project} gateHint="Choisis d'abord une idée ci-dessous, puis valide." />}
      {locked && (
        <Alert tone="green">
          Idée validée. <button type="button" className="underline" onClick={() => navigate("/script")}>Passer au script →</button>
        </Alert>
      )}
      {warnings.length > 0 && <Alert tone="yellow" title="Sources de tendances indisponibles">{warnings.join("\n")}</Alert>}

      {ideas.data?.length ? (
        <div className="grid gap-4 md:grid-cols-2">
          {ideas.data.map((idea) => (
            <article
              key={idea.id}
              className={`flex flex-col gap-3 rounded-xl border p-5 ${idea.selected ? "border-violet-500 bg-violet-950/30" : "border-zinc-800 bg-zinc-900/60"}`}
            >
              <div className="flex items-start justify-between gap-3">
                <h3 className="font-medium">{idea.title}</h3>
                <span className="shrink-0 text-sm font-semibold text-violet-300" title="Potentiel estimé">{Math.round(idea.potential_score)}/100</span>
              </div>
              <p className="text-sm text-zinc-300">« {idea.hook} »</p>
              <p className="text-sm text-zinc-400"><span className="text-zinc-500">Angle : </span>{idea.original_angle}</p>
              <div className="flex flex-wrap gap-1.5">
                <Badge tone={RISK_TONES[idea.reuse_risk]}>{REUSE_RISK_LABELS[idea.reuse_risk]} de contenu réutilisé</Badge>
                <Badge>{seconds(idea.estimated_duration_s)}</Badge>
                {idea.visual_style && <Badge tone="blue">{idea.visual_style}</Badge>}
                {idea.keywords.map((k) => <Badge key={k}>#{k}</Badge>)}
              </div>
              {idea.sources.length > 0 && <p className="text-xs text-zinc-500">Inspiré de : {idea.sources.join(", ")}</p>}
              <div className="mt-auto">
                {idea.selected ? (
                  <Badge tone="violet">Idée choisie</Badge>
                ) : (
                  <Button disabled={locked} busy={select.isPending && select.variables?.id === idea.id} onClick={() => select.mutate(idea)}>
                    Choisir cette idée
                  </Button>
                )}
              </div>
            </article>
          ))}
        </div>
      ) : (
        <Empty>{generate?.status === "running" ? "Ollama cherche des idées…" : "Pas encore d'idée : lance la génération."}</Empty>
      )}
    </div>
  );
}
