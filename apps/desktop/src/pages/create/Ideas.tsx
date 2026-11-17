// Etape 2 : les idees. Les nouvelles s'ajoutent aux precedentes ; aucun score de viralite n'est affiche.
import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import { wizard, type Engine, type WizardIdea, type WizardState } from "../../api/wizard";
import { Btn, Dialog, Labeled, Notice, Page, Panel, Tag, fieldClass } from "../../components/ds";
import { useToasts } from "../../stores/toasts";
import { EngineNote, Generating, NoModel, StateGate, Stepper, useGeneration, useWizard } from "./shared";

export default function IdeasPage() {
  const { id = "" } = useParams();
  const query = useWizard(id);
  return (
    <Page title="Idées" subtitle="Choisis une idée, retouche-la ou demandes-en d'autres. Rien n'est remplacé : les idées précédentes restent là.">
      <StateGate query={query}>{(state) => <Board id={id} state={state} set={query.set} />}</StateGate>
    </Page>
  );
}

function Board({ id, state, set }: { id: string; state: WizardState; set: (s: WizardState) => void }) {
  const navigate = useNavigate();
  const location = useLocation();
  const push = useToasts((s) => s.push);
  const gen = useGeneration();
  const [used, setUsed] = useState<Engine | null>(null);
  const [fresh, setFresh] = useState<string[]>([]);
  const [rejected, setRejected] = useState<string[]>([]);
  const [editing, setEditing] = useState<WizardIdea | null>(null);
  const engine = state.engines.ideas;
  const locked = state.script_approved;

  const generate = async (variantOf?: WizardIdea) => {
    const result = await gen.run(variantOf ? `Recherche de variantes de « ${variantOf.title} »` : "Recherche de 5 idées", (rid, signal) => wizard.ideas(id, rid, signal, variantOf?.id));
    if (!result) return;
    set(result);
    setUsed(result.used ?? null);
    setFresh(result.new_idea_ids ?? []);
    setRejected(result.rejected ?? []);
  };
  // Arrivee depuis le brief avec « Generer 5 idees » : la demande vient de l'utilisateur, on la lance une fois.
  const auto = useRef((location.state as { generate?: boolean } | null)?.generate === true);
  useEffect(() => {
    if (auto.current && state.ideas.length === 0 && engine?.configured !== false) {
      auto.current = false;
      navigate(location.pathname, { replace: true, state: null });
      void generate();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const choose = useMutation({
    mutationFn: (idea: WizardIdea) => wizard.choose(id, idea.id),
    onSuccess: (next) => { set(next); navigate(`/creer/${id}/script`); },
    onError: (e: Error) => push(e.message, "error"),
  });
  const patch = useMutation({
    mutationFn: ({ idea, body }: { idea: WizardIdea; body: Parameters<typeof wizard.patchIdea>[1] }) => wizard.patchIdea(idea.id, body),
    onSuccess: (updated) => { set({ ...state, ideas: state.ideas.map((i) => (i.id === updated.id ? { ...i, ...updated } : i)) }); setEditing(null); },
    onError: (e: Error) => push(e.message, "error"),
  });
  const manual = useMutation({
    mutationFn: () => wizard.manualScript(id),
    onSuccess: (next) => { set(next); navigate(`/creer/${id}/script`); },
    onError: (e: Error) => push(e.message, "error"),
  });

  const saved = state.ideas.filter((i) => i.saved);
  const others = state.ideas.filter((i) => !i.saved);
  const card = (idea: WizardIdea) => (
    <IdeaCard key={idea.id} idea={idea} isNew={fresh.includes(idea.id)} selected={idea.id === state.selected_idea_id} locked={locked} busy={!!gen.busy || choose.isPending}
      onChoose={() => choose.mutate(idea)} onEdit={() => setEditing(idea)} onVariant={() => void generate(idea)}
      onSave={() => patch.mutate({ idea, body: { saved: !idea.saved } })} />
  );

  return (
    <>
      <Stepper id={id} state={state} />
      {locked && <Notice tone="warning" title="Script validé">L'idée ne peut plus être changée pour ce projet. Rouvre le script depuis le studio, ou duplique le projet.</Notice>}
      <NoModel engine={engine}><Btn busy={manual.isPending} disabled={locked} onClick={() => manual.mutate()}>Écrire le script moi-même</Btn></NoModel>
      <Generating gen={gen} />
      <div className="flex flex-wrap items-center gap-4">
        <Btn variant={state.ideas.length ? "secondary" : "primary"} disabled={!!gen.busy || engine?.configured === false} onClick={() => void generate()}>
          {state.ideas.length ? "Générer 5 nouvelles idées" : "Générer 5 idées"}
        </Btn>
        <EngineNote engine={engine} used={used} />
      </div>
      {rejected.length > 0 && (
        <Notice tone="neutral" title="Idées écartées automatiquement">
          <ul className="list-disc pl-4">{rejected.map((r) => <li key={r}>{r}</li>)}</ul>
        </Notice>
      )}
      {state.ideas.length === 0 && !gen.busy && (
        <Panel>
          <p className="text-sm text-sf-muted">Aucune idée pour l'instant. Lance une génération à partir de ton brief, ou écris directement ton script si tu sais déjà ce que tu veux dire.</p>
          {engine?.configured !== false && <Btn className="mt-3" busy={manual.isPending} onClick={() => manual.mutate()}>Écrire le script moi-même</Btn>}
        </Panel>
      )}
      {saved.length > 0 && <section aria-label="Idées gardées pour plus tard"><h2 className="mb-3 text-sm text-sf-muted">Gardées pour plus tard</h2><ul className="grid gap-4 lg:grid-cols-2">{saved.map(card)}</ul></section>}
      {others.length > 0 && <ul className="grid gap-4 lg:grid-cols-2">{others.map(card)}</ul>}
      {state.ideas.length > 0 && <p className="text-xs text-sf-muted">ShortForge n'affiche pas de score de viralité : personne ne peut prédire les vues d'une vidéo. « Difficulté » et « ressources » sont des estimations du modèle.</p>}
      {editing && <EditIdea idea={editing} busy={patch.isPending} onClose={() => setEditing(null)} onSave={(body) => patch.mutate({ idea: editing, body })} />}
    </>
  );
}

function IdeaCard({ idea, isNew, selected, locked, busy, onChoose, onEdit, onVariant, onSave }: {
  idea: WizardIdea; isNew: boolean; selected: boolean; locked: boolean; busy: boolean;
  onChoose: () => void; onEdit: () => void; onVariant: () => void; onSave: () => void;
}) {
  return (
    <li className={`flex flex-col gap-3 rounded-sf border bg-sf-surface p-5 shadow-sf transition duration-sf ${selected ? "border-sf-primary" : "border-sf-border"}`}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <h3 className="text-base font-medium">{idea.title}</h3>
        <div className="flex flex-wrap gap-1.5">
          {selected && <Tag tone="primary">Idée choisie</Tag>}
          {isNew && <Tag tone="success">Nouvelle</Tag>}
          {idea.parent_id && <Tag>Variante</Tag>}
        </div>
      </div>
      <dl className="space-y-2 text-sm">
        {idea.hook && <Row term="Hook">« {idea.hook} »</Row>}
        {idea.original_angle && <Row term="Angle">{idea.original_angle}</Row>}
        {idea.summary && <Row term="Résumé">{idea.summary}</Row>}
        {idea.fit_reason && <Row term="Pourquoi elle répond au brief">{idea.fit_reason}</Row>}
        {idea.resources.length > 0 && <Row term="Ressources nécessaires">{idea.resources.join(" · ")}</Row>}
      </dl>
      <div className="flex flex-wrap gap-1.5">
        {idea.estimated_duration_s > 0 && <Tag>Durée visée : {Math.round(idea.estimated_duration_s)} s</Tag>}
        {idea.difficulty && <Tag>Production : {idea.difficulty}</Tag>}
      </div>
      <div className="mt-auto flex flex-wrap gap-2 pt-1">
        <Btn variant="accent" disabled={busy || locked} onClick={onChoose}>{selected ? "Continuer avec cette idée" : "Choisir"}</Btn>
        <Btn variant="ghost" onClick={onEdit}>Modifier</Btn>
        <Btn variant="ghost" disabled={busy} onClick={onVariant}>Variante</Btn>
        <Btn variant="ghost" aria-pressed={idea.saved} onClick={onSave}>{idea.saved ? "Ne plus garder" : "Garder pour plus tard"}</Btn>
      </div>
    </li>
  );
}

function Row({ term, children }: { term: string; children: React.ReactNode }) {
  return <div><dt className="text-xs text-sf-muted">{term}</dt><dd>{children}</dd></div>;
}

function EditIdea({ idea, busy, onClose, onSave }: { idea: WizardIdea; busy: boolean; onClose: () => void; onSave: (body: { title: string; hook: string; original_angle: string; summary: string }) => void }) {
  const [form, setForm] = useState({ title: idea.title, hook: idea.hook, original_angle: idea.original_angle, summary: idea.summary });
  const field = (key: keyof typeof form, label: string, rows = 2) => (
    <Labeled label={label}>
      {(fid) => <textarea id={fid} rows={rows} className={`${fieldClass} py-2`} value={form[key]} onChange={(e) => setForm({ ...form, [key]: e.target.value })} />}
    </Labeled>
  );
  return (
    <Dialog title="Modifier l'idée" onClose={onClose}
      footer={<><Btn variant="ghost" onClick={onClose}>Annuler</Btn><Btn variant="primary" busy={busy} disabled={form.title.trim().length < 3} onClick={() => onSave(form)}>Enregistrer</Btn></>}>
      {field("title", "Titre", 1)}
      {field("hook", "Hook")}
      {field("original_angle", "Angle")}
      {field("summary", "Résumé", 3)}
    </Dialog>
  );
}
