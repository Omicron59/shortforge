// Statistiques de production : projets, scenes, generations et depenses par moteur et par mois.
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { useState } from "react";
import { useAction } from "../api/hooks";
import { keys } from "../api/hooks";
import { Alert, Button, Card, Empty, Field, Loading, Meter, PageHeader, Stat, inputClass } from "../components/ui";
import { JOB_STATUS_LABELS, PROJECT_STATUS_LABELS, usd } from "../lib/format";

function Bars({ data, format = String }: { data: Record<string, number>; format?: (v: number) => string }) {
  const entries = Object.entries(data).sort((a, b) => b[1] - a[1]);
  const max = Math.max(0, ...entries.map(([, v]) => v));
  if (!entries.length) return <p className="text-sm text-zinc-500">Pas encore de données.</p>;
  return (
    <ul className="space-y-3">
      {entries.map(([label, value]) => (
        <li key={label} className="text-sm">
          <div className="mb-1 flex justify-between"><span>{label}</span><span className="text-zinc-400">{format(value)}</span></div>
          <Meter value={value} max={max} />
        </li>
      ))}
    </ul>
  );
}

export default function Stats() {
  const stats = useQuery({ queryKey: ["stats"], queryFn: api.stats });
  const providers = useQuery({ queryKey: ["providers"], queryFn: api.providers });
  const names = Object.fromEntries((providers.data ?? []).map((p) => [p.id, p.name]));
  const rename = (data: Record<string, number>, labels: Record<string, string>) =>
    Object.fromEntries(Object.entries(data).map(([k, v]) => [labels[k] ?? k, v]));

  if (stats.isLoading) return <Loading />;
  const s = stats.data;
  if (!s) return <Empty>Statistiques indisponibles.</Empty>;
  const jobsTotal = Object.values(s.jobs_by_status).reduce((a, b) => a + b, 0);
  const success = jobsTotal ? Math.round(((s.jobs_by_status.succeeded ?? 0) / jobsTotal) * 100) : null;

  return (
    <>
      <PageHeader title="Statistiques" subtitle="Ta production en chiffres." />
      <div className="grid gap-4 md:grid-cols-3 lg:grid-cols-6">
        <Stat label="Projets" value={s.projects_total} />
        <Stat label="Idées" value={s.ideas_total} />
        <Stat label="Scènes" value={s.scenes_total} />
        <Stat label="Images" value={s.images_total} />
        <Stat label="Clips vidéo" value={s.videos_total} />
        <Stat label="Dépensé" value={usd(s.spent_total_usd)} hint={success !== null ? `${success} % de générations réussies` : undefined} />
      </div>
      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <Card title="Dépenses par moteur"><Bars data={rename(s.spent_by_provider, names)} format={usd} /></Card>
        <Card title="Dépenses par mois"><Bars data={s.spent_by_month} format={usd} /></Card>
        <Card title="Scènes par moteur"><Bars data={rename(s.scenes_by_provider, names)} /></Card>
        <Card title="Projets par statut"><Bars data={rename(s.projects_by_status, PROJECT_STATUS_LABELS)} /></Card>
        <Card title="Générations vidéo par statut"><Bars data={rename(s.jobs_by_status, JOB_STATUS_LABELS)} /></Card>
      </div>
      <Results />
    </>
  );
}

/** Resultats des Shorts publies (YouTube automatique, TikTok et Instagram a la main) et lecons pour la suite. */
function Results() {
  const perf = useQuery({ queryKey: ["performance"], queryFn: api.performance });
  const projects = useQuery({ queryKey: keys.projects, queryFn: api.projects });
  const refresh = useAction(() => api.refreshStats(), "Chiffres YouTube mis à jour.");
  const learn = useAction(() => api.insights(), "Leçons mises à jour : elles guideront les prochaines idées.");
  const [form, setForm] = useState({ project_id: "", platform: "tiktok", views: "", likes: "", comments: "" });
  const add = useAction(() => api.addStats({ project_id: form.project_id, platform: form.platform, views: Number(form.views),
    likes: Number(form.likes || 0), comments: Number(form.comments || 0) }), "Résultat ajouté.");
  const insights = perf.data?.insights;

  return (
    <div className="mt-6 grid gap-6 lg:grid-cols-2">
      <Card title="Résultats de tes Shorts" actions={<Button className="text-xs" busy={refresh.isPending} onClick={() => refresh.mutate(undefined)}>Actualiser YouTube</Button>}>
        {perf.data?.rows.length ? (
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-zinc-500"><tr><th className="pb-2">Short</th><th>Plateforme</th><th className="text-right">Vues</th><th className="text-right">J'aime</th></tr></thead>
            <tbody className="divide-y divide-zinc-800">
              {perf.data.rows.map((r, i) => (
                <tr key={i}><td className="py-1.5">{r.title}</td><td>{r.platform}</td><td className="text-right">{r.views.toLocaleString("fr-FR")}</td><td className="text-right">{r.likes.toLocaleString("fr-FR")}</td></tr>
              ))}
            </tbody>
          </table>
        ) : <p className="text-sm text-zinc-500">Pas encore de résultats. YouTube se met à jour tout seul (clé YOUTUBE_API_KEY) ; pour TikTok et Instagram, ajoute les chiffres ci-dessous.</p>}
        <div className="mt-4 grid grid-cols-2 gap-2 md:grid-cols-5">
          <select className={`${inputClass} md:col-span-2`} value={form.project_id} onChange={(e) => setForm({ ...form, project_id: e.target.value })}>
            <option value="">Choisis un Short</option>
            {projects.data?.map((p) => <option key={p.id} value={p.id}>{p.title}</option>)}
          </select>
          <select className={inputClass} value={form.platform} onChange={(e) => setForm({ ...form, platform: e.target.value })}>
            <option value="tiktok">TikTok</option><option value="instagram">Instagram</option><option value="youtube">YouTube</option>
          </select>
          <input className={inputClass} inputMode="numeric" placeholder="Vues" value={form.views} onChange={(e) => setForm({ ...form, views: e.target.value })} />
          <input className={inputClass} inputMode="numeric" placeholder="J'aime" value={form.likes} onChange={(e) => setForm({ ...form, likes: e.target.value })} />
        </div>
        <Button className="mt-2" disabled={!form.project_id || !form.views} onClick={() => add.mutate(undefined)}>Ajouter ce résultat</Button>
      </Card>

      <Card title="Ce qui marche" actions={<Button className="text-xs" variant="primary" busy={learn.isPending} onClick={() => learn.mutate(undefined)}>Analyser mes résultats</Button>}>
        {insights ? (
          <div className="space-y-3 text-sm">
            <p>{insights.summary}</p>
            <Field label="À refaire"><ul className="list-inside list-disc text-zinc-300">{insights.what_works.map((x) => <li key={x}>{x}</li>)}</ul></Field>
            <Field label="À éviter"><ul className="list-inside list-disc text-zinc-300">{insights.avoid.map((x) => <li key={x}>{x}</li>)}</ul></Field>
            <Field label="Pistes pour la semaine prochaine"><ul className="list-inside list-disc text-zinc-300">{insights.next_week.map((x) => <li key={x}>{x}</li>)}</ul></Field>
            <p className="text-xs text-zinc-500">Basé sur {insights.based_on} Shorts. Ces leçons sont ajoutées aux consignes des prochaines idées.</p>
          </div>
        ) : <Alert tone="blue">Il faut les résultats d'au moins 3 Shorts pour en tirer des leçons.</Alert>}
      </Card>
    </div>
  );
}
