// Etape 4 : le studio. Scenes a gauche, apercu vertical 9:16 au centre, proprietes a droite.
// L'apercu du storyboard n'est pas une video : la video rendue est montree a part, avec son etat reel.
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, assetUrl, upload } from "../../api/client";
import { useProject } from "../../api/hooks";
import type { Asset, Step } from "../../api/types";
import { wizard, type WizardScene, type WizardState } from "../../api/wizard";
import { Btn, Labeled, Notice, Page, Panel, Pill, Tag, fieldClass, type Tone } from "../../components/ds";
import { spokenDuration } from "../../lib/format";
import { useProjectStore } from "../../stores/project";
import { useToasts } from "../../stores/toasts";
import { Confirm, SaveBadge, StateGate, Stepper, stateKey, useAutosave, useWizard } from "./shared";

export default function StudioPage() {
  const { id = "" } = useParams();
  const query = useWizard(id);
  return (
    <Page title="Studio" subtitle="Vérifie chaque scène, lance la production, puis regarde la vidéo rendue.">
      <StateGate query={query}>{(state) => <Studio id={id} state={state} set={query.set} />}</StateGate>
    </Page>
  );
}

const PRODUCTION = ["create_storyboard", "generate_images", "generate_videos", "generate_voice", "create_subtitles", "select_music", "render_video"];
const STATUS: Record<string, { label: string; tone: Tone }> = {
  pending: { label: "À faire", tone: "neutral" }, running: { label: "En cours", tone: "primary" }, done: { label: "Terminé", tone: "success" },
  failed: { label: "Échec", tone: "danger" }, needs_validation: { label: "Attend ta décision", tone: "warning" }, cancelled: { label: "Annulé", tone: "neutral" },
};
type Tab = "texte" | "visuel" | "voix" | "sous-titres" | "musique";
const TAB_LABELS: Record<Tab, string> = { texte: "Texte", visuel: "Visuel", voix: "Voix", "sous-titres": "Sous-titres", musique: "Musique" };
type Ask = "reopen" | "images" | "voice" | "render" | null;

