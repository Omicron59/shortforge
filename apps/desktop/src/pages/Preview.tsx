// Apercu video, validation humaine obligatoire, brouillon YouTube, verification finale et publication.
// Rien n'est publie sans : publication activee dans le .env, rendu regarde et valide par une personne,
// verification finale au vert et confirmation explicite de la publication.
import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api, assetUrl } from "../api/client";
import { useAction } from "../api/hooks";
import type { ProjectDetail, SocialPostT, YoutubeDraft } from "../api/types";
import { WithProject } from "../components/Layout";
import { NextAction, currentStep, stepOf } from "../components/Pipeline";
import { Alert, Badge, Button, Card, Empty, Field, PageHeader, StatusBadge, inputClass } from "../components/ui";
import { dateTime, seconds } from "../lib/format";

export default function Preview() {
  return (
    <>
      <PageHeader title="Aperçu et publication" subtitle="Regarde le Short en entier, valide-le, prépare le brouillon YouTube. Rien n'est publié sans ton accord explicite." />
      <WithProject>{(project) => <PreviewBody project={project} />}</WithProject>
    </>
  );
}

const PRIVACY_LABELS = { private: "Privée", unlisted: "Non répertoriée", public: "Publique" } as const;

function PreviewBody({ project }: { project: ProjectDetail }) {
  const render = useQuery({ queryKey: ["render", project.id], queryFn: () => api.render(project.id) });
  const current = currentStep(project);
  const [watched, setWatched] = useState(false);
  const renderStep = stepOf(project, "render_video");
  const info = renderStep?.output as { duration_s?: number; width?: number; height?: number; size_bytes?: number; warnings?: string[] } | null;

  useEffect(() => setWatched(false), [render.data?.asset_id]);

  const gatesHere = ["review_preview", "approve_final_render", "publish"];
  const showGenericAction = current && !gatesHere.includes(current.name);

  return (
    <div className="space-y-4">
      {showGenericAction && <NextAction project={project} />}
      <div className="grid gap-4 lg:grid-cols-5">
        <Card title="Rendu final (1080x1920)" className="lg:col-span-2">
          {render.data?.asset_id ? (
            <div className="flex flex-col items-center gap-3">
              <video
                key={render.data.asset_id}
                src={assetUrl(render.data.asset_id)}
                controls
                onEnded={() => setWatched(true)}
                className="aspect-[9/16] w-full max-w-[340px] rounded-lg bg-black"
              />
              <div className="flex flex-wrap justify-center gap-1.5 text-xs">
                <Badge>{render.data.width}x{render.data.height}</Badge>
                <Badge>H.264 + AAC</Badge>
                {info?.duration_s !== undefined && <Badge>{seconds(info.duration_s)}</Badge>}
                {info?.size_bytes !== undefined && <Badge>{(info.size_bytes / 1_048_576).toFixed(1).replace(".", ",")} Mo</Badge>}
                {render.data.approved_by ? (
                  <Badge tone="green">Validée par {render.data.approved_by}</Badge>
                ) : (
                  <Badge tone={watched ? "green" : "yellow"}>{watched ? "Regardée jusqu'au bout" : "Pas encore regardée en entier"}</Badge>
                )}
              </div>
              {info?.warnings?.length ? <Alert tone="yellow">{info.warnings.join("\n")}</Alert> : null}
              <a href={assetUrl(render.data.asset_id)} download="short_1080x1920.mp4" className="text-sm text-violet-300 underline">
                Télécharger le MP4
              </a>
            </div>
          ) : (
            <Empty>Pas encore de rendu. Il est créé par l'étape « Montage » (FFmpeg).</Empty>
          )}
        </Card>

        <div className="space-y-4 lg:col-span-3">
          <Validation project={project} watched={watched} />
          <Quality project={project} />
          <Draft project={project} />
          <Platforms project={project} />
          <Publication project={project} />
        </div>
      </div>
    </div>
  );
}

