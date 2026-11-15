// Revue des scenes : images, videos, moteur choisi par scene, cout estime et regeneration.
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, assetUrl } from "../api/client";
import { useAction } from "../api/hooks";
import type { Asset, ProjectDetail, Provider, Scene, VideoMode } from "../api/types";
import { WithProject } from "../components/Layout";
import { NextAction, stepOf } from "../components/Pipeline";
import { Alert, Badge, Button, Card, Empty, Field, PageHeader, inputClass } from "../components/ui";
import { IMPORTANCE_LABELS, TRANSITION_LABELS, VIDEO_MODE_LABELS, seconds, usd } from "../lib/format";

export default function Scenes() {
  return (
    <>
      <PageHeader title="Revue des scènes" subtitle="Vérifie chaque scène, choisis son moteur vidéo et régénère ce qui ne va pas." />
      <WithProject>{(project) => <SceneBoard project={project} />}</WithProject>
    </>
  );
}

function latest(assets: Asset[], sceneId: string, kind: string): Asset | undefined {
  return [...assets].reverse().find((a) => a.scene_id === sceneId && a.kind === kind);
}

function SceneBoard({ project }: { project: ProjectDetail }) {
  const approved = stepOf(project, "approve_script")?.status === "done";
  const scenes = useQuery({ queryKey: ["scenes", project.id], queryFn: () => api.scenes(project.id), enabled: approved });
  const assets = useQuery({ queryKey: ["assets", project.id], queryFn: () => api.assets(project.id), enabled: approved });
  const providers = useQuery({ queryKey: ["providers"], queryFn: api.providers });
  const estimate = useQuery({ queryKey: ["estimate", project.id], queryFn: () => api.costEstimate(project.id), enabled: approved, retry: false });
  const engine = useAction((body: Parameters<typeof api.setEngine>[1]) => api.setEngine(project.id, body), "Réglage du moteur enregistré.");

  if (!approved) {
    return (
      <div className="space-y-4">
        <NextAction project={project} />
        <Empty>Les scènes apparaissent une fois le script validé.</Empty>
      </div>
    );
  }

  const enabledProviders = providers.data?.filter((p) => p.enabled) ?? [];

  return (
    <div className="space-y-4">
      <NextAction project={project} />

      <Card title="Moteur vidéo du projet">
        <div className="grid gap-4 md:grid-cols-3">
          <Field label="Mode">
            <select className={inputClass} value={project.video_mode} onChange={(e) => engine.mutate({ video_mode: e.target.value as VideoMode })}>
              {Object.entries(VIDEO_MODE_LABELS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </Field>
          <Field label="Choix du moteur">
            <select className={inputClass} value={project.engine_scope} onChange={(e) => engine.mutate({ engine_scope: e.target.value as "scene" | "short" })}>
              <option value="scene">Scène par scène (selon le mode)</option>
              <option value="short">Un seul moteur pour tout le Short</option>
            </select>
          </Field>
          <Field label="Moteur unique" hint="Utilisé seulement en mode « un seul moteur ».">
            <select className={inputClass} disabled={project.engine_scope !== "short"} value={project.default_provider} onChange={(e) => engine.mutate({ default_provider: e.target.value })}>
              {enabledProviders.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </Field>
        </div>
        <p className="mt-3 text-xs text-zinc-500">
          Le choix est appliqué au découpage en scènes. Pour l'appliquer à des scènes déjà découpées, refais l'étape « Découpage en scènes ».
          Veo 3 n'est jamais choisi par défaut.
        </p>
      </Card>

      {estimate.data && (
        <div className="flex flex-wrap gap-3 text-sm">
          <Badge tone="violet">Coût estimé du Short : {usd(estimate.data.estimated_total_usd)}</Badge>
          <Badge>Reste aujourd'hui : {usd(estimate.data.budget.remaining_today)}</Badge>
          <Badge>Plafond par scène : {usd(estimate.data.budget.budget_max_per_scene)}</Badge>
          {estimate.data.scenes.some((s) => s.estimated_cost_usd === null) && <Badge tone="red">Un tarif est inconnu</Badge>}
        </div>
      )}

      {scenes.data?.length ? (
        <div className="grid gap-4 xl:grid-cols-2">
          {scenes.data.map((scene) => (
            <SceneCard key={scene.id} scene={scene} providers={providers.data ?? []} image={latest(assets.data ?? [], scene.id, "image")}
              video={latest(assets.data ?? [], scene.id, "video")} />
          ))}
        </div>
      ) : (
        <Empty>Le script n'a pas encore été découpé en scènes.</Empty>
      )}
    </div>
  );
}

const STATUS_LABELS: Record<string, string> = { pending: "à faire", running: "en cours", done: "prête", failed: "échec", image_only: "image animée" };

function SceneCard({ scene, providers, image, video }: { scene: Scene; providers: Provider[]; image?: Asset; video?: Asset }) {
  const [prompt, setPrompt] = useState(scene.visual_prompt);
  const patch = useAction((body: Parameters<typeof api.patchScene>[1]) => api.patchScene(scene.id, body), "Scène modifiée.");
  const regen = useAction((target: "image" | "video") => api.regenerateScene(scene.id, target), "La scène sera régénérée à la prochaine exécution.");
  const provider = providers.find((p) => p.id === scene.provider_id);

  return (
    <article className="flex gap-4 rounded-xl border border-zinc-800 bg-zinc-900/60 p-4">
      <div className="w-36 shrink-0">
        <div className="aspect-[9/16] overflow-hidden rounded-lg bg-zinc-950">
          {video ? (
            <video src={assetUrl(video.id)} poster={image ? assetUrl(image.id) : undefined} controls className="h-full w-full object-cover" />
          ) : image ? (
            <img src={assetUrl(image.id)} alt={`Scène ${scene.position + 1}`} className="h-full w-full object-cover" />
          ) : (
            <div className="flex h-full items-center justify-center text-xs text-zinc-600">Pas d'image</div>
          )}
        </div>
        <div className="mt-2 space-y-1 text-xs text-zinc-400">
          <p>Image : {STATUS_LABELS[scene.image_status] ?? scene.image_status}</p>
          <p>Vidéo : {STATUS_LABELS[scene.status] ?? scene.status}</p>
        </div>
      </div>
      <div className="flex min-w-0 flex-1 flex-col gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-medium">Scène {scene.position + 1}</span>
          <Badge>{seconds(scene.duration_s)}</Badge>
          <Badge>{TRANSITION_LABELS[scene.transition] ?? scene.transition}</Badge>
          {scene.estimated_cost_usd > 0 && <Badge tone="yellow">{usd(scene.estimated_cost_usd)}</Badge>}
        </div>
        {scene.text && <p className="text-sm text-zinc-300">« {scene.text} »</p>}
        <Field label="Prompt visuel">
          <textarea className={inputClass} rows={2} value={prompt} onChange={(e) => setPrompt(e.target.value)} />
        </Field>
        {prompt !== scene.visual_prompt && (
          <Button className="self-start" disabled={prompt.trim().length < 3} onClick={() => patch.mutate({ visual_prompt: prompt })}>Enregistrer le prompt</Button>
        )}
        <div className="grid grid-cols-2 gap-2">
          <Field label="Type de scène">
            <select className={inputClass} value={scene.importance} onChange={(e) => patch.mutate({ importance: e.target.value as Scene["importance"] })}>
              {Object.entries(IMPORTANCE_LABELS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </Field>
          <Field label="Moteur vidéo">
            <select className={inputClass} value={scene.provider_locked ? scene.provider_id ?? "" : ""} onChange={(e) => patch.mutate({ provider_id: e.target.value })}>
              <option value="">Automatique{provider && !scene.provider_locked ? ` (${provider.name})` : ""}</option>
              {providers.filter((p) => p.enabled).map((p) => (
                <option key={p.id} value={p.id} disabled={!p.configured}>
                  {p.name}{p.tier === "premium" ? " · premium" : ""}{!p.configured ? " (non configuré)" : ""}
                </option>
              ))}
            </select>
          </Field>
        </div>
        {scene.provider_reason && <p className="text-xs text-zinc-500">Pourquoi ce moteur : {scene.provider_reason}</p>}
        {provider?.tier === "premium" && <Alert tone="yellow">Moteur premium : coût élevé, confirmation demandée avant génération.</Alert>}
        <div className="mt-auto flex gap-2">
          <Button className="text-xs" onClick={() => regen.mutate("image")}>Régénérer l'image</Button>
          <Button className="text-xs" onClick={() => regen.mutate("video")}>Régénérer la vidéo</Button>
        </div>
      </div>
    </article>
  );
}
