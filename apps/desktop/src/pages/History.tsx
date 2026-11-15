// Historique : journal des etapes, validations, echecs et depenses de tous les projets.
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { keys } from "../api/hooks";
import { Badge, Card, Empty, Loading, PageHeader, inputClass, type Tone } from "../components/ui";
import { dateTime, usd } from "../lib/format";

const TYPES: Record<string, { label: string; tone: Tone }> = {
  step_done: { label: "Terminé", tone: "green" },
  step_failed: { label: "Échec", tone: "red" },
  step_running: { label: "En cours", tone: "blue" },
  step_needs_validation: { label: "À valider", tone: "yellow" },
  step_pending: { label: "Remis en attente", tone: "zinc" },
  step_cancelled: { label: "Annulé", tone: "zinc" },
  cost_actual: { label: "Dépense", tone: "violet" },
  cost_confirmation: { label: "Confirmation", tone: "yellow" },
};

export default function History() {
  const [projectId, setProjectId] = useState("");
  const [filter, setFilter] = useState<"all" | "steps" | "costs" | "failures">("all");
  const projects = useQuery({ queryKey: keys.projects, queryFn: api.projects });
  const history = useQuery({ queryKey: ["history", projectId], queryFn: () => api.history(projectId || undefined) });

  const events = (history.data ?? []).filter((e) =>
    filter === "all" ? true : filter === "steps" ? e.type.startsWith("step_") : filter === "costs" ? e.type.startsWith("cost_") : e.type === "step_failed");
  const spent = events.filter((e) => e.type === "cost_actual").reduce((s, e) => s + (e.amount_usd ?? 0), 0);

  return (
    <>
      <PageHeader title="Historique" subtitle="Tout ce qui s'est passé, du plus récent au plus ancien." />
      <div className="mb-4 flex flex-wrap gap-3">
        <select className={`${inputClass} w-64`} value={projectId} onChange={(e) => setProjectId(e.target.value)} aria-label="Projet">
          <option value="">Tous les projets</option>
          {projects.data?.map((p) => <option key={p.id} value={p.id}>{p.title}</option>)}
        </select>
        <select className={`${inputClass} w-52`} value={filter} onChange={(e) => setFilter(e.target.value as typeof filter)} aria-label="Filtre">
          <option value="all">Tous les événements</option>
          <option value="steps">Étapes</option>
          <option value="costs">Dépenses</option>
          <option value="failures">Échecs</option>
        </select>
        <span className="self-center text-sm text-zinc-400">Dépensé sur la sélection : {usd(spent)}</span>
      </div>
      <Card>
        {history.isLoading ? (
          <Loading />
        ) : events.length ? (
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-zinc-500">
              <tr><th className="pb-2">Date</th><th className="pb-2">Projet</th><th className="pb-2">Événement</th><th className="pb-2">Type</th><th className="pb-2">Détail</th><th className="pb-2 text-right">Montant</th></tr>
            </thead>
            <tbody className="divide-y divide-zinc-800">
              {events.map((e, i) => (
                <tr key={i}>
                  <td className="whitespace-nowrap py-2 text-zinc-400">{dateTime(e.at)}</td>
                  <td className="py-2">{e.project_title || "—"}</td>
                  <td className="py-2">{e.label}</td>
                  <td className="py-2"><Badge tone={TYPES[e.type]?.tone ?? "zinc"}>{TYPES[e.type]?.label ?? e.type}</Badge></td>
                  <td className="py-2 text-zinc-400">{e.detail}</td>
                  <td className="py-2 text-right">{e.amount_usd !== null ? usd(e.amount_usd) : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <Empty>Rien pour l'instant.</Empty>
        )}
      </Card>
    </>
  );
}
