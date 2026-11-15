// File de production : etapes en cours ou en attente sur tous les projets, et travaux des moteurs video.
import { useQueries, useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { keys } from "../api/hooks";
import { currentStep } from "../components/Pipeline";
import { Badge, Card, Empty, PageHeader, StatusBadge } from "../components/ui";
import { JOB_STATUS_LABELS, OPERATION_LABELS, dateTime, usd } from "../lib/format";
import { useProjectStore } from "../stores/project";

const JOB_TONES: Record<string, "zinc" | "blue" | "green" | "red"> = { pending: "zinc", queued: "zinc", running: "blue", succeeded: "green", failed: "red" };

export default function Queue() {
  const projects = useQuery({ queryKey: keys.projects, queryFn: api.projects, refetchInterval: 5000 });
  const details = useQueries({
    queries: (projects.data ?? [])
      .filter((p) => p.status !== "done" && p.status !== "cancelled")
      .map((p) => ({ queryKey: keys.project(p.id), queryFn: () => api.project(p.id), refetchInterval: 3000 })),
  });
  const jobs = useQuery({ queryKey: ["jobs"], queryFn: () => api.jobs(), refetchInterval: 3000 });
  const providers = useQuery({ queryKey: ["providers"], queryFn: api.providers });
  const setCurrent = useProjectStore((s) => s.setCurrent);
  const names = Object.fromEntries((providers.data ?? []).map((p) => [p.id, p.name]));
  const titles = Object.fromEntries((projects.data ?? []).map((p) => [p.id, p.title]));

  const active = details.map((d) => d.data).filter((d) => d !== undefined)
    .map((project) => ({ project, step: currentStep(project) }))
    .sort((a, b) => order(a.step?.status) - order(b.step?.status));

  return (
    <>
      <PageHeader title="File de production" subtitle="Ce qui tourne, ce qui attend ta décision et l'historique des générations vidéo." />
      <div className="space-y-6">
        <Card title="Projets en cours">
          {active.length ? (
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-zinc-500">
                <tr><th className="pb-2">Projet</th><th className="pb-2">Étape</th><th className="pb-2">Statut</th><th className="pb-2">Avancement</th></tr>
              </thead>
              <tbody className="divide-y divide-zinc-800">
                {active.map(({ project, step }) => {
                  const done = project.steps.filter((s) => s.status === "done").length;
                  return (
                    <tr key={project.id}>
                      <td className="py-2"><button type="button" className="hover:text-violet-300" onClick={() => setCurrent(project.id)}>{project.title}</button></td>
                      <td className="py-2">{step?.label ?? "—"}{step?.error && <span className="block text-xs text-red-300">{step.error}</span>}</td>
                      <td className="py-2">{step && <StatusBadge status={step.status} />}</td>
                      <td className="py-2 text-zinc-400">{done} / {project.steps.length}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          ) : (
            <Empty>Aucun projet en production.</Empty>
          )}
        </Card>

        <Card title="Générations vidéo">
          {jobs.data?.length ? (
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-zinc-500">
                <tr><th className="pb-2">Date</th><th className="pb-2">Projet</th><th className="pb-2">Moteur</th><th className="pb-2">Opération</th><th className="pb-2">Coût estimé</th><th className="pb-2">Statut</th></tr>
              </thead>
              <tbody className="divide-y divide-zinc-800">
                {jobs.data.map((job) => (
                  <tr key={job.id}>
                    <td className="py-2 text-zinc-400">{dateTime(job.created_at)}</td>
                    <td className="py-2">{titles[job.project_id] ?? "—"}</td>
                    <td className="py-2">{names[job.provider_id] ?? job.provider_id}</td>
                    <td className="py-2 text-zinc-400">{OPERATION_LABELS[job.operation] ?? job.operation}</td>
                    <td className="py-2">{usd(job.estimated_cost_usd)}</td>
                    <td className="py-2">
                      <Badge tone={JOB_TONES[job.status] ?? "zinc"}>{JOB_STATUS_LABELS[job.status] ?? job.status}</Badge>
                      {job.error && <span className="block text-xs text-red-300">{job.error}</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <Empty>Aucune génération vidéo pour l'instant.</Empty>
          )}
        </Card>
      </div>
    </>
  );
}

function order(status: string | undefined): number {
  return ["running", "needs_validation", "failed", "pending", "cancelled"].indexOf(status ?? "pending");
}