/** Revue de l'apercu puis validation du rendu final : obligatoires, par une personne. */
function Validation({ project, watched }: { project: ProjectDetail; watched: boolean }) {
  const review = stepOf(project, "review_preview");
  const final = stepOf(project, "approve_final_render");
  const [confirmed, setConfirmed] = useState(false);
  const [reason, setReason] = useState("");
  const advance = useAction(() => api.advance(project.id), "Étape lancée.");
  const approveReview = useAction(() => api.approve(project.id, "review_preview"), "Aperçu validé.");
  const approveFinal = useAction(() => api.approve(project.id, "approve_final_render", true), "Rendu final validé.");
  const reject = useAction((step: string) => api.reject(project.id, step, reason), "Refusé : le montage sera refait.");
  const current = currentStep(project);

  return (
    <Card title="Validation humaine">
      <ul className="mb-4 space-y-2 text-sm">
        {[review, final].map((s) => s && (
          <li key={s.name} className="flex items-center justify-between">
            <span>{s.label}{s.validated_by && <span className="text-xs text-zinc-500"> · par {s.validated_by}, {dateTime(s.validated_at)}</span>}</span>
            <StatusBadge status={s.status} />
          </li>
        ))}
      </ul>

      {current && ["review_preview", "approve_final_render"].includes(current.name) && current.status === "pending" && (
        <Button variant="primary" busy={advance.isPending} onClick={() => advance.mutate(undefined)}>Passer à la validation</Button>
      )}

      {review?.status === "needs_validation" && (
        <div className="space-y-3">
          <p className="text-sm text-zinc-300">Regarde l'aperçu. Il te convient ?</p>
          <div className="flex flex-wrap gap-2">
            <Button variant="primary" busy={approveReview.isPending} onClick={() => approveReview.mutate(undefined)}>L'aperçu me convient</Button>
            <input className={`${inputClass} w-64`} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Ce qui ne va pas (facultatif)" />
            <Button variant="danger" onClick={() => reject.mutate("review_preview")}>Refaire le montage</Button>
          </div>
        </div>
      )}

      {final?.status === "needs_validation" && (
        <div className="space-y-3">
          {!watched && <Alert tone="yellow">Regarde la vidéo jusqu'à la fin avant de la valider.</Alert>}
          <label className={`flex items-center gap-2 text-sm ${watched ? "" : "opacity-50"}`}>
            <input type="checkbox" disabled={!watched} checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />
            J'ai regardé le rendu final en entier et je le valide.
          </label>
          <div className="flex gap-2">
            <Button variant="primary" disabled={!watched || !confirmed} busy={approveFinal.isPending} onClick={() => approveFinal.mutate(undefined)}>
              Valider le rendu final
            </Button>
            <Button variant="danger" onClick={() => reject.mutate("approve_final_render")}>Refuser et refaire le montage</Button>
          </div>
        </div>
      )}
    </Card>
  );
}

/** Brouillon local : rien n'est envoye a YouTube tant que la publication n'est pas confirmee. */
function Draft({ project }: { project: ProjectDetail }) {
  const draft = useQuery({ queryKey: ["draft", project.id], queryFn: () => api.draft(project.id) });
  const [form, setForm] = useState<Pick<YoutubeDraft, "title" | "description" | "privacy" | "made_for_kids"> & { tags: string } | null>(null);
  const save = useAction((body: Parameters<typeof api.updateDraft>[1]) => api.updateDraft(project.id, body), "Brouillon enregistré.");
  const step = stepOf(project, "create_youtube_draft");

  useEffect(() => {
    if (draft.data) {
      const d = draft.data;
      setForm({ title: d.title, description: d.description, privacy: d.privacy, made_for_kids: d.made_for_kids, tags: d.tags.join(", ") });
    }
  }, [draft.data]);

  if (!draft.data || !form) {
    return (
      <Card title="Brouillon YouTube">
        <p className="text-sm text-zinc-400">
          {step?.status === "done" ? "Chargement…" : "Le brouillon est préparé après la validation du rendu final (étape « Brouillon YouTube »)."}
        </p>
      </Card>
    );
  }
  const locked = draft.data.status !== "draft";

  return (
    <Card title="Brouillon YouTube" actions={<Badge tone={locked ? "green" : "zinc"}>{locked ? "Envoyé" : "Local, non envoyé"}</Badge>}>
      <div className="grid gap-3">
        <Field label={`Titre (${form.title.length}/100)`}>
          <input className={inputClass} maxLength={100} disabled={locked} value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
        </Field>
        <Field label={`Description (${form.description.length}/5000)`} hint="La mention « contenu généré par IA » doit rester dans la description.">
          <textarea className={inputClass} rows={5} maxLength={5000} disabled={locked} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
        </Field>
        <Field label="Tags (séparés par des virgules)">
          <input className={inputClass} disabled={locked} value={form.tags} onChange={(e) => setForm({ ...form, tags: e.target.value })} />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Confidentialité">
            <select className={inputClass} disabled={locked} value={form.privacy} onChange={(e) => setForm({ ...form, privacy: e.target.value as YoutubeDraft["privacy"] })}>
              {Object.entries(PRIVACY_LABELS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </Field>
          <label className="mt-6 flex items-center gap-2 text-sm">
            <input type="checkbox" disabled={locked} checked={form.made_for_kids} onChange={(e) => setForm({ ...form, made_for_kids: e.target.checked })} />
            Conçue pour les enfants
          </label>
        </div>
        {!locked && (
          <Button className="self-start" busy={save.isPending} onClick={() => save.mutate({
            title: form.title, description: form.description, privacy: form.privacy, made_for_kids: form.made_for_kids,
            tags: form.tags.split(",").map((t) => t.trim()).filter(Boolean),
          })}>
            Enregistrer le brouillon
          </Button>
        )}
        {draft.data.youtube_video_id && (
          <Alert tone="green">
            Envoyée sur YouTube ({PRIVACY_LABELS[draft.data.privacy]}) par {draft.data.human_approved_by} · identifiant {draft.data.youtube_video_id}
          </Alert>
        )}
        {draft.data.error && <Alert tone="red">{draft.data.error}</Alert>}
      </div>
    </Card>
  );
}

/** Verification finale (toujours visible) puis publication, seulement si tout est au vert. */
function Publication({ project }: { project: ProjectDetail }) {
  const navigate = useNavigate();
  const status = useQuery({ queryKey: ["youtube-status"], queryFn: api.youtubeStatus });
  const check = useQuery({ queryKey: ["final-check", project.id], queryFn: () => api.finalCheck(project.id) });
  const draft = useQuery({ queryKey: ["draft", project.id], queryFn: () => api.draft(project.id) });
  const publish = stepOf(project, "publish");
  const [confirmed, setConfirmed] = useState(false);
  const advance = useAction(() => api.advance(project.id), "Étape lancée.");
  const approve = useAction(() => api.approve(project.id, "publish", true), "Vidéo envoyée sur YouTube.");
  const ready = !!check.data?.ready;
  const current = currentStep(project);

  return (
    <Card title="Vérification finale et publication"
      actions={<Button variant="ghost" className="text-xs" onClick={() => void check.refetch()}>Revérifier</Button>}>
      {!status.data?.publish_enabled && (
        <div className="mb-3">
          <Alert tone="blue">
            Publication désactivée (YOUTUBE_PUBLISH_ENABLED=false, réglage par défaut). Le Short reste sur ton ordinateur ; tu peux le télécharger et l'envoyer toi-même.
          </Alert>
        </div>
      )}
      <ul className="space-y-1.5 text-sm">
        {check.data?.checks.map((c) => (
          <li key={c.id} className="flex gap-2">
            <span className={c.ok ? "text-emerald-400" : "text-red-400"}>{c.ok ? "✓" : "✗"}</span>
            <span>
              {c.label}
              {c.detail && <span className="block text-xs text-zinc-500">{c.detail}</span>}
            </span>
          </li>
        ))}
      </ul>
      {check.data && !check.data.checks.find((c) => c.id === "channel")?.ok && (
        <Button variant="ghost" className="mt-2 text-xs" onClick={() => navigate("/parametres")}>Connecter ma chaîne YouTube →</Button>
      )}

      <div className="mt-4 border-t border-zinc-800 pt-4">
        {publish?.status === "done" ? (
          <Alert tone="green">Publication terminée.</Alert>
        ) : current?.name === "publish" && publish?.status === "pending" ? (
          <Button busy={advance.isPending} onClick={() => advance.mutate(undefined)}>Préparer la publication</Button>
        ) : publish?.status === "needs_validation" ? (
          <div className="space-y-3">
            <label className={`flex items-center gap-2 text-sm ${ready ? "" : "opacity-50"}`}>
              <input type="checkbox" disabled={!ready} checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />
              Je confirme l'envoi de « {draft.data?.title} » sur {status.data?.channel?.title ?? "ma chaîne"} en mode {PRIVACY_LABELS[draft.data?.privacy ?? "private"].toLowerCase()}.
            </label>
            <Button variant="primary" disabled={!ready || !confirmed} busy={approve.isPending} onClick={() => approve.mutate(undefined)}>
              Publier sur YouTube
            </Button>
            {!ready && <p className="text-xs text-zinc-500">Le bouton s'active quand toutes les vérifications sont au vert.</p>}
          </div>
        ) : (
          <p className="text-sm text-zinc-500">La publication vient après la validation du rendu final et le brouillon.</p>
        )}
      </div>
    </Card>
  );
}

/** Note du controle qualite image par image (FFmpeg). */
function Quality({ project }: { project: ProjectDetail }) {
  const out = stepOf(project, "render_video")?.output as { quality?: { score: number; issues: string[] } } | null;
  const q = out?.quality;
  if (!q) return null;
  const tone = q.score >= 8 ? "green" : q.score >= 6 ? "yellow" : "red";
  return (
    <Card title="Contrôle vidéo" actions={<Badge tone={tone}>{q.score.toLocaleString("fr-FR")}/10</Badge>}>
      {q.issues.length ? (
        <ul className="list-inside list-disc text-sm text-zinc-300">{q.issues.map((i) => <li key={i}>{i}</li>)}</ul>
      ) : (
        <p className="text-sm text-emerald-300">Aucun défaut détecté : ni passage noir, ni image figée, ni silence, volume correct.</p>
      )}
      <p className="mt-2 text-xs text-zinc-500">Analyse image par image (passages noirs, images figées) et du son (silences, volume en LUFS).</p>
    </Card>
  );
}

const METHOD_LABELS = { youtube_api: "Envoi automatique (API YouTube)", postiz: "Envoi automatique (Postiz)", manual: "Tu publies toi-même" };
const POST_STATUS: Record<string, string> = { draft: "à préparer", exported: "exporté", scheduled: "programmé", published: "publié", failed: "échec" };

/** YouTube, TikTok et Instagram : texte, heure, et export manuel si pas d'envoi automatique. */
function Platforms({ project }: { project: ProjectDetail }) {
  const final = stepOf(project, "approve_final_render");
  const posts = useQuery({ queryKey: ["posts", project.id], queryFn: () => api.posts(project.id), enabled: final?.status === "done" });
  const finish = useAction(() => api.finishManual(project.id), "Short terminé (publication faite à la main).");
  if (final?.status !== "done") return null;
  const allManual = posts.data?.every((p) => !p.enabled || p.method === "manual");
  return (
    <Card title="Plateformes">
      <div className="space-y-4">
        {posts.data?.map((post) => <PostEditor key={post.id} projectId={project.id} post={post} />)}
      </div>
      {allManual && stepOf(project, "publish")?.status !== "done" && (
        <div className="mt-4 border-t border-zinc-800 pt-4">
          <p className="mb-2 text-sm text-zinc-400">Aucun envoi automatique : télécharge le MP4, copie les textes, publie toi-même, puis termine le Short.</p>
          <Button onClick={() => finish.mutate(undefined)}>J'ai publié moi-même : terminer</Button>
        </div>
      )}
    </Card>
  );
}

function toLocalInput(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(/[zZ+]/.test(iso.slice(10)) ? iso : `${iso}Z`);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function PostEditor({ projectId, post }: { projectId: string; post: SocialPostT }) {
  const [caption, setCaption] = useState(post.caption);
  const [url, setUrl] = useState("");
  const patch = useAction((body: Parameters<typeof api.patchPost>[1]) => api.patchPost(post.id, body), `${post.label} : enregistré.`);
  const exported = useAction(() => api.postExported(post.id));
  const published = useAction(() => api.postPublished(post.id, url), `${post.label} : marqué comme publié.`);
  const render = useQuery({ queryKey: ["render", projectId], queryFn: () => api.render(projectId) });
  const locked = ["scheduled", "published"].includes(post.status);
  useEffect(() => setCaption(post.caption), [post.caption]);

  return (
    <div className={`rounded-lg border p-3 ${post.enabled ? "border-zinc-800" : "border-zinc-900 opacity-60"}`}>
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <label className="flex items-center gap-2 font-medium">
          <input type="checkbox" checked={post.enabled} disabled={locked} onChange={(e) => patch.mutate({ enabled: e.target.checked })} /> {post.label}
        </label>
        <Badge tone={post.method === "manual" ? "zinc" : "blue"}>{METHOD_LABELS[post.method]}</Badge>
        <Badge tone={post.status === "failed" ? "red" : post.status === "draft" ? "zinc" : "green"}>{POST_STATUS[post.status] ?? post.status}</Badge>
      </div>
      {post.platform !== "youtube" && (
        <textarea className={inputClass} rows={3} disabled={locked} value={caption} onChange={(e) => setCaption(e.target.value)} onBlur={() => caption !== post.caption && patch.mutate({ caption })} />
      )}
      {post.platform === "youtube" && <p className="text-xs text-zinc-500">Texte : titre et description du brouillon YouTube ci-dessus.</p>}
      <div className="mt-2 flex flex-wrap items-center gap-2 text-sm">
        <span className="text-zinc-400">Publier le</span>
        <input type="datetime-local" className={`${inputClass} w-56`} disabled={locked} defaultValue={toLocalInput(post.scheduled_at)}
          onBlur={(e) => e.target.value ? patch.mutate({ scheduled_at: new Date(e.target.value).toISOString() }) : patch.mutate({ clear_schedule: true })} />
        <span className="text-xs text-zinc-500">vide = dès la publication</span>
      </div>
      {post.error && <p className="mt-2 text-xs text-red-300">{post.error}</p>}
      {post.method === "manual" && post.enabled && post.status !== "published" && (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Button className="text-xs" onClick={() => { void navigator.clipboard?.writeText(post.platform === "youtube" ? "" : caption); exported.mutate(undefined); }}>Copier le texte</Button>
          {render.data?.asset_id && <a className="text-xs text-violet-300 underline" href={assetUrl(render.data.asset_id)} download={`short_${post.platform}.mp4`}>Télécharger le MP4</a>}
          <input className={`${inputClass} w-64 text-xs`} value={url} onChange={(e) => setUrl(e.target.value)} placeholder="Lien de la publication (facultatif)" />
          <Button className="text-xs" onClick={() => published.mutate(undefined)}>C'est publié</Button>
        </div>
      )}
    </div>
  );
}
