// Formats gagnants : suivi de 5 comptes, Shorts a 2x leur mediane, recette du format, nouveau Short en un clic.
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { useAction } from "../api/hooks";
import type { Competitor, CompetitorVideo, VideoMode } from "../api/types";
import { Alert, Badge, Button, Card, Empty, Field, PageHeader, inputClass } from "../components/ui";
import { VIDEO_MODE_LABELS } from "../lib/format";
import { useProjectStore } from "../stores/project";

export default function Formats() {
  const competitors = useQuery({ queryKey: ["competitors"], queryFn: api.competitors });
  const [platform, setPlatform] = useState<"youtube" | "tiktok">("youtube");
  const [handle, setHandle] = useState("");
  const [niche, setNiche] = useState("");
  const [mode, setMode] = useState<VideoMode>("economique");
  const add = useAction(() => api.addCompetitor(platform, handle.trim()), "Compte ajouté.");

  return (
    <>
      <PageHeader title="Formats gagnants" subtitle="Repère les Shorts qui font au moins 2x les vues habituelles d'un compte, et réutilise leur format avec une histoire 100 % nouvelle." />
      <div className="space-y-6">
        <Alert tone="blue">
          Seuls le titre, la durée et les vues publiques sont lus : aucune vidéo n'est téléchargée ni recopiée. TikTok n'ouvre pas ces données :
          pour un compte TikTok, ajoute ses Shorts à la main (titre et nombre de vues).
        </Alert>
        <Card title={`Comptes suivis (${competitors.data?.length ?? 0}/5)`}>
          <div className="flex flex-wrap items-end gap-3">
            <Field label="Plateforme">
              <select className={inputClass} value={platform} onChange={(e) => setPlatform(e.target.value as "youtube" | "tiktok")}>
                <option value="youtube">YouTube</option>
                <option value="tiktok">TikTok</option>
              </select>
            </Field>
            <Field label="Compte (@nom ou adresse)"><input className={`${inputClass} w-72`} value={handle} onChange={(e) => setHandle(e.target.value)} /></Field>
            <Button variant="primary" disabled={handle.trim().length < 2 || (competitors.data?.length ?? 0) >= 5} busy={add.isPending}
              onClick={() => add.mutate(undefined, { onSuccess: () => setHandle("") })}>Suivre</Button>
          </div>
          <div className="mt-4 grid gap-4 md:grid-cols-2">
            <Field label="Niche de tes Shorts"><input className={inputClass} value={niche} onChange={(e) => setNiche(e.target.value)} placeholder="Ta niche (le format sera adapté)" /></Field>
            <Field label="Mode vidéo">
              <select className={inputClass} value={mode} onChange={(e) => setMode(e.target.value as VideoMode)}>
                {Object.entries(VIDEO_MODE_LABELS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
            </Field>
          </div>
        </Card>
        {competitors.data?.length ? competitors.data.map((c) => <CompetitorCard key={c.id} competitor={c} niche={niche} mode={mode} />)
          : <Empty>Ajoute jusqu'à 5 comptes de ta niche.</Empty>}
      </div>
    </>
  );
}

function CompetitorCard({ competitor, niche, mode }: { competitor: Competitor; niche: string; mode: VideoMode }) {
  const refresh = useAction(() => api.refreshCompetitor(competitor.id), "Compte mis à jour.");
  const remove = useAction(() => api.deleteCompetitor(competitor.id), "Compte retiré.");
  const [title, setTitle] = useState("");
  const [views, setViews] = useState("");
  const addVideo = useAction(() => api.addCompetitorVideo(competitor.id, { title, views: Number(views) }), "Short ajouté.");
  const outliers = competitor.videos.filter((v) => v.outlier);

  return (
    <Card title={`${competitor.title} (${competitor.platform === "youtube" ? "YouTube" : "TikTok"})`}
      actions={<div className="flex gap-2">
        {competitor.platform === "youtube" && <Button className="text-xs" busy={refresh.isPending} onClick={() => refresh.mutate(undefined)}>Actualiser</Button>}
        <Button variant="ghost" className="text-xs" onClick={() => remove.mutate(undefined)}>Retirer</Button>
      </div>}>
      <p className="mb-3 text-sm text-zinc-400">Médiane : {Math.round(competitor.median_views).toLocaleString("fr-FR")} vues · {outliers.length} Short(s) gagnant(s) sur {competitor.videos.length}</p>
      <ul className="space-y-2">
        {competitor.videos.slice(0, 12).map((v) => <VideoRow key={v.id} video={v} niche={niche} mode={mode} />)}
      </ul>
      {competitor.platform === "tiktok" && (
        <div className="mt-4 flex flex-wrap items-end gap-2">
          <input className={`${inputClass} w-72`} value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Titre ou description du Short" />
          <input className={`${inputClass} w-32`} inputMode="numeric" value={views} onChange={(e) => setViews(e.target.value)} placeholder="Vues" />
          <Button disabled={title.length < 2 || !Number(views)} onClick={() => addVideo.mutate(undefined, { onSuccess: () => { setTitle(""); setViews(""); } })}>Ajouter</Button>
        </div>
      )}
    </Card>
  );
}

function VideoRow({ video, niche, mode }: { video: CompetitorVideo; niche: string; mode: VideoMode }) {
  const recipe = useAction(() => api.recipe(video.id));
  const navigate = useNavigate();
  const setCurrent = useProjectStore((s) => s.setCurrent);
  const make = useAction(() => api.makeShort(video.id, { niche, language: "fr", video_mode: mode }), "Nouveau Short lancé.");
  const r = video.recipe;
  return (
    <li className={`rounded-lg border p-3 text-sm ${video.outlier ? "border-amber-600/60 bg-amber-950/20" : "border-zinc-800"}`}>
      <div className="flex flex-wrap items-center gap-2">
        {video.outlier && <Badge tone="yellow">x{video.ratio.toLocaleString("fr-FR")}</Badge>}
        <span className="flex-1">{video.title}</span>
        <span className="text-zinc-400">{video.views.toLocaleString("fr-FR")} vues</span>
        {video.outlier && !r && <Button className="text-xs" busy={recipe.isPending} onClick={() => recipe.mutate(undefined)}>Analyser le format</Button>}
        {video.outlier && (
          <Button variant="primary" className="text-xs" busy={make.isPending}
            onClick={() => make.mutate(undefined, { onSuccess: (res) => { setCurrent(res.project_id); navigate("/"); } })}>
            Fabriquer mon Short
          </Button>
        )}
      </div>
      {r && (
        <div className="mt-2 grid gap-1 text-xs text-zinc-400">
          <p><span className="text-zinc-500">Accroche :</span> {r.hook_type} · <span className="text-zinc-500">Rythme :</span> {r.pacing}</p>
          <p><span className="text-zinc-500">Structure :</span> {r.structure.join(" → ")}</p>
          <p><span className="text-zinc-500">Chute :</span> {r.ending} · <span className="text-zinc-500">Pourquoi ça marche :</span> {r.why_it_works}</p>
        </div>
      )}
    </li>
  );
}
