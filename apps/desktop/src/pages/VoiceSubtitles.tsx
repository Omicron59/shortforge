// Voix off et sous-titres : texte a dire, minutage par scene et style des sous-titres incrustes.
// Les sous-titres sont calcules a partir du texte des scenes et incrustes au montage FFmpeg.
// La voix off n'est pas encore generee : la video est exportee avec une piste muette.
import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { useAction } from "../api/hooks";
import type { ProjectDetail } from "../api/types";
import { WithProject } from "../components/Layout";
import { stepOf } from "../components/Pipeline";
import { Alert, Button, Card, Empty, Field, PageHeader, StatusBadge, inputClass } from "../components/ui";
import { seconds, spokenDuration } from "../lib/format";

export default function VoiceSubtitles() {
  return (
    <>
      <PageHeader title="Voix et sous-titres" subtitle="Ce que la voix off dira, scène par scène, et l'aspect des sous-titres." />
      <WithProject>{(project) => <VoiceBody project={project} />}</WithProject>
    </>
  );
}

interface Segment { start: number; end: number; text: string }

/** Decoupe le texte d'une scene en sous-titres de 4 mots au plus, repartis sur sa duree. */
function segmentsFor(text: string, start: number, duration: number): Segment[] {
  const words = text.split(/\s+/).filter(Boolean);
  if (!words.length) return [];
  const chunks: string[] = [];
  for (let i = 0; i < words.length; i += 4) chunks.push(words.slice(i, i + 4).join(" "));
  const step = duration / chunks.length;
  return chunks.map((c, i) => ({ start: start + i * step, end: start + (i + 1) * step, text: c }));
}

const POSITIONS = { bottom: "bottom-[18%]", middle: "top-1/2 -translate-y-1/2", top: "top-[12%]" } as const;

function VoiceBody({ project }: { project: ProjectDetail }) {
  const approved = stepOf(project, "approve_script")?.status === "done";
  const scenes = useQuery({ queryKey: ["scenes", project.id], queryFn: () => api.scenes(project.id), enabled: approved });
  const voice = stepOf(project, "generate_voice");
  const subtitles = stepOf(project, "create_subtitles");
  const saved = useQuery({ queryKey: ["subtitles", project.id], queryFn: () => api.subtitles(project.id) });
  const [position, setPosition] = useState<keyof typeof POSITIONS>("bottom");
  const [color, setColor] = useState("#ffffff");
  const [outline, setOutline] = useState("#000000");
  const [size, setSize] = useState(78);
  const [uppercase, setUppercase] = useState(true);
  const [current, setCurrent] = useState(0);
  const save = useAction(() => api.setSubtitleStyle(project.id, {
    position, style: { color, outline_color: outline, size, uppercase },
  }), "Style enregistré : il sera utilisé au prochain montage.");

  useEffect(() => {
    if (!saved.data) return;
    setPosition(saved.data.position);
    setColor(saved.data.style.color);
    setOutline(saved.data.style.outline_color);
    setSize(saved.data.style.size);
    setUppercase(saved.data.style.uppercase);
  }, [saved.data]);

  const timeline = useMemo(() => {
    let t = 0;
    return (scenes.data ?? []).map((scene) => {
      const segs = segmentsFor(scene.text, t, scene.duration_s);
      const row = { scene, start: t, segs, spoken: spokenDuration(scene.text) };
      t += scene.duration_s;
      return row;
    });
  }, [scenes.data]);
  const allSegments = timeline.flatMap((r) => r.segs);
  const shown = allSegments[Math.min(current, allSegments.length - 1)];

  if (!approved) return <Empty>Valide d'abord le script : la voix off suit le texte validé.</Empty>;

  return (
    <div className="space-y-4">
      <div className="grid gap-4 md:grid-cols-2">
        <Card title="Voix off">
          <div className="flex items-center gap-2 text-sm">Étape : {voice && <StatusBadge status={voice.status} />}</div>
        </Card>
        <Card title="Sous-titres">
          <div className="flex items-center gap-2 text-sm">Étape : {subtitles && <StatusBadge status={subtitles.status} />}</div>
        </Card>
      </div>
      <Alert tone="blue" title="Ce qui est en place">
        Les sous-titres sont créés à partir du texte des scènes et incrustés dans la vidéo au montage (fichier .srt gardé à côté).
        La voix off (Piper, XTTS ou F5-TTS) n'est pas encore générée : la vidéo est exportée avec une piste son muette.
      </Alert>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="Texte et minutage" className="lg:col-span-2">
          <ol className="space-y-3">
            {timeline.map(({ scene, start, spoken }) => (
              <li key={scene.id} className="rounded-lg border border-zinc-800 p-3 text-sm">
                <div className="mb-1 flex justify-between text-xs text-zinc-500">
                  <span>Scène {scene.position + 1} · {seconds(start)} → {seconds(start + scene.duration_s)}</span>
                  <span className={spoken > scene.duration_s ? "text-red-400" : ""}>
                    parole ≈ {seconds(spoken)}{spoken > scene.duration_s ? " : trop long pour la scène" : ""}
                  </span>
                </div>
                <p>{scene.text || <span className="text-zinc-600">(pas de texte dit)</span>}</p>
              </li>
            ))}
          </ol>
        </Card>

        <Card title="Style des sous-titres (aperçu)">
          <div className="relative mx-auto aspect-[9/16] w-48 overflow-hidden rounded-lg bg-gradient-to-b from-zinc-700 to-zinc-900">
            {shown && (
              <p className={`absolute left-2 right-2 text-center font-extrabold leading-tight ${uppercase ? "uppercase" : ""} ${POSITIONS[position]}`}
                style={{ color, fontSize: size * (192 / 1080), WebkitTextStroke: `1px ${outline}`, textShadow: `0 1px 2px ${outline}` }}>
                {shown.text}
              </p>
            )}
          </div>
          {allSegments.length > 0 && (
            <input type="range" min={0} max={allSegments.length - 1} value={current} onChange={(e) => setCurrent(Number(e.target.value))} className="mt-3 w-full" aria-label="Sous-titre affiché" />
          )}
          <div className="mt-3 grid gap-3">
            <Field label="Position">
              <select className={inputClass} value={position} onChange={(e) => setPosition(e.target.value as keyof typeof POSITIONS)}>
                <option value="bottom">En bas</option>
                <option value="middle">Au milieu</option>
                <option value="top">En haut</option>
              </select>
            </Field>
            <div className="grid grid-cols-3 gap-2">
              <Field label="Texte"><input type="color" value={color} onChange={(e) => setColor(e.target.value)} className="h-9 w-full" /></Field>
              <Field label="Contour"><input type="color" value={outline} onChange={(e) => setOutline(e.target.value)} className="h-9 w-full" /></Field>
              <Field label="Taille (px)"><input type="number" min={36} max={140} value={size} onChange={(e) => setSize(Number(e.target.value))} className={inputClass} /></Field>
            </div>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={uppercase} onChange={(e) => setUppercase(e.target.checked)} /> Majuscules
            </label>
            <Button variant="primary" busy={save.isPending} onClick={() => save.mutate(undefined)}>Enregistrer le style</Button>
            <p className="text-xs text-zinc-500">Appliqué au prochain montage. Pour l'appliquer à une vidéo déjà montée, refais l'étape « Montage ».</p>
          </div>
        </Card>
      </div>
    </div>
  );
}
