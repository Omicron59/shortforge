// Apercu video, validation humaine obligatoire, brouillon YouTube, verification finale et publication.
// Rien n'est publie sans : publication activee dans le .env, rendu regarde et valide par une personne,
// verification finale au vert et confirmation explicite de la publication.
import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api, assetUrl } from "../api/client";
import { useAction } from "../api/hooks";
import type { ProjectDetail, YoutubeDraft } from "../api/types";
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
          <Draft project={project} />
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