function Studio({ id, state, set }: { id: string; state: WizardState; set: (s: WizardState) => void }) {
  const navigate = useNavigate();
  const push = useToasts((s) => s.push);
  const client = useQueryClient();
  const setCurrent = useProjectStore((s) => s.setCurrent);
  useEffect(() => setCurrent(id), [id, setCurrent]);
  const live = useProject(id); // etat des etapes en direct (WebSocket existant)
  const steps = live.data?.steps ?? state.project.steps;
  const signature = steps.map((s) => `${s.name}:${s.status}`).join(",");
  useEffect(() => { void client.invalidateQueries({ queryKey: stateKey(id) }); }, [signature, client, id]);
  const assets = useQuery({ queryKey: ["assets", id], queryFn: () => api.assets(id) });
  const render = useQuery({ queryKey: ["render", id], queryFn: () => api.render(id) });
  const [selected, setSelected] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("texte");
  const [view, setView] = useState<"storyboard" | "video">("storyboard");
  const [ask, setAsk] = useState<Ask>(null);
  const onError = (e: Error) => push(e.message, "error");
  const scenes = state.script?.scenes ?? [];
  const scene = scenes.find((s) => s.id === selected) ?? scenes[0];
  const step = (name: string) => steps.find((s) => s.name === name);
  const running = steps.some((s) => s.status === "running");
  const waiting = steps.find((s) => PRODUCTION.includes(s.name) && s.status === "needs_validation");
  const failed = steps.find((s) => PRODUCTION.includes(s.name) && s.status === "failed");
  const rendered = step("render_video")?.status === "done" && !!render.data?.asset_id;
  const staleAny = state.stale.voice || state.stale.subtitles || state.stale.render || state.stale.images.length > 0;
  const upToDate = rendered && !staleAny && !failed && !running;
  const voiceReady = step("generate_voice")?.status === "done" && !(step("generate_voice")?.output as { skipped?: boolean } | null)?.skipped && !state.stale.voice;

  const produce = useMutation({ mutationFn: () => api.autopilot(id), onSuccess: () => void live.refetch(), onError });
  const redo = useMutation({
    mutationFn: (name: string) => api.redo(id, name),
    onSuccess: () => { setAsk(null); void live.refetch(); void client.invalidateQueries({ queryKey: stateKey(id) }); push("Étape remise à faire. Lance la production quand tu veux.", "success"); },
    onError,
  });
  const reopen = useMutation({ mutationFn: () => wizard.reopen(id), onSuccess: (next) => { set(next); navigate(`/creer/${id}/script`); }, onError });
  const duplicate = useMutation({
    mutationFn: () => wizard.duplicate(id),
    onSuccess: (copy) => { push("Projet dupliqué (sans les médias).", "success"); navigate(`/creer/${copy.project.id}`); },
    onError,
  });
  const order = useMutation({ mutationFn: (ids: string[]) => wizard.reorder(id, ids), onSuccess: set, onError });
  const move = (index: number, delta: number) => {
    const ids = scenes.map((s) => s.id);
    const target = index + delta;
    if (target < 0 || target >= ids.length) return;
    [ids[index], ids[target]] = [ids[target], ids[index]];
    order.mutate(ids);
  };
  const imageOf = (sceneId: string) => [...(assets.data ?? [])].reverse().find((a) => a.scene_id === sceneId && a.kind === "image");

  if (!state.script_approved || !state.script) {
    return (
      <>
        <Stepper id={id} state={state} />
        <Panel><p className="text-sm text-sf-muted">Le studio s'ouvre une fois le script validé.</p><Btn variant="primary" className="mt-3" onClick={() => navigate(`/creer/${id}/script`)}>Aller au script</Btn></Panel>
      </>
    );
  }

  return (
    <>
      <Stepper id={id} state={state} />
      <div className="flex flex-wrap items-center gap-2">
        <SaveBadge status="idle" label="Brouillon enregistré automatiquement" />
        <span className="flex-1" />
        <Btn variant="ghost" busy={duplicate.isPending} onClick={() => duplicate.mutate()}>Dupliquer le projet</Btn>
        <Btn variant="ghost" disabled={running} onClick={() => setAsk("reopen")}>Rouvrir le script</Btn>
      </div>
      {staleAny && (
        <Notice tone="warning" title="Des éléments ne correspondent plus au script">
          <ul className="list-disc pl-4">
            {state.stale.images.length > 0 && <li>{state.stale.images.length} image(s) faite(s) avec un ancien prompt.</li>}
            {state.stale.voice && <li>La voix a été générée avant tes dernières modifications de texte.</li>}
            {state.stale.subtitles && <li>Les sous-titres datent d'avant tes dernières modifications.</li>}
            {state.stale.render && <li>La vidéo rendue ne reflète pas l'état actuel.</li>}
          </ul>
          <p className="mt-1">Rien n'est relancé automatiquement : utilise les boutons « Refaire » des onglets Visuel et Voix.</p>
        </Notice>
      )}

      <div className="grid gap-4 xl:grid-cols-[250px_minmax(0,1fr)_340px]">
        <section aria-label="Scènes" className="order-2 xl:order-1">
          <Panel title="Scènes">
            <ol className="space-y-2">
              {scenes.map((s, index) => {
                const image = imageOf(s.id);
                const active = s.id === scene?.id;
                return (
                  <li key={s.id} className={`rounded-xl border p-2 transition duration-sf ${active ? "border-sf-primary bg-sf-primary/10" : "border-sf-border bg-sf-raised"}`}>
                    <button type="button" onClick={() => setSelected(s.id)} aria-pressed={active} className="flex w-full items-center gap-3 rounded-lg text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-sf-primary">
                      <span className="flex h-14 w-8 shrink-0 items-center justify-center overflow-hidden rounded bg-sf-bg text-xs text-sf-muted">
                        {image ? <img src={assetUrl(image.id)} alt="" className="h-full w-full object-cover" /> : index + 1}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block text-xs text-sf-muted">Scène {index + 1}{state.stale.images.includes(s.id) ? " · image à refaire" : ""}</span>
                        <span className="line-clamp-2 text-sm">{s.text || s.on_screen_text || "(sans texte)"}</span>
                      </span>
                    </button>
                    <div className="mt-1 flex justify-end gap-1">
                      <Btn variant="ghost" className="min-h-[32px] px-2 text-xs" disabled={index === 0 || order.isPending || running} onClick={() => move(index, -1)} aria-label={`Monter la scène ${index + 1}`}>↑</Btn>
                      <Btn variant="ghost" className="min-h-[32px] px-2 text-xs" disabled={index === scenes.length - 1 || order.isPending || running} onClick={() => move(index, 1)} aria-label={`Descendre la scène ${index + 1}`}>↓</Btn>
                    </div>
                  </li>
                );
              })}
            </ol>
            <p className="mt-3 text-xs text-sf-muted">Pour ajouter ou supprimer une scène, rouvre le script.</p>
          </Panel>
        </section>

        <section aria-label="Aperçu" className="order-1 xl:order-2">
          <Panel>
            <div className="mb-3 flex flex-wrap gap-2" role="group" aria-label="Type d'aperçu">
              <Pill active={view === "storyboard"} onClick={() => setView("storyboard")}>Storyboard</Pill>
              <Pill active={view === "video"} onClick={() => setView("video")} dot={rendered ? (state.stale.render ? "warning" : "success") : "neutral"}>Vidéo rendue</Pill>
            </div>
            <div className="mx-auto w-full max-w-[300px]">
              <div className="relative aspect-[9/16] overflow-hidden rounded-sf border border-sf-border bg-black">
                {view === "storyboard" ? <Storyboard scene={scene} image={scene ? imageOf(scene.id) : undefined} /> : rendered && render.data?.asset_id
                  ? <video key={render.data.id} src={assetUrl(render.data.asset_id)} controls className="h-full w-full object-contain" />
                  : <Placeholder>Aucune vidéo rendue pour l'instant. Lance la production ci-dessous.</Placeholder>}
              </div>
              <p className="mt-2 text-center text-xs text-sf-muted">
                {view === "storyboard" ? "Aperçu du storyboard : une image fixe et les textes, pas la vidéo finale." : rendered ? (state.stale.render ? "Vidéo rendue avant tes dernières modifications." : "Vidéo réellement rendue (MP4 1080x1920).") : ""}
              </p>
            </div>
          </Panel>

          <div className="mt-4">
            <Panel title="Production" hint="Images, vidéos, voix, sous-titres, musique et montage s'enchaînent. Toute dépense demande ta confirmation.">
              <ul className="space-y-1.5">
                {PRODUCTION.map((name) => { const s = step(name); return s ? <StepRow key={name} step={s} /> : null; })}
              </ul>
              {failed && <Notice tone="danger" title={`Échec : ${failed.label}`}>{failed.error ?? "Erreur inconnue."}</Notice>}
              {waiting && (
                <Notice tone="warning" title={`${waiting.label} attend ta décision`}>
                  {waiting.output?.message ?? "Une confirmation est nécessaire avant de continuer."}{" "}
                  <Link to="/a-valider" className="text-violet-300 underline">Ouvrir « À valider »</Link>
                </Notice>
              )}
              <div className="mt-4 flex flex-wrap items-center gap-3">
                <Btn variant="primary" busy={produce.isPending || running} disabled={!!waiting || upToDate} onClick={() => produce.mutate()}>
                  {running ? "Production en cours" : failed ? "Réessayer" : upToDate ? "Vidéo à jour" : rendered ? "Continuer la production" : "Générer la vidéo"}
                </Btn>
                {rendered && <Link to="/apercu" className="text-sm text-violet-300 underline">Valider, exporter ou publier</Link>}
              </div>
              <p className="mt-2 text-xs text-sf-muted">La progression affichée est l'état réel de chaque étape ; aucune durée n'est estimée.</p>
            </Panel>
          </div>
        </section>

        <section aria-label="Propriétés de la scène" className="order-3">
          <Panel title={scene ? `Scène ${scene.position + 1}` : "Scène"}>
            <div className="mb-4 flex flex-wrap gap-1.5" role="tablist" aria-label="Propriétés">
              {(["texte", "visuel", "voix", "sous-titres", "musique"] as Tab[]).map((t) => (
                <button key={t} type="button" role="tab" aria-selected={tab === t} onClick={() => setTab(t)}
                  className={`min-h-[36px] rounded-lg px-3 text-sm transition duration-sf focus:outline-none focus-visible:ring-2 focus-visible:ring-sf-primary ${tab === t ? "bg-sf-primary/20 text-sf-text" : "text-sf-muted hover:text-sf-text"}`}>{TAB_LABELS[t]}</button>
              ))}
            </div>
            <div role="tabpanel">
              {scene && tab === "texte" && <TextTab key={scene.id} scene={scene} voiceReady={voiceReady} onSaved={() => void client.invalidateQueries({ queryKey: stateKey(id) })} />}
              {scene && tab === "visuel" && <VisualTab key={scene.id} projectId={id} scene={scene} image={imageOf(scene.id)} stale={state.stale.images.includes(scene.id)} busy={running} onRedo={() => setAsk("images")}
                onChanged={() => { void assets.refetch(); void client.invalidateQueries({ queryKey: stateKey(id) }); }} />}
              {tab === "voix" && <StepTab step={step("generate_voice")} stale={state.stale.voice} staleText="La voix a été générée avant tes dernières modifications de texte."
                actions={<><Btn disabled={running || step("generate_voice")?.status !== "done"} onClick={() => setAsk("voice")}>Refaire la voix</Btn><Link to="/voix" className="text-sm text-violet-300 underline">Choisir la voix et écouter un essai</Link></>}
                soon="Une voix différente par scène : disponible dans un prochain lot. La voix choisie s'applique à tout le Short." />}
              {tab === "sous-titres" && <StepTab step={step("create_subtitles")} stale={state.stale.subtitles} staleText="Les sous-titres datent d'avant tes dernières modifications."
                actions={<Link to="/voix" className="text-sm text-violet-300 underline">Choisir le style des sous-titres</Link>}
                soon={step("generate_voice")?.status === "done" ? "Les sous-titres sont alignés sur la voix générée." : "Pas encore synchronisés : ils seront alignés sur la voix une fois celle-ci générée."} />}
              {tab === "musique" && <StepTab step={step("select_music")} stale={false} staleText=""
                actions={<Link to="/parametres" className="text-sm text-violet-300 underline">Gérer ma bibliothèque musicale</Link>}
                soon="Génération de musique par IA : non configurée, prévue dans un prochain lot. ShortForge choisit un morceau dans ta bibliothèque, s'il y en a un." />}
            </div>
          </Panel>
        </section>
      </div>

      {ask === "reopen" && (
        <Confirm title="Rouvrir le script ?" confirm="Rouvrir" busy={reopen.isPending} onClose={() => setAsk(null)} onConfirm={() => reopen.mutate()}>
          <p>Tu pourras ajouter ou supprimer des scènes et restaurer une version. Les images déjà produites sont gardées, mais les étapes de production seront à relancer après la nouvelle validation.</p>
        </Confirm>
      )}
      {ask === "images" && (
        <Confirm title="Refaire les images à refaire ?" confirm="Remettre à faire" busy={redo.isPending} onClose={() => setAsk(null)} onConfirm={() => redo.mutate("generate_images")}>
          <p>Les images marquées « à refaire » seront régénérées avec ComfyUI à la prochaine production ; les autres sont gardées. Les étapes suivantes (vidéos, voix, montage) repasseront aussi par la production. Rien ne démarre tant que tu ne cliques pas sur « Générer la vidéo ».</p>
        </Confirm>
      )}
      {ask === "voice" && (
        <Confirm title="Refaire la voix ?" confirm="Remettre à faire" busy={redo.isPending} onClose={() => setAsk(null)} onConfirm={() => redo.mutate("generate_voice")}>
          <p>La voix, les sous-titres et le montage seront refaits à la prochaine production. Une voix payante (ElevenLabs) te demandera une confirmation de coût.</p>
        </Confirm>
      )}
    </>
  );
}

function Placeholder({ children }: { children: ReactNode }) {
  return <div className="flex h-full items-center justify-center p-6 text-center text-sm text-sf-muted">{children}</div>;
}

function Storyboard({ scene, image }: { scene?: WizardScene; image?: Asset }) {
  if (!scene) return <Placeholder>Aucune scène.</Placeholder>;
  return (
    <>
      {image ? <img src={assetUrl(image.id)} alt={scene.visual_intent || `Image de la scène ${scene.position + 1}`} className="h-full w-full object-cover" />
        : <Placeholder>Pas encore d'image pour cette scène.{scene.visual_intent ? ` Intention : ${scene.visual_intent}` : ""}</Placeholder>}
      {scene.on_screen_text && <p className="absolute inset-x-3 top-[18%] text-center text-xl font-bold uppercase leading-tight text-white [text-shadow:0_2px_6px_rgb(0_0_0/0.9)]">{scene.on_screen_text}</p>}
      {scene.text && <p className="absolute inset-x-3 bottom-[12%] rounded-lg bg-black/60 px-2 py-1.5 text-center text-sm text-white">{scene.text}</p>}
    </>
  );
}

function StepRow({ step }: { step: Step }) {
  const info = STATUS[step.status] ?? STATUS.pending;
  const skipped = step.status === "done" && step.output?.skipped === true;
  return (
    <li className="flex items-center justify-between gap-3 rounded-lg px-2 py-1.5 text-sm">
      <span>{step.label}</span>
      <Tag tone={skipped ? "neutral" : info.tone}>{step.status === "running" && <span className="mr-1 inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-current" />}{skipped ? "Sans objet" : info.label}</Tag>
    </li>
  );
}

function TextTab({ scene, voiceReady, onSaved }: { scene: WizardScene; voiceReady: boolean; onSaved: () => void }) {
  const [form, setForm] = useState({ text: scene.text, on_screen_text: scene.on_screen_text });
  const status = useAutosave(form, (value) => wizard.patchScene(scene.id, value).then(onSaved));
  return (
    <div className="space-y-4">
      <Labeled label="Voix off" hint={voiceReady && form.text === scene.text
        ? `Durée dans la vidéo : ${Number(scene.duration_s.toFixed(1)).toLocaleString("fr-FR")} s (voix générée)`
        : `≈ ${Math.max(1, Math.round(spokenDuration(form.text)))} s (estimation : la voix n'est pas encore générée pour ce texte)`}>
        {(fid) => <textarea id={fid} rows={5} className={`${fieldClass} py-2`} value={form.text} onChange={(e) => setForm({ ...form, text: e.target.value })} />}
      </Labeled>
      <Labeled label="Texte à l'écran" hint="Incrusté en haut de la vidéo pendant toute la scène, au prochain montage.">
        {(fid) => <input id={fid} className={fieldClass} value={form.on_screen_text} onChange={(e) => setForm({ ...form, on_screen_text: e.target.value })} />}
      </Labeled>
      <SaveBadge status={status} label="" />
    </div>
  );
}

function VisualTab({ projectId, scene, image, stale, busy, onRedo, onChanged }: {
  projectId: string; scene: WizardScene; image?: Asset; stale: boolean; busy: boolean; onRedo: () => void; onChanged: () => void;
}) {
  const push = useToasts((s) => s.push);
  const services = useQuery({ queryKey: ["status"], queryFn: api.status, staleTime: 15_000 });
  const [form, setForm] = useState({ visual_intent: scene.visual_intent, visual_prompt: scene.visual_prompt });
  const status = useAutosave(form, (value) => wizard.patchScene(scene.id, value).then(onChanged));
  const [rights, setRights] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const importImage = useMutation({
    mutationFn: (file: File) => upload(wizard.imageUploadPath(scene.id), file, { rights_confirmed: rights }),
    onSuccess: () => { push("Image importée pour cette scène.", "success"); onChanged(); },
    onError: (e: Error) => push(e.message, "error"),
  });
  const mark = useMutation({
    mutationFn: () => api.regenerateScene(scene.id, "image"),
    onSuccess: () => { onChanged(); onRedo(); },
    onError: (e: Error) => push(e.message, "error"),
  });
  const comfy = services.data?.comfyui.running;
  return (
    <div className="space-y-4" data-project={projectId}>
      <div className="flex flex-wrap gap-1.5">
        <Tag tone={image ? (stale ? "warning" : "success") : "neutral"}>{image ? (stale ? "Image faite avec un ancien prompt" : image.origin === "imported" ? "Image importée" : "Image générée") : "Pas encore d'image"}</Tag>
        <Tag tone={comfy ? "success" : "warning"}>{services.isLoading ? "ComfyUI : vérification…" : comfy ? "ComfyUI détecté" : "ComfyUI non détecté"}</Tag>
      </div>
      <Labeled label="Intention visuelle">
        {(fid) => <input id={fid} className={fieldClass} value={form.visual_intent} onChange={(e) => setForm({ ...form, visual_intent: e.target.value })} />}
      </Labeled>
      <Labeled label="Prompt visuel" hint="Le modifier marque l'image actuelle comme « à refaire », sans rien relancer.">
        {(fid) => <textarea id={fid} rows={4} className={`${fieldClass} py-2`} value={form.visual_prompt} onChange={(e) => setForm({ ...form, visual_prompt: e.target.value })} />}
      </Labeled>
      <SaveBadge status={status} label="" />
      <div className="space-y-2 border-t border-sf-border pt-4">
        <Btn disabled={busy || !image} busy={mark.isPending} onClick={() => mark.mutate()}>Refaire cette image</Btn>
        {!comfy && !services.isLoading && <p className="text-xs text-sf-warning">Génération d'images non configurée : lance ComfyUI (Paramètres), ou importe ta propre image ci-dessous.</p>}
      </div>
      <div className="space-y-2 border-t border-sf-border pt-4">
        <p className="text-sm">Utiliser ma propre image</p>
        <label className="flex items-start gap-2 text-sm text-sf-muted">
          <input type="checkbox" className="mt-0.5 h-4 w-4 accent-violet-600" checked={rights} onChange={(e) => setRights(e.target.checked)} />
          J'ai le droit d'utiliser cette image.
        </label>
        <input ref={input} type="file" accept="image/png,image/jpeg,image/webp" className="sr-only" aria-label="Fichier image" onChange={(e) => { const file = e.target.files?.[0]; if (file) importImage.mutate(file); e.target.value = ""; }} />
        <Btn disabled={!rights} busy={importImage.isPending} onClick={() => input.current?.click()}>Importer une image (PNG, JPG, WebP)</Btn>
      </div>
      <p className="text-xs text-sf-muted">Moteur vidéo par scène (ComfyUI ou fournisseur externe) : <Link to="/scenes" className="text-violet-300 underline">Revue des scènes</Link>.</p>
    </div>
  );
}

function StepTab({ step, stale, staleText, actions, soon }: { step?: Step; stale: boolean; staleText: string; actions: ReactNode; soon: string }) {
  const info = STATUS[step?.status ?? "pending"] ?? STATUS.pending;
  const skipped = step?.status === "done" && step.output?.skipped === true;
  return (
    <div className="space-y-4 text-sm">
      <p className="flex items-center gap-2">État : <Tag tone={skipped ? "neutral" : info.tone}>{skipped ? "Sans objet" : info.label}</Tag></p>
      {step?.error && <Notice tone="danger">{step.error}</Notice>}
      {stale && <Notice tone="warning">{staleText}</Notice>}
      <div className="flex flex-col items-start gap-3">{actions}</div>
      <p className="text-xs text-sf-muted">{soon}</p>
      <p className="text-xs text-sf-muted">Ce réglage s'applique à tout le Short, pas seulement à la scène sélectionnée.</p>
    </div>
  );
}
