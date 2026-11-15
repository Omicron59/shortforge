// Statistiques de production : projets, scenes, generations et depenses par moteur et par mois.
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { Alert, Card, Empty, Loading, Meter, PageHeader, Stat } from "../components/ui";
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
        <Card title="YouTube"><Alert tone="blue">{s.youtube.message}</Alert></Card>
      </div>
    </>
  );
}
