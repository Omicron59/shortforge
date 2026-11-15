// Editeur de script : hook, corps, conclusion, appel a l'action et scenes ; versions et validation.
import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { useAction } from "../api/hooks";
import type { ProjectDetail, SceneEdit, ScriptDetail } from "../api/types";
import { WithProject } from "../components/Layout";
import { NextAction, stepOf } from "../components/Pipeline";
import { Alert, Badge, Button, Card, Empty, Field, Loading, PageHeader, inputClass } from "../components/ui";
import { IMPORTANCE_LABELS, TRANSITION_LABELS, seconds, spokenDuration } from "../lib/format";

export default function ScriptEditor() {
  return (
    <>
      <PageHeader title="Éditeur de script" subtitle="Modifie le texte et les scènes avant de valider : une fois validé, le script est verrouillé." />
      <WithProject>{(project) => <ScriptBody project={project} />}</WithProject>
    </>
  );
}

type Draft = { hook: string; body: string; conclusion: string; call_to_action: string; scenes: SceneEdit[] };

function toDraft(detail: ScriptDetail): Draft {
  const { script, scenes } = detail;
  return {
    hook: script.hook,
    body: script.body,
    conclusion: script.conclusion,
    call_to_action: script.call_to_action,
    scenes: scenes.map((s) => ({ text: s.text, visual_prompt: s.visual_prompt, negative_prompt: s.negative_prompt, transition: s.transition, duration_s: s.duration_s, importance: s.importance })),
  };
}

