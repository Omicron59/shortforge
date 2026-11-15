// Video longue → Shorts : import, transcription locale, choix des meilleurs passages, un Short par passage.
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { useAction } from "../api/hooks";
import type { SourceVideo } from "../api/types";
import { Alert, Badge, Button, Card, Empty, Field, PageHeader, Spinner, inputClass } from "../components/ui";
import { LANGUAGES, seconds } from "../lib/format";

const STATUS: Record<string, string> = { imported: "importée", transcribed: "transcrite", analysed: "analysée", failed: "échec" };

export default function LongVideo() {
  const sources = useQuery({ queryKey: ["sources"], queryFn: api.sources, refetchInterval: 3000 });
  const [file, setFile] = useState<File | null>(null);
  const [rights, setRights] = useState(false);
  const [language, setLanguage] = useState("fr");
  const upload = useAction(() => api.uploadSource(file!, { title: file!.name, rights_confirmed: rights, language }), "Vidéo importée.");

  return (
    <>
      <PageHeader title="Vidéo longue → Shorts" subtitle="Importe une vidéo que tu as filmée : ShortForge la transcrit, repère les meilleurs passages et en fait des Shorts sous-titrés." />
      <div className="space-y-6">
        <Card title="Importer une vidéo">
          <div className="flex flex-wrap items-end gap-4">
            <input type="file" accept="video/*" className="text-sm text-zinc-400" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
            <Field label="Langue parlée">
              <select className={inputClass} value={language} onChange={(e) => setLanguage(e.target.value)}>
                {Object.entries(LANGUAGES).map(([c, l]) => <option key={c} value={c}>{l}</option>)}
              </select>
            </Field>
          </div>
          <label className="mt-3 flex items-center gap-2 text-sm">
            <input type="checkbox" checked={rights} onChange={(e) => setRights(e.target.checked)} />
            Cette vidéo est la mienne, ou j'ai le droit de la réutiliser.
          </label>
          <Button className="mt-3" variant="primary" disabled={!file || !rights} busy={upload.isPending}
            onClick={() => upload.mutate(undefined, { onSuccess: () => setFile(null) })}>Importer</Button>
          <p className="mt-2 text-xs text-zinc-500">La transcription utilise faster-whisper sur ton ordinateur (premier usage : téléchargement du modèle). Recadrage vertical centré.</p>
        </Card>
        {sources.data?.length ? sources.data.map((s) => <SourceCard key={s.id} source={s} />) : <Empty>Aucune vidéo importée.</Empty>}
      </div>
    </>
  );
}

function SourceCard({ source }: { source: SourceVideo }) {
  const [count, setCount] = useState(5);
  const [chosen, setChosen] = useState<number[]>([]);
  const navigate = useNavigate();
  const analyse = useAction(() => api.analyseSource(source.id, count), "Analyse lancée.");
  const create = useAction(() => api.createClips(source.id, chosen), "Shorts créés : montage en cours.");
  const remove = useAction(() => api.deleteSource(source.id), "Vidéo supprimée.");

  return (
    <Card title={source.title} actions={<div className="flex items-center gap-2">
      <Badge tone={source.status === "failed" ? "red" : source.status === "analysed" ? "green" : "zinc"}>{STATUS[source.status] ?? source.status}</Badge>
      <Badge>{seconds(source.duration_s)}</Badge>
      <Button variant="ghost" className="text-xs" onClick={() => remove.mutate(undefined)}>Supprimer</Button>
    </div>}>
      {source.error && <Alert tone="red">{source.error}</Alert>}
      {source.busy ? (
        <p className="flex items-center gap-2 text-sm text-zinc-400"><Spinner /> Transcription et analyse en cours…</p>
      ) : (
        <div className="flex items-end gap-2">
          <Field label="Nombre de Shorts"><input type="number" min={1} max={10} className={`${inputClass} w-24`} value={count} onChange={(e) => setCount(Number(e.target.value))} /></Field>
          <Button onClick={() => analyse.mutate(undefined)}>{source.proposals.length ? "Relancer l'analyse" : "Trouver les meilleurs passages"}</Button>
        </div>
      )}
      {source.proposals.length > 0 && (
        <>
          <ul className="mt-4 space-y-2">
            {source.proposals.map((p, i) => (
              <li key={i} className="flex items-start gap-3 rounded-lg border border-zinc-800 p-3 text-sm">
                <input type="checkbox" className="mt-1" checked={chosen.includes(i)} onChange={(e) => setChosen(e.target.checked ? [...chosen, i] : chosen.filter((c) => c !== i))} />
                <div className="flex-1">
                  <p className="font-medium">{p.title} <span className="text-zinc-500">({seconds(p.start)} → {seconds(p.end)}, {seconds(p.end - p.start)})</span></p>
                  {p.hook && <p className="text-zinc-400">« {p.hook} »</p>}
                  {p.why && <p className="text-xs text-zinc-500">{p.why}</p>}
                </div>
              </li>
            ))}
          </ul>
          <Button className="mt-3" variant="primary" disabled={!chosen.length} busy={create.isPending}
            onClick={() => create.mutate(undefined, { onSuccess: () => navigate("/a-valider") })}>Créer {chosen.length} Short(s)</Button>
        </>
      )}
    </Card>
  );
}
