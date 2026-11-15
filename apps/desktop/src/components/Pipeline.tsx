// Suivi et pilotage du pipeline d'un projet : etape suivante, validations, confirmations de cout.
import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useAction } from "../api/hooks";
import type { ProjectDetail, Step } from "../api/types";
import { dateTime } from "../lib/format";
import { Alert, Button, Card, StatusBadge } from "./ui";

/** Validations faites dans l'ecran Apercu (video regardee, verification finale). */
const PREVIEW_GATES = ["review_preview", "approve_final_render", "publish"];

/** Etape a traiter maintenant : la premiere qui n'est pas terminee. */
export function currentStep(project: ProjectDetail): Step | undefined {
  return project.steps.find((s) => s.status !== "done");
}

export function stepOf(project: ProjectDetail, name: string): Step | undefined {
  return project.steps.find((s) => s.name === name);
}

/** Barre d'action : ce qu'il faut faire maintenant, avec le bon bouton. */
export function NextAction({ project, gateHint }: { project: ProjectDetail; gateHint?: string }) {
  const step = currentStep(project);
  const advance = useAction(() => api.advance(project.id), "Étape lancée.");
  const approve = useAction(({ name, confirm }: { name: string; confirm: boolean }) => api.approve(project.id, name, confirm),
    "Validation enregistrée.");
  const reject = useAction((name: string) => api.reject(project.id, name), "Refus enregistré.");
  const resume = useAction(() => api.resume(project.id), "Projet repris.");

  if (!step) return <Alert tone="green">Toutes les étapes sont terminées.</Alert>;

  if (step.status === "cancelled") {
    return (
      <Alert tone="yellow" title="Projet annulé">
        <div className="mt-2"><Button variant="primary" busy={resume.isPending} onClick={() => resume.mutate(undefined)}>Reprendre le projet</Button></div>
      </Alert>
    );
  }

  if (step.status === "running") {
    return <Alert tone="blue" title={`${step.label} en cours…`}>La progression se met à jour toute seule.</Alert>;
  }

  if (step.status === "needs_validation") {
    const items = step.output?.confirmation_required;
    if (items?.length) return <CostConfirmation project={project} step={step} />;
    if (PREVIEW_GATES.includes(step.name)) {
      return (
        <Alert tone="yellow" title={`${step.label} : ta validation est nécessaire`}>
          Cette validation se fait dans l'écran Aperçu, après avoir regardé la vidéo.{" "}
          <Link to="/apercu" className="underline">Ouvrir l'aperçu →</Link>
        </Alert>
      );
    }
    return (
      <Alert tone="yellow" title={`${step.label} : ta validation est nécessaire`}>
        {gateHint && <p className="mb-2">{gateHint}</p>}
        <div className="mt-2 flex gap-2">
          <Button variant="primary" busy={approve.isPending} onClick={() => approve.mutate({ name: step.name, confirm: false })}>
            Valider
          </Button>
          <Button variant="danger" busy={reject.isPending} onClick={() => reject.mutate(step.name)}>Refuser et refaire</Button>
        </div>
      </Alert>
    );
  }

  return (
    <div className="flex flex-wrap items-center gap-3 rounded-lg border border-zinc-800 bg-zinc-900/60 px-4 py-3">
      <div className="flex-1 text-sm">
        <span className="text-zinc-400">Prochaine étape : </span>
        <span className="font-medium">{step.label}</span>
        {step.status === "failed" && <p className="mt-1 text-red-300">Dernier essai en échec : {step.error}</p>}
        {step.status === "pending" && step.error && <p className="mt-1 text-amber-300">{step.error}</p>}
      </div>
      <Button variant="primary" busy={advance.isPending} onClick={() => advance.mutate(undefined)}>
        {step.status === "failed" ? "Réessayer" : step.human_gate ? "Passer à la validation" : "Lancer"}
      </Button>
    </div>
  );
}

/** Message de cout exact du backend, a confirmer explicitement avant toute depense. */
function CostConfirmation({ project, step }: { project: ProjectDetail; step: Step }) {
  const [checked, setChecked] = useState(false);
  const approve = useAction(() => api.approve(project.id, step.name, true), "Dépense confirmée : relance l'étape.");
  const reject = useAction(() => api.reject(project.id, step.name, "Dépense refusée"), "Dépense refusée.");
  const items = step.output?.confirmation_required ?? [];
  const total = items.reduce((sum, i) => sum + (i.estimated_cost_usd ?? 0), 0);
  const unknown = items.some((i) => i.estimated_cost_usd === null);

  return (
    <Alert tone="yellow" title="Dépense à confirmer">
      <ul className="mb-3 space-y-2">
        {items.map((item) => (
          <li key={item.scene_id} className="rounded bg-black/30 p-2">
            <span className="text-xs text-amber-400">Scène {item.position + 1}</span>
            <p>{item.message}</p>
          </li>
        ))}
      </ul>
      {unknown ? (
        <p className="mb-2 text-red-300">Un tarif est inconnu : renseigne-le dans Paramètres → Moteurs vidéo, ou passe la scène en local.</p>
      ) : (
        <label className="mb-2 flex items-center gap-2">
          <input type="checkbox" checked={checked} onChange={(e) => setChecked(e.target.checked)} />
          Je confirme cette dépense de {total.toFixed(2).replace(".", ",")} $.
        </label>
      )}
      <div className="flex gap-2">
        <Button variant="primary" disabled={!checked || unknown} busy={approve.isPending} onClick={() => approve.mutate(undefined)}>
          Confirmer la génération
        </Button>
        <Button variant="danger" busy={reject.isPending} onClick={() => reject.mutate(undefined)}>Refuser la dépense</Button>
      </div>
    </Alert>
  );
}

/** Liste des 15 etapes avec statut, dates et bouton « refaire ». */
export function PipelineTimeline({ project }: { project: ProjectDetail }) {
  const redo = useAction((name: string) => api.redo(project.id, name), "L'étape sera refaite.");
  return (
    <Card title="Étapes du pipeline">
      <ol className="space-y-1">
        {project.steps.map((step) => (
          <li key={step.name} className="flex items-center gap-3 rounded-lg px-2 py-1.5 text-sm hover:bg-zinc-800/50">
            <span className="w-6 text-right text-xs text-zinc-500">{step.position + 1}</span>
            <span className="flex-1">
              {step.label}
              {step.human_gate && <span className="ml-2 text-xs text-zinc-500">(validation humaine)</span>}
              {step.error && step.status !== "done" && <span className="block text-xs text-red-300">{step.error}</span>}
            </span>
            <span className="hidden text-xs text-zinc-500 md:inline">{dateTime(step.finished_at ?? step.started_at)}</span>
            <StatusBadge status={step.status} />
            {(step.status === "done" || step.status === "failed") && step.name !== "publish" && (
              <Button variant="ghost" className="px-2 py-1 text-xs" onClick={() => redo.mutate(step.name)}>Refaire</Button>
            )}
          </li>
        ))}
      </ol>
    </Card>
  );
}
