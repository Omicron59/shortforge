// Mon style : ShortForge apprend ta facon d'ecrire et de parler, puis l'applique a tes scripts.
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { useAction } from "../api/hooks";
import { Alert, Badge, Button, Card, Field, PageHeader, inputClass } from "../components/ui";
import { dateTime } from "../lib/format";

export default function MyStyle() {
  const style = useQuery({ queryKey: ["style"], queryFn: api.style });
  const [texts, setTexts] = useState("");
  const learn = useAction(() => api.learnStyle(texts.split(/\n-{3,}\n/).map((t) => t.trim()).filter(Boolean)), "Style appris.");
  const fromVideos = useAction(() => api.learnStyleFromVideos(), "Style appris depuis tes vidéos.");
  const toggle = useAction((enabled: boolean) => api.toggleStyle(enabled), "Réglage enregistré.");
  const s = style.data;

  return (
    <>
      <PageHeader title="Mon style" subtitle="Tes scripts sont écrits avec ton ton, tes expressions et ta façon de raconter." />
      <div className="space-y-6">
        {s && (
          <Card title="Ton style" actions={<label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={s.enabled} onChange={(e) => toggle.mutate(e.target.checked)} /> Utiliser pour les scripts
          </label>}>
            <p className="text-sm">{s.summary}</p>
            <div className="mt-3 grid gap-2 text-sm text-zinc-400 md:grid-cols-2">
              {s.tone && <p><span className="text-zinc-500">Ton :</span> {s.tone}</p>}
              {s.sentence_length && <p><span className="text-zinc-500">Phrases :</span> {s.sentence_length}</p>}
              {s.hooks && <p><span className="text-zinc-500">Accroches :</span> {s.hooks}</p>}
              {s.avoid && <p><span className="text-zinc-500">À éviter :</span> {s.avoid}</p>}
            </div>
            <div className="mt-3 flex flex-wrap gap-1">{(s.expressions ?? []).map((e) => <Badge key={e}>{e}</Badge>)}</div>
            <p className="mt-3 text-xs text-zinc-500">Appris depuis {s.samples} texte(s) ({s.source}), le {dateTime(s.updated_at)}.</p>
          </Card>
        )}
        <Card title="Apprendre mon style">
          <Field label="Colle 2 à 30 de tes scripts ou transcriptions, séparés par une ligne ---">
            <textarea className={inputClass} rows={10} value={texts} onChange={(e) => setTexts(e.target.value)} placeholder={"Premier script…\n---\nDeuxième script…"} />
          </Field>
          <div className="mt-3 flex flex-wrap gap-2">
            <Button variant="primary" disabled={texts.trim().length < 40} busy={learn.isPending} onClick={() => learn.mutate(undefined)}>Apprendre depuis ces textes</Button>
            <Button busy={fromVideos.isPending} onClick={() => fromVideos.mutate(undefined)}>Apprendre depuis mes vidéos importées</Button>
          </div>
          <div className="mt-3"><Alert tone="blue">Tout reste sur ton ordinateur : l'analyse est faite par ton modèle Ollama.</Alert></div>
        </Card>
      </div>
    </>
  );
}
