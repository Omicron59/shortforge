// Voix off locale (Piper, voix Windows/macOS) ou ElevenLabs, et sous-titres animes (20 styles, 7 effets).
import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, fileUrl } from "../api/client";
import { useAction } from "../api/hooks";
import type { ProjectDetail, SubtitlePreset } from "../api/types";
import { WithProject } from "../components/Layout";
import { NextAction, stepOf } from "../components/Pipeline";
import { Alert, Badge, Button, Card, Field, PageHeader, StatusBadge, inputClass } from "../components/ui";
import { seconds, spokenDuration } from "../lib/format";

export default function VoiceSubtitles() {
  return (
    <>
      <PageHeader title="Voix et sous-titres" subtitle="La voix off est créée sur ton ordinateur ; les sous-titres animés suivent chaque mot." />
      <div className="space-y-6">
        <VoiceSettings />
        <WithProject>{(project) => <ProjectVoice project={project} />}</WithProject>
      </div>
    </>
  );
}

function VoiceSettings() {
  const state = useQuery({ queryKey: ["voice"], queryFn: api.voice });
  const save = useAction((body: Parameters<typeof api.setVoice>[0]) => api.setVoice(body), "Réglage de la voix enregistré.");
  const [sampleUrl, setSampleUrl] = useState<string | null>(null);
  const sample = useAction(async () => {
    const res = await api.voiceSample();
    setSampleUrl(fileUrl(res.url, { t: Date.now() }));
    return res;
  });
  const s = state.data;
  if (!s) return null;

  return (
    <Card title="Voix off">
      <div className="grid gap-4 md:grid-cols-3">
        <Field label="Moteur">
          <select className={inputClass} value={s.settings.engine} onChange={(e) => save.mutate({ engine: e.target.value })}>
            <option value="auto">Automatique (Piper si prêt, sinon la voix du système)</option>
            {s.engines.map((e) => <option key={e.id} value={e.id}>{e.name}{e.available ? "" : " (non prêt)"}</option>)}
          </select>
        </Field>
        <Field label={`Vitesse (${s.settings.speed.toFixed(2).replace(".", ",")})`}>
          <input type="range" min={0.7} max={1.4} step={0.05} defaultValue={s.settings.speed} onMouseUp={(e) => save.mutate({ speed: Number((e.target as HTMLInputElement).value) })} />
        </Field>
        <label className="mt-6 flex items-center gap-2 text-sm">
          <input type="checkbox" checked={s.settings.enabled} onChange={(e) => save.mutate({ enabled: e.target.checked })} /> Ajouter une voix off aux Shorts
        </label>
      </div>
      <ul className="mt-4 space-y-1 text-sm">
        {s.engines.map((e) => (
          <li key={e.id} className="flex items-center gap-2">
            <span className={e.available ? "text-emerald-400" : "text-zinc-500"}>{e.available ? "●" : "○"}</span>
            {e.name} {!e.local && <Badge tone="yellow">payant</Badge>}
            <span className="text-xs text-zinc-500">{e.detail}</span>
          </li>
        ))}
      </ul>
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <Button busy={sample.isPending} onClick={() => sample.mutate(undefined)}>Écouter un essai</Button>
        {sampleUrl && <audio src={sampleUrl} controls autoPlay />}
      </div>
      <p className="mt-3 text-xs text-zinc-500">
        Piper (voix naturelle, gratuite) : installe-le puis indique PIPER_PATH et PIPER_VOICE (fichier .onnx d'une voix française) dans le fichier de réglages.
        ElevenLabs (ta voix clonée) est payant : chaque génération demande ta confirmation avec le coût.
      </p>
    </Card>
  );
}

function ProjectVoice({ project }: { project: ProjectDetail }) {
  const approved = stepOf(project, "approve_script")?.status === "done";
  const scenes = useQuery({ queryKey: ["scenes", project.id], queryFn: () => api.scenes(project.id), enabled: approved });
  const presets = useQuery({ queryKey: ["subtitle-presets"], queryFn: api.subtitlePresets });
  const saved = useQuery({ queryKey: ["subtitles", project.id], queryFn: () => api.subtitles(project.id) });
  const choose = useAction((preset: string) => api.setSubtitlePreset(project.id, preset), "Style choisi : il sera utilisé au prochain montage.");
  const voice = stepOf(project, "generate_voice");
  const subtitles = stepOf(project, "create_subtitles");
  const [preview, setPreview] = useState<string | null>(null);
  useEffect(() => setPreview(saved.data ? (saved.data as unknown as { preset?: string }).preset ?? null : null), [saved.data]);

  return (
    <div className="space-y-6">
      <NextAction project={project} />
      <div className="grid gap-4 md:grid-cols-2">
        <Card title="Voix off de ce Short">
          <div className="flex items-center gap-2 text-sm">{voice && <StatusBadge status={voice.status} />}
            {voice?.output?.engine ? <span className="text-zinc-400">{String(voice.output.engine)} · minutage {String(voice.output.word_timing ?? "")}</span> : null}
          </div>
          {Array.isArray(voice?.output?.lengthened_scenes) && (voice.output.lengthened_scenes as number[]).length > 0 && (
            <p className="mt-2 text-xs text-zinc-400">Scènes allongées pour laisser la voix finir : {(voice.output.lengthened_scenes as number[]).join(", ")}</p>
          )}
          {voice?.output?.skipped ? <p className="mt-2 text-xs text-zinc-500">{String(voice.output.message)}</p> : null}
        </Card>
        <Card title="Sous-titres de ce Short">
          <div className="flex items-center gap-2 text-sm">{subtitles && <StatusBadge status={subtitles.status} />}
            {subtitles?.output?.segments !== undefined && <span className="text-zinc-400">{String(subtitles.output.segments)} lignes · {String(subtitles.output.source ?? "")}</span>}
          </div>
        </Card>
      </div>

      <Card title="Style des sous-titres">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {presets.data?.presets.map((p) => (
            <PresetTile key={p.id} preset={p} effectLabel={presets.data.effects[p.style.effect]} active={preview === p.id}
              onClick={() => { setPreview(p.id); choose.mutate(p.id); }} />
          ))}
        </div>
        <p className="mt-3 text-xs text-zinc-500">Pour changer le style d'une vidéo déjà montée, refais l'étape « Montage ». Le style par défaut se règle dans Paramètres → Marque.</p>
      </Card>

      {approved && scenes.data && (
        <Card title="Texte et minutage">
          <ol className="space-y-2">
            {scenes.data.map((scene) => {
              const spoken = spokenDuration(scene.text);
              return (
                <li key={scene.id} className="rounded-lg border border-zinc-800 p-3 text-sm">
                  <div className="mb-1 flex justify-between text-xs text-zinc-500">
                    <span>Scène {scene.position + 1} · {seconds(scene.duration_s)}</span>
                    <span>parole estimée ≈ {seconds(spoken)}</span>
                  </div>
                  <p>{scene.text || <span className="text-zinc-600">(pas de texte dit)</span>}</p>
                </li>
              );
            })}
          </ol>
        </Card>
      )}
      {!approved && <Alert tone="blue">Valide d'abord le script : la voix off lit le texte validé.</Alert>}
    </div>
  );
}

function PresetTile({ preset, effectLabel, active, onClick }: { preset: SubtitlePreset; effectLabel?: string; active: boolean; onClick: () => void }) {
  const st = preset.style;
  const words = ["Tu", "ne", "vas", "pas", "y", "croire"].slice(0, Math.max(2, st.words_per_line));
  const pos = st.position === "top" ? "top-3" : st.position === "middle" ? "top-1/2 -translate-y-1/2" : "bottom-4";
  return (
    <button type="button" onClick={onClick}
      className={`overflow-hidden rounded-lg border text-left ${active ? "border-violet-500 ring-2 ring-violet-500/40" : "border-zinc-800 hover:border-zinc-600"}`}>
      <div className="relative h-28 bg-gradient-to-br from-zinc-600 to-zinc-900">
        <p className={`absolute left-2 right-2 text-center leading-tight ${pos} ${st.uppercase ? "uppercase" : ""}`}
          style={{ fontFamily: st.font, fontWeight: st.bold ? 800 : 500, fontSize: Math.max(11, st.size / 5.5), color: st.color,
            WebkitTextStroke: st.box ? undefined : `1px ${st.outline_color}`, background: st.box ? st.outline_color : undefined,
            padding: st.box ? "2px 4px" : undefined }}>
          {words.map((w, i) => <span key={i} style={i === 1 && st.effect !== "aucun" && st.effect !== "fondu" && st.effect !== "pop" ? { color: st.highlight_color } : undefined}>{w} </span>)}
        </p>
      </div>
      <div className="px-2 py-1.5">
        <p className="text-sm font-medium">{preset.label}</p>
        <p className="text-xs text-zinc-500">{effectLabel}</p>
      </div>
    </button>
  );
}
