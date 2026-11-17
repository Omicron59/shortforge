// Etape 3 : script et storyboard, scene par scene. Chaque champ s'enregistre tout seul ;
// une regeneration ciblee ne touche qu'un champ d'une scene.
import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { wizard, type Engine, type SceneField, type ScenePatch, type WizardScene, type WizardState } from "../../api/wizard";
import { Btn, Dialog, Labeled, Notice, Page, Panel, Tag, fieldClass } from "../../components/ds";
import { TRANSITION_LABELS, spokenDuration } from "../../lib/format";
import { useToasts } from "../../stores/toasts";
import { Confirm, EngineNote, Generating, NoModel, SaveBadge, StateGate, Stepper, useAutosave, useGeneration, useWizard, type SaveStatus } from "./shared";

export default function ScriptPage() {
  const { id = "" } = useParams();
  const query = useWizard(id);
  return (
    <Page title="Script et storyboard" subtitle="Relis, corrige et réorganise. Les durées sont des estimations : elles deviendront exactes une fois la voix générée.">
      <StateGate query={query}>{(state) => <Editor id={id} state={state} set={query.set} />}</StateGate>
    </Page>
  );
}

type Ask = { kind: "delete"; scene: WizardScene } | { kind: "regenerate" } | { kind: "restore"; version: number } | null;