function ScriptBody({ project }: { project: ProjectDetail }) {
  const write = stepOf(project, "write_script");
  const approveStep = stepOf(project, "approve_script");
  const detail = useQuery({ queryKey: ["script", project.id], queryFn: () => api.script(project.id), enabled: write?.status === "done", retry: false });
  const [draft, setDraft] = useState<Draft | null>(null);
  const [instructions, setInstructions] = useState("");
  const [target, setTarget] = useState(30);
  const navigate = useNavigate();

  useEffect(() => {
    if (detail.data) setDraft(toDraft(detail.data));
  }, [detail.data]);

  const save = useAction((d: Draft) => api.updateScript(project.id, d), "Script enregistré.");
  const shorten = useAction(() => api.shortenScript(project.id, target), "Script raccourci (nouvelle version).");
  const regenerate = useAction(() => api.regenerateScript(project.id, instructions), "Nouvelle version générée.");

  if (write?.status !== "done") {
    return (
      <div className="space-y-4">
        <NextAction project={project} gateHint="Choisis une idée dans « Niche et idées » avant de valider." />
        <Empty>Le script n'est pas encore écrit.</Empty>
      </div>
    );
  }
  if (detail.isLoading || !draft || !detail.data) return <Loading />;

  const locked = detail.data.script.status === "approved";
  const fullText = [draft.hook, draft.body, draft.conclusion, draft.call_to_action].join(" ");
  const hookDuration = spokenDuration(draft.hook);
  const dirty = JSON.stringify(draft) !== JSON.stringify(toDraft(detail.data));
  const setScene = (i: number, patch: Partial<SceneEdit>) =>
    setDraft({ ...draft, scenes: draft.scenes.map((s, j) => (j === i ? { ...s, ...patch } : s)) });

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <Badge tone="violet">Version {detail.data.script.version}</Badge>
        <Badge tone={locked ? "green" : "yellow"}>{locked ? "Validé (verrouillé)" : "Brouillon"}</Badge>
        <Badge>Durée parlée ≈ {seconds(spokenDuration(fullText))}</Badge>
        <Badge tone={hookDuration < 2 || hookDuration > 5 ? "red" : "green"}>Hook ≈ {seconds(hookDuration)} (2 à 5 s)</Badge>
      </div>

      {detail.data.warnings.length > 0 && <Alert tone="yellow" title="À vérifier">{detail.data.warnings.join("\n")}</Alert>}
      {approveStep?.status !== "done" && !dirty && <NextAction project={project} />}
      {locked && (
        <Alert tone="green">
          Script validé. <button type="button" className="underline" onClick={() => navigate("/scenes")}>Revoir les scènes →</button>
        </Alert>
      )}

      <Card title="Texte">
        <div className="grid gap-4">
          {(["hook", "body", "conclusion", "call_to_action"] as const).map((key) => (
            <Field key={key} label={{ hook: "Hook (accroche)", body: "Corps", conclusion: "Conclusion", call_to_action: "Appel à l'action" }[key]}>
              <textarea
                className={`${inputClass} min-h-[60px]`}
                rows={key === "body" ? 5 : 2}
                disabled={locked}
                value={draft[key]}
                onChange={(e) => setDraft({ ...draft, [key]: e.target.value })}
              />
            </Field>
          ))}
        </div>
      </Card>

      <Card title={`Scènes (${draft.scenes.length})`}>
        <div className="space-y-4">
          {draft.scenes.map((scene, i) => (
            <div key={i} className="rounded-lg border border-zinc-800 p-4">
              <div className="mb-3 flex items-center justify-between">
                <span className="text-sm font-medium">Scène {i + 1}</span>
                {!locked && draft.scenes.length > 1 && (
                  <Button variant="ghost" className="px-2 py-1 text-xs" onClick={() => setDraft({ ...draft, scenes: draft.scenes.filter((_, j) => j !== i) })}>Supprimer</Button>
                )}
              </div>
              <div className="grid gap-3 md:grid-cols-2">
                <Field label="Texte dit pendant la scène">
                  <textarea className={inputClass} rows={2} disabled={locked} value={scene.text} onChange={(e) => setScene(i, { text: e.target.value })} />
                </Field>
                <Field label="Prompt visuel (en anglais de préférence)">
                  <textarea className={inputClass} rows={2} disabled={locked} value={scene.visual_prompt} onChange={(e) => setScene(i, { visual_prompt: e.target.value })} />
                </Field>
                <Field label="Prompt négatif">
                  <input className={inputClass} disabled={locked} value={scene.negative_prompt} onChange={(e) => setScene(i, { negative_prompt: e.target.value })} />
                </Field>
                <div className="grid grid-cols-3 gap-2">
                  <Field label="Durée (s)">
                    <input type="number" min={1} max={30} step={0.5} className={inputClass} disabled={locked} value={scene.duration_s}
                      onChange={(e) => setScene(i, { duration_s: Number(e.target.value) })} />
                  </Field>
                  <Field label="Transition">
                    <select className={inputClass} disabled={locked} value={scene.transition} onChange={(e) => setScene(i, { transition: e.target.value })}>
                      {Object.entries(TRANSITION_LABELS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                    </select>
                  </Field>
                  <Field label="Type">
                    <select className={inputClass} disabled={locked} value={scene.importance} onChange={(e) => setScene(i, { importance: e.target.value as SceneEdit["importance"] })}>
                      {Object.entries(IMPORTANCE_LABELS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                    </select>
                  </Field>
                </div>
              </div>
            </div>
          ))}
          {!locked && (
            <Button onClick={() => setDraft({ ...draft, scenes: [...draft.scenes, { text: "", visual_prompt: "", negative_prompt: "", transition: "cut", duration_s: 3, importance: "simple" }] })}>
              Ajouter une scène
            </Button>
          )}
        </div>
      </Card>

      {!locked && (
        <div className="sticky bottom-0 -mx-2 flex flex-wrap items-end gap-3 rounded-xl border border-zinc-800 bg-zinc-950/95 p-4 backdrop-blur">
          <Button variant="primary" disabled={!dirty || draft.scenes.some((s) => s.visual_prompt.trim().length < 3)} busy={save.isPending} onClick={() => save.mutate(draft)}>
            Enregistrer
          </Button>
          <Button variant="ghost" disabled={!dirty} onClick={() => setDraft(toDraft(detail.data))}>Annuler les modifications</Button>
          <div className="ml-auto flex items-end gap-2">
            <Field label="Raccourcir à (s)">
              <input type="number" min={5} max={180} className={`${inputClass} w-24`} value={target} onChange={(e) => setTarget(Number(e.target.value))} />
            </Field>
            <Button busy={shorten.isPending} onClick={() => shorten.mutate(undefined)}>Raccourcir</Button>
          </div>
          <div className="flex items-end gap-2">
            <Field label="Consignes pour régénérer">
              <input className={`${inputClass} w-64`} value={instructions} onChange={(e) => setInstructions(e.target.value)} placeholder="Ex. : plus drôle, chute inattendue" />
            </Field>
            <Button busy={regenerate.isPending} onClick={() => regenerate.mutate(undefined)}>Régénérer</Button>
          </div>
        </div>
      )}
    </div>
  );
}
