// Planning de la semaine : un lot d'idees, tu en choisis, chaque Short avance seul jusqu'a ta validation.
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { useAction } from "../api/hooks";
import type { PoolIdea, Slots, VideoMode } from "../api/types";
import { Alert, Badge, Button, Card, Field, PageHeader, inputClass } from "../components/ui";
import { LANGUAGES, REUSE_RISK_LABELS, VIDEO_MODE_LABELS, dateTime } from "../lib/format";

const DAYS = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"];

export default function Planning() {
  const navigate = useNavigate();
  const [niche, setNiche] = useState("");
  const [language, setLanguage] = useState("fr");
  const [mode, setMode] = useState<VideoMode>("economique");
  const [count, setCount] = useState(7);
  const [pool, setPool] = useState<{ pool_id: string; dates: string[]; ideas: PoolIdea[]; warnings: string[] } | null>(null);
  const [chosen, setChosen] = useState<string[]>([]);
  const generate = useAction(async () => {
    const result = await api.planningPool({ niche, language, video_mode: mode, count });
    setPool(result);
    setChosen(result.ideas.slice(0, count).map((i) => i.id));
    return result;
  });
  const create = useAction(() => api.planningWeek({ pool_id: pool!.pool_id, idea_ids: chosen }),
    "Shorts créés : ils avancent seuls jusqu'à ta prochaine validation.");

  return (
    <>
      <PageHeader title="Planning de la semaine" subtitle="Prépare plusieurs Shorts d'un coup. Chacun s'arrête à chaque validation : rien ne part sans toi." />
      <div className="space-y-6">
        <Card title="1. Idées de la semaine">
          <div className="grid gap-4 md:grid-cols-4">
            <Field label="Niche"><input className={inputClass} value={niche} onChange={(e) => setNiche(e.target.value)} placeholder="Ex. : cuisine rapide" /></Field>
            <Field label="Langue">
              <select className={inputClass} value={language} onChange={(e) => setLanguage(e.target.value)}>
                {Object.entries(LANGUAGES).map(([c, l]) => <option key={c} value={c}>{l}</option>)}
              </select>
            </Field>
            <Field label="Mode vidéo">
              <select className={inputClass} value={mode} onChange={(e) => setMode(e.target.value as VideoMode)}>
                {Object.entries(VIDEO_MODE_LABELS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
            </Field>
            <Field label="Nombre de Shorts"><input type="number" min={1} max={21} className={inputClass} value={count} onChange={(e) => setCount(Number(e.target.value))} /></Field>
          </div>
          <Button className="mt-4" variant="primary" busy={generate.isPending} onClick={() => generate.mutate(undefined)}>Proposer des idées</Button>
        </Card>

        {pool && (
          <Card title={`2. Choisis tes idées (${chosen.length} sélectionnée${chosen.length > 1 ? "s" : ""})`}>
            {pool.warnings.length > 0 && <Alert tone="yellow">{pool.warnings.join("\n")}</Alert>}
            <ul className="mt-3 space-y-2">
              {pool.ideas.map((idea) => (
                <li key={idea.id} className="flex items-start gap-3 rounded-lg border border-zinc-800 p-3">
                  <input type="checkbox" className="mt-1" checked={chosen.includes(idea.id)}
                    onChange={(e) => setChosen(e.target.checked ? [...chosen, idea.id] : chosen.filter((c) => c !== idea.id))} />
                  <div className="flex-1">
                    <p className="font-medium">{idea.title} <span className="text-sm text-violet-300">{Math.round(idea.potential_score)}/100</span></p>
                    <p className="text-sm text-zinc-400">« {idea.hook} » · {idea.original_angle}</p>
                  </div>
                  <Badge tone={idea.reuse_risk === "low" ? "green" : idea.reuse_risk === "medium" ? "yellow" : "red"}>{REUSE_RISK_LABELS[idea.reuse_risk]}</Badge>
                </li>
              ))}
            </ul>
            <p className="mt-3 text-sm text-zinc-400">Dates prévues : {pool.dates.slice(0, chosen.length).map((d) => dateTime(d)).join(" · ")}</p>
            <div className="mt-3 flex gap-2">
              <Button variant="primary" disabled={!chosen.length} busy={create.isPending}
                onClick={() => create.mutate(undefined, { onSuccess: () => navigate("/a-valider") })}>
                Préparer ces {chosen.length} Shorts
              </Button>
            </div>
          </Card>
        )}
        <SlotsCard />
      </div>
    </>
  );
}

function SlotsCard() {
  const slots = useQuery({ queryKey: ["slots"], queryFn: api.slots });
  const save = useAction((body: Partial<Slots>) => api.setSlots(body), "Créneaux enregistrés.");
  const s = slots.data;
  if (!s) return null;
  return (
    <Card title="Créneaux de publication (heure de ton ordinateur)">
      <div className="grid gap-4 md:grid-cols-4">
        {(["youtube", "tiktok", "instagram"] as const).map((p) => (
          <Field key={p} label={{ youtube: "YouTube Shorts", tiktok: "TikTok", instagram: "Instagram Reels" }[p]}>
            <input type="time" className={inputClass} defaultValue={s[p]} onBlur={(e) => save.mutate({ [p]: e.target.value })} />
          </Field>
        ))}
        <Field label="Shorts par jour">
          <input type="number" min={1} max={5} className={inputClass} defaultValue={s.per_day} onBlur={(e) => save.mutate({ per_day: Number(e.target.value) })} />
        </Field>
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        {DAYS.map((d, i) => (
          <button key={d} type="button" onClick={() => save.mutate({ days: s.days.includes(i) ? s.days.filter((x) => x !== i) : [...s.days, i].sort() })}
            className={`rounded-full px-3 py-1 text-sm ${s.days.includes(i) ? "bg-violet-600 text-white" : "bg-zinc-800 text-zinc-400"}`}>
            {d}
          </button>
        ))}
      </div>
    </Card>
  );
}
