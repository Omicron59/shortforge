// Archiver, restaurer et supprimer un projet. La suppression demande une confirmation explicite.
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Project } from "../api/types";
import { useProjectStore } from "../stores/project";
import { useToasts } from "../stores/toasts";
import { Btn, Dialog, Notice, Skeleton } from "./ds";

export function formatBytes(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} Ko`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1).replace(".", ",")} Mo`;
  return `${(bytes / 1024 ** 3).toFixed(2).replace(".", ",")} Go`;
}

/** Actions communes ; `onGone` est appele quand le projet quitte la liste (archive ou supprime). */
export function useProjectLifecycle() {
  const client = useQueryClient();
  const push = useToasts((s) => s.push);
  const { currentId, setCurrent } = useProjectStore();
  const refresh = (id: string) => {
    if (currentId === id) setCurrent(null);
    void client.invalidateQueries({ queryKey: ["projects"] });
    void client.invalidateQueries({ queryKey: ["validations"] });
  };
  const archive = useMutation({
    mutationFn: (p: Project) => api.archiveProject(p.id),
    onSuccess: (p) => { refresh(p.id); push(`« ${p.title} » est archivé. Tu peux le restaurer à tout moment.`, "success"); },
    onError: (e: Error) => push(e.message, "error"),
  });
  const unarchive = useMutation({
    mutationFn: (p: Project) => api.unarchiveProject(p.id),
    onSuccess: (p) => { void client.invalidateQueries({ queryKey: ["projects"] }); void client.invalidateQueries({ queryKey: ["validations"] }); push(`« ${p.title} » est de retour dans tes projets.`, "success"); },
    onError: (e: Error) => push(e.message, "error"),
  });
  return { archive, unarchive, refresh };
}

export function DeleteProjectDialog({ project, onClose }: { project: Project; onClose: () => void }) {
  const push = useToasts((s) => s.push);
  const { archive, refresh } = useProjectLifecycle();
  const [agreed, setAgreed] = useState(false);
  const footprint = useQuery({ queryKey: ["footprint", project.id], queryFn: () => api.projectFootprint(project.id) });
  const remove = useMutation({
    mutationFn: () => api.deleteProject(project.id),
    onSuccess: (res) => {
      refresh(project.id);
      push(`« ${res.title} » est supprimé. ${formatBytes(res.freed_bytes)} libérés.`, "success");
      if (res.leftover) push(`Le dossier n'a pas pu être effacé entièrement (fichier ouvert ?) : ${res.leftover}`, "error");
      onClose();
    },
    onError: (e: Error) => push(e.message, "error"),
  });
  const fp = footprint.data;
  return (
    <Dialog title={`Supprimer « ${project.title} » ?`} onClose={onClose}
      footer={(
        <>
          <Btn variant="ghost" onClick={onClose}>Annuler</Btn>
          {!project.archived_at && <Btn onClick={() => { archive.mutate(project); onClose(); }}>Archiver plutôt</Btn>}
          <Btn variant="danger" busy={remove.isPending} disabled={!agreed || !fp} onClick={() => remove.mutate()}>Supprimer définitivement</Btn>
        </>
      )}>
      <p><strong>Cette suppression est définitive</strong> : le projet ne pourra pas être récupéré.</p>
      {footprint.isLoading && <Skeleton className="h-16" />}
      {footprint.isError && <Notice tone="danger">Impossible de lire le contenu du projet : la suppression est bloquée par prudence.</Notice>}
      {fp && (
        <ul className="list-disc space-y-1 pl-5 text-sf-muted">
          <li>Le brief, les idées, toutes les versions du script et le storyboard.</li>
          <li>{fp.images} image(s), {fp.videos} clip(s) vidéo, {fp.audio} piste(s) de voix, {fp.renders} vidéo(s) exportée(s).</li>
          <li>{fp.files} fichier(s) sur le disque : <strong className="text-sf-text">{formatBytes(fp.bytes)} libérés</strong>.</li>
          <li>Ne sont pas touchés : ta bibliothèque musicale, ton logo, les vidéos longues importées et les dépenses déjà comptées dans le budget.</li>
        </ul>
      )}
      {fp && fp.scheduled_posts > 0 && (
        <Notice tone="warning" title={`${fp.scheduled_posts} publication(s) programmée(s)`}>
          Supprimer le projet ne les annule pas sur YouTube, TikTok ou Instagram : annule-les d'abord sur ces plateformes si besoin.
        </Notice>
      )}
      <label className="flex items-start gap-2">
        <input type="checkbox" className="mt-0.5 h-4 w-4 accent-red-600" checked={agreed} onChange={(e) => setAgreed(e.target.checked)} />
        Je comprends que la suppression est définitive.
      </label>
    </Dialog>
  );
}

/** Boutons « Archiver » et « Supprimer » d'une ligne de projet. */
export function ProjectRowActions({ project, compact = false }: { project: Project; compact?: boolean }) {
  const { archive, unarchive } = useProjectLifecycle();
  const [deleting, setDeleting] = useState(false);
  const cls = compact ? "min-h-[32px] px-2 text-xs" : "";
  return (
    <div className="flex flex-wrap gap-1">
      {project.archived_at
        ? <Btn variant="ghost" className={cls} busy={unarchive.isPending} onClick={() => unarchive.mutate(project)}>Restaurer</Btn>
        : <Btn variant="ghost" className={cls} busy={archive.isPending} onClick={() => archive.mutate(project)} aria-label={`Archiver ${project.title}`}>Archiver</Btn>}
      <Btn variant="ghost" className={`${cls} text-sf-danger`} onClick={() => setDeleting(true)} aria-label={`Supprimer ${project.title}`}>Supprimer…</Btn>
      {deleting && <DeleteProjectDialog project={project} onClose={() => setDeleting(false)} />}
    </div>
  );
}

/** Liste repliable des projets archives (restaurer ou supprimer). */
export function ArchivedProjects() {
  const [open, setOpen] = useState(false);
  const archived = useQuery({ queryKey: ["projects", "archived"], queryFn: api.archivedProjects });
  if (!archived.data?.length) return null;
  return (
    <div className="mt-4 border-t border-sf-border pt-3">
      <Btn variant="ghost" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        {open ? "Masquer" : "Voir"} les projets archivés ({archived.data.length})
      </Btn>
      {open && (
        <ul className="mt-2 divide-y divide-sf-border">
          {archived.data.map((p) => (
            <li key={p.id} className="flex flex-wrap items-center justify-between gap-3 py-2.5">
              <div className="min-w-0">
                <p className="truncate text-sf-muted">{p.title}</p>
                <p className="text-xs text-sf-muted">Archivé le {new Date(`${p.archived_at}Z`).toLocaleString("fr-FR", { dateStyle: "medium", timeStyle: "short" })}</p>
              </div>
              <ProjectRowActions project={p} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