function Editor({ id, state, set }: { id: string; state: WizardState; set: (s: WizardState) => void }) {
  const navigate = useNavigate();
  const push = useToasts((s) => s.push);
  const client = useQueryClient();
  const gen = useGeneration();
  const [used, setUsed] = useState<Engine | null>(null);
  const [saves, setSaves] = useState<Record<string, SaveStatus>>({});
  const [ask, setAsk] = useState<Ask>(null);
  const [hooks, setHooks] = useState<string[] | null>(null);
  const [history, setHistory] = useState(false);
  const [tone, setTone] = useState("");
  const [epoch, setEpoch] = useState(0); // change : les editeurs de scene repartent des donnees enregistrees
  const script = state.script;
  const engine = state.engines.script;
  const locked = state.script_approved;
  const onError = (e: Error) => push(e.message, "error");
  const report = useCallback((sceneId: string, status: SaveStatus) => setSaves((all) => (all[sceneId] === status ? all : { ...all, [sceneId]: status })), []);
  const refresh = () => wizard.state(id).then(set);
  const overall: SaveStatus = Object.values(saves).includes("error") ? "error" : Object.values(saves).includes("saving") ? "saving" : Object.values(saves).includes("saved") ? "saved" : "idle";

  const full = async (label: string, call: (rid: string, signal: AbortSignal) => Promise<WizardState>) => {
    const result = await gen.run(label, call);
    if (!result) return;
    set(result);
    setUsed(result.used ?? null);
    setSaves({});
    void client.invalidateQueries({ queryKey: ["wizard", id, "versions"] });
  };
  const manual = useMutation({ mutationFn: () => wizard.manualScript(id), onSuccess: set, onError });
  const structure = useMutation({ mutationFn: (call: () => Promise<WizardState>) => call(), onSuccess: (next) => { set(next); setAsk(null); }, onError });
  const approve = useMutation({
    mutationFn: () => wizard.approve(id),
    onSuccess: (next) => { set(next); if (next.warning) push(next.warning, "error"); navigate(`/creer/${id}/studio`); },
    onError,
  });
  const askHooks = async () => {
    const result = await gen.run("Recherche d'autres accroches", (rid, signal) => wizard.hooks(id, rid, signal));
    if (result) { setHooks(result.hooks); setUsed(result.used); }
  };

  if (!state.selected_idea_id && !script) {
    return (
      <>
        <Stepper id={id} state={state} />
        <Panel>
          <p className="text-sm text-sf-muted">Choisis d'abord une idée, ou écris directement ton script.</p>
          <div className="mt-3 flex flex-wrap gap-2">
            <Btn variant="primary" onClick={() => navigate(`/creer/${id}/idees`)}>Voir les idées</Btn>
            <Btn busy={manual.isPending} onClick={() => manual.mutate()}>Écrire le script moi-même</Btn>
          </div>
        </Panel>
      </>
    );
  }
  if (!script) {
    const idea = state.ideas.find((i) => i.id === state.selected_idea_id);
    return (
      <>
        <Stepper id={id} state={state} />
        <Panel title={idea ? `Idée choisie : ${idea.title}` : "Idée choisie"} hint={idea?.hook ? `« ${idea.hook} »` : undefined}>
          <NoModel engine={engine} />
          <Generating gen={gen} />
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <Btn variant="primary" disabled={!!gen.busy || engine?.configured === false} onClick={() => void full("Écriture du script et du storyboard", (rid, signal) => wizard.generateScript(id, rid, signal))}>Générer le script et le storyboard</Btn>
            <Btn busy={manual.isPending} disabled={!!gen.busy} onClick={() => manual.mutate()}>Écrire moi-même</Btn>
            <EngineNote engine={engine} />
          </div>
        </Panel>
      </>
    );
  }

  const scenes = script.scenes;
  const move = (index: number, delta: number) => {
    const ids = scenes.map((s) => s.id);
    const target = index + delta;
    if (target < 0 || target >= ids.length) return;
    [ids[index], ids[target]] = [ids[target], ids[index]];
    structure.mutate(() => wizard.reorder(id, ids));
  };
  const total = scenes.reduce((sum, s) => sum + spokenDuration(s.text), 0);

  return (
    <>
      <Stepper id={id} state={state} />
      {locked && <Notice tone="warning" title="Script validé">Tu peux encore corriger les textes et les prompts. Pour ajouter, supprimer une scène ou tout régénérer, rouvre le script depuis le studio.</Notice>}
      <Generating gen={gen} />
      <Panel>
        <div className="flex flex-wrap items-center gap-2">
          <Btn disabled={!!gen.busy || locked} onClick={() => void full("Raccourcissement du script", (rid, signal) => wizard.transform(id, rid, signal, { kind: "shorten" }))}>Raccourcir</Btn>
          <label className="sr-only" htmlFor="ton">Changer le ton</label>
          <div className="w-48"><select id="ton" className={fieldClass} value={tone} disabled={!!gen.busy || locked}
            onChange={(e) => { const value = e.target.value; setTone(""); if (value) void full("Réécriture avec un autre ton", (rid, signal) => wizard.transform(id, rid, signal, { kind: "tone", tone: value })); }}>
            <option value="">Changer le ton…</option>
            {TONES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select></div>
          <Btn disabled={!!gen.busy} onClick={() => void askHooks()}>Autre hook</Btn>
          <Btn disabled={!!gen.busy || locked} onClick={() => setAsk({ kind: "regenerate" })}>Tout régénérer</Btn>
          <Btn variant="ghost" onClick={() => setHistory(true)}>Historique (version {script.version})</Btn>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1">
          <SaveBadge status={overall} />
          <span className="text-xs text-sf-muted">{scenes.length} scène(s) · environ {Math.round(total)} s de voix off (estimation, visée : {state.brief.duration_s} s)</span>
          <EngineNote engine={engine} used={used} />
        </div>
        <p className="mt-2 text-xs text-sf-muted">« Raccourcir », « Changer le ton » et « Tout régénérer » créent une nouvelle version : l'actuelle reste dans l'historique.</p>
      </Panel>

      <ol className="space-y-4">
        {scenes.map((scene, index) => (
          <SceneEditor key={`${scene.id}:${epoch}`} scene={scene} index={index} count={scenes.length} locked={locked} busy={structure.isPending}
            onMove={(delta) => move(index, delta)} onDelete={() => setAsk({ kind: "delete", scene })} onSaved={refresh} report={report} />
        ))}
      </ol>
      <div className="flex flex-wrap gap-2">
        <Btn disabled={locked || structure.isPending || scenes.length >= 30} onClick={() => structure.mutate(() => wizard.addScene(id, null))}>Ajouter une scène</Btn>
      </div>
      <CallToAction id={id} value={script.call_to_action} onSaved={set} />

      {state.problems.length > 0 && (
        <Notice tone="warning" title="À compléter avant de valider">
          <ul className="list-disc pl-4">{state.problems.map((p) => <li key={p}>{p}</li>)}</ul>
        </Notice>
      )}
      <Notice tone="neutral" title="Ce qui est provisoire">
        Les durées sont calculées sur le nombre de mots. Les sous-titres ne seront synchronisés qu'après la génération de la voix, dans le studio.
      </Notice>
      <div className="flex flex-wrap items-center gap-3">
        {locked
          ? <Btn variant="primary" onClick={() => navigate(`/creer/${id}/studio`)}>Ouvrir le studio</Btn>
          : <Btn variant="primary" busy={approve.isPending} disabled={state.problems.length > 0 || overall === "saving" || !!gen.busy} onClick={() => approve.mutate()}>Valider le script et ouvrir le studio</Btn>}
        {!locked && <span className="text-xs text-sf-muted">Valider ne lance aucune génération d'image, de voix ni de vidéo.</span>}
      </div>

      {ask?.kind === "delete" && (
        <Confirm title={`Supprimer la scène ${ask.scene.position + 1} ?`} confirm="Supprimer la scène" danger busy={structure.isPending} onClose={() => setAsk(null)}
          onConfirm={() => structure.mutate(() => wizard.deleteScene(ask.scene.id))}>
          <p>Son texte et son prompt seront supprimés. Pour pouvoir revenir en arrière, enregistre d'abord une version dans l'historique.</p>
        </Confirm>
      )}
      {ask?.kind === "regenerate" && (
        <Confirm title="Régénérer tout le script ?" confirm="Régénérer" onClose={() => setAsk(null)}
          onConfirm={() => { setAsk(null); void full("Écriture d'une nouvelle version", (rid, signal) => wizard.generateScript(id, rid, signal)); }}>
          <p>Une nouvelle version complète sera écrite à partir de l'idée et du brief. La version actuelle, avec tes modifications, reste dans l'historique.</p>
        </Confirm>
      )}
      {ask?.kind === "restore" && (
        <Confirm title={`Revenir à la version ${ask.version} ?`} confirm="Restaurer" busy={structure.isPending} onClose={() => setAsk(null)}
          onConfirm={() => structure.mutate(() => wizard.restore(id, ask.version).then((next) => { setHistory(false); setSaves({}); return next; }))}>
          <p>Elle devient la version courante. Aucune version n'est effacée.</p>
        </Confirm>
      )}
      {hooks && (
        <Dialog title="Autres accroches" onClose={() => setHooks(null)} footer={<Btn variant="ghost" onClick={() => setHooks(null)}>Garder l'accroche actuelle</Btn>}>
          <p className="text-sf-muted">Appliquer une accroche remplace seulement le texte de la première scène.</p>
          <ul className="space-y-2">
            {hooks.map((hook) => (
              <li key={hook} className="flex items-start justify-between gap-3 rounded-xl border border-sf-border bg-sf-raised p-3">
                <span>« {hook} »</span>
                <Btn onClick={() => void wizard.patchScene(scenes[0].id, { text: hook }).then(refresh).then(() => { setHooks(null); setSaves({}); setEpoch((e) => e + 1); }).catch(onError)}>Appliquer</Btn>
              </li>
            ))}
          </ul>
        </Dialog>
      )}
      {history && <History id={id} locked={locked} onClose={() => setHistory(false)} onRestore={(version) => setAsk({ kind: "restore", version })} />}
    </>
  );
}

const TONES: [string, string][] = [["educatif", "Éducatif"], ["storytelling", "Récit"], ["humour", "Humour"], ["choc", "Choc"], ["autorite", "Expert"], ["inspirant", "Inspirant"]];

function SceneEditor({ scene, index, count, locked, busy, onMove, onDelete, onSaved, report }: {
  scene: WizardScene; index: number; count: number; locked: boolean; busy: boolean;
  onMove: (delta: number) => void; onDelete: () => void; onSaved: () => void; report: (id: string, status: SaveStatus) => void;
}) {
  const push = useToasts((s) => s.push);
  const gen = useGeneration();
  const [form, setForm] = useState<Required<ScenePatch>>({ text: scene.text, on_screen_text: scene.on_screen_text, visual_intent: scene.visual_intent, visual_prompt: scene.visual_prompt, transition: scene.transition });
  const status = useAutosave(form, (value) => wizard.patchScene(scene.id, value).then(onSaved));
  useEffect(() => report(scene.id, status), [report, scene.id, status]);
  const set = <K extends keyof ScenePatch>(key: K, value: string) => setForm((f) => ({ ...f, [key]: value }));
  const regenerate = async (field: SceneField, label: string) => {
    const result = await gen.run(label, (rid, signal) => wizard.regenerateField(scene.id, field, rid, signal));
    if (result) { setForm((f) => ({ ...f, [field]: result.scene[field] })); push("Champ régénéré. Le reste de la scène n'a pas changé.", "success"); }
  };
  const regen = (field: SceneField, label: string) => <Btn variant="ghost" className="min-h-[32px] self-start px-2 text-xs" disabled={!!gen.busy} onClick={() => void regenerate(field, label)}>Régénérer ce champ</Btn>;

  return (
    <li className="rounded-sf border border-sf-border bg-sf-surface p-5 shadow-sf">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <h3 className="font-medium">Scène {index + 1}</h3>
          <Tag>≈ {Math.max(1, Math.round(spokenDuration(form.text)))} s (estimation)</Tag>
        </div>
        <div className="flex flex-wrap gap-1">
          <Btn variant="ghost" className="px-2.5" disabled={index === 0 || busy} onClick={() => onMove(-1)} aria-label={`Monter la scène ${index + 1}`}>↑ Monter</Btn>
          <Btn variant="ghost" className="px-2.5" disabled={index === count - 1 || busy} onClick={() => onMove(1)} aria-label={`Descendre la scène ${index + 1}`}>↓ Descendre</Btn>
          <Btn variant="ghost" className="px-2.5 text-sf-danger" disabled={locked || count <= 1} onClick={onDelete} aria-label={`Supprimer la scène ${index + 1}`}>Supprimer</Btn>
        </div>
      </div>
      <Generating gen={gen} />
      <div className="grid gap-4 lg:grid-cols-2">
        <div className="space-y-4">
          <Labeled label="Voix off" hint="Ce qui est dit pendant la scène.">
            {(fid) => <><textarea id={fid} rows={3} className={`${fieldClass} py-2`} value={form.text} onChange={(e) => set("text", e.target.value)} />{regen("text", "Réécriture de la voix off de cette scène")}</>}
          </Labeled>
          <Labeled label="Texte à l'écran" hint="Quelques mots forts, ou vide.">
            {(fid) => <><input id={fid} className={fieldClass} value={form.on_screen_text} onChange={(e) => set("on_screen_text", e.target.value)} />{regen("on_screen_text", "Réécriture du texte à l'écran")}</>}
          </Labeled>
        </div>
        <div className="space-y-4">
          <Labeled label="Intention visuelle" hint="Ce que l'image doit montrer, avec tes mots.">
            {(fid) => <input id={fid} className={fieldClass} value={form.visual_intent} onChange={(e) => set("visual_intent", e.target.value)} />}
          </Labeled>
          <Labeled label="Prompt visuel" hint="En anglais de préférence : c'est le texte envoyé au générateur d'images.">
            {(fid) => <><textarea id={fid} rows={3} className={`${fieldClass} py-2`} value={form.visual_prompt} onChange={(e) => set("visual_prompt", e.target.value)} />{regen("visual_prompt", "Réécriture du prompt visuel")}</>}
          </Labeled>
          <Labeled label="Transition vers la scène suivante">
            {(fid) => (
              <select id={fid} className={fieldClass} value={form.transition} onChange={(e) => set("transition", e.target.value)}>
                {Object.entries(TRANSITION_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
              </select>
            )}
          </Labeled>
        </div>
      </div>
    </li>
  );
}

function CallToAction({ id, value, onSaved }: { id: string; value: string; onSaved: (s: WizardState) => void }) {
  const [text, setText] = useState(value);
  const status = useAutosave(text, (v) => wizard.patchScript(id, { call_to_action: v }).then(onSaved));
  return (
    <Panel>
      <Labeled label="Appel à l'action (facultatif)" hint="Ex. : « Abonne-toi pour la suite ». Laisse vide si tu n'en veux pas.">
        {(fid) => <input id={fid} className={fieldClass} value={text} onChange={(e) => setText(e.target.value)} />}
      </Labeled>
      <div className="mt-2"><SaveBadge status={status} label="" /></div>
    </Panel>
  );
}

function History({ id, locked, onClose, onRestore }: { id: string; locked: boolean; onClose: () => void; onRestore: (version: number) => void }) {
  const client = useQueryClient();
  const push = useToasts((s) => s.push);
  const versions = useQuery({ queryKey: ["wizard", id, "versions"], queryFn: () => wizard.versions(id) });
  const snapshot = useMutation({
    mutationFn: () => wizard.snapshot(id),
    onSuccess: (list) => { client.setQueryData(["wizard", id, "versions"], list); void client.invalidateQueries({ queryKey: ["wizard", id], exact: true }); push("Version enregistrée dans l'historique.", "success"); },
    onError: (e: Error) => push(e.message, "error"),
  });
  return (
    <Dialog title="Historique des versions" onClose={onClose}
      footer={<><Btn variant="ghost" onClick={onClose}>Fermer</Btn><Btn busy={snapshot.isPending} onClick={() => snapshot.mutate()}>Enregistrer la version actuelle</Btn></>}>
      {locked && <p className="text-sf-muted">Le script est validé : rouvre-le depuis le studio pour restaurer une version.</p>}
      <ul className="max-h-80 space-y-2 overflow-y-auto">
        {versions.data?.map((v) => (
          <li key={v.version} className="flex items-center justify-between gap-3 rounded-xl border border-sf-border bg-sf-raised p-3">
            <div className="min-w-0">
              <p>Version {v.version} · {v.scenes} scène(s) {v.current && <Tag tone="primary">Actuelle</Tag>}</p>
              <p className="truncate text-xs text-sf-muted">{new Date(`${v.updated_at}Z`).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" })} · {v.preview || "(vide)"}</p>
            </div>
            {!v.current && <Btn disabled={locked} onClick={() => onRestore(v.version)}>Restaurer</Btn>}
          </li>
        ))}
      </ul>
    </Dialog>
  );
}
