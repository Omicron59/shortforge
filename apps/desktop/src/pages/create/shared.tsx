// Elements communs aux 4 etapes du parcours de creation.
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { Link, NavLink } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "../../api/client";
import { wizard, type Engine, type WizardState } from "../../api/wizard";
import { Btn, Dialog, Dot, Notice, Skeleton } from "../../components/ds";

export const message = (error: unknown) => (error instanceof Error ? error.message : "Erreur inconnue.");
export const stateKey = (id: string) => ["wizard", id] as const;

export function useWizard(id: string) {
  const client = useQueryClient();
  const query = useQuery({ queryKey: stateKey(id), queryFn: () => wizard.state(id) });
  const set = useCallback((state: WizardState) => client.setQueryData(stateKey(id), state), [client, id]);
  return { ...query, set };
}

const STEPS = [
  { key: "brief", label: "Brief" },
  { key: "idees", label: "Idées" },
  { key: "script", label: "Script" },
  { key: "studio", label: "Studio" },
] as const;

/** Navigation entre les etapes : on peut revenir en arriere sans rien perdre. */
export function Stepper({ id, state }: { id?: string; state?: WizardState }) {
  const reached = !state ? 0 : state.step === "studio" ? 3 : state.script ? 2 : 1;
  return (
    <nav aria-label="Étapes de création" className="mb-6">
      <ol className="flex flex-wrap gap-2">
        {STEPS.map((step, index) => {
          const open = !!id && index <= Math.max(reached, state?.selected_idea_id ? 2 : 1);
          const body = (
            <>
              <span className="flex h-6 w-6 items-center justify-center rounded-full border border-current text-xs">{index + 1}</span>
              {step.label}
            </>
          );
          const cls = "inline-flex min-h-[40px] items-center gap-2 rounded-full border px-4 text-sm transition duration-sf focus:outline-none focus-visible:ring-2 focus-visible:ring-sf-primary";
          return (
            <li key={step.key}>
              {open ? (
                <NavLink to={`/creer/${id}/${step.key}`} className={({ isActive }) => `${cls} ${isActive ? "border-sf-primary bg-sf-primary/15 text-sf-text" : "border-sf-border text-sf-muted hover:text-sf-text"}`}>{body}</NavLink>
              ) : (
                <span aria-disabled="true" aria-current={!id && index === 0 ? "step" : undefined}
                  className={`${cls} ${!id && index === 0 ? "border-sf-primary bg-sf-primary/15 text-sf-text" : "border-sf-border text-sf-muted/50"}`}>{body}</span>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

/** Moteur prevu ou utilise, affiche discretement. Les reglages restent dans leur page. */
export function EngineNote({ engine, used }: { engine?: Engine; used?: Engine | null }) {
  const shown = used ?? engine;
  if (!shown) return null;
  if (!used && engine && !engine.configured) return null;
  return (
    <p className="flex flex-wrap items-center gap-1.5 text-xs text-sf-muted">
      <Dot tone={shown.mode === "local" ? "success" : "primary"} />
      {used ? "Généré avec" : "Modèle"} : {shown.provider_label} · {shown.model} · {shown.mode === "local" ? "sur ton PC" : "dans le cloud"}
      {used?.used_fallback && <span className="text-sf-warning">(modèle de secours utilisé)</span>}
    </p>
  );
}

export function NoModel({ engine, children }: { engine?: Engine; children?: ReactNode }) {
  if (!engine || engine.configured) return null;
  return (
    <Notice tone="warning" title="Aucun modèle de texte prêt pour cette étape">
      <p>{engine.model ? `${engine.provider_label} demande une clé API qui n'est pas enregistrée.` : "Aucun modèle n'est choisi."} Ce que tu as saisi est conservé.</p>
      <div className="mt-2 flex flex-wrap gap-2">
        <Link to="/parametres/ia" className="inline-flex min-h-[40px] items-center rounded-xl border border-sf-border bg-sf-surface px-4 text-sm text-sf-text hover:border-sf-muted/50 focus:outline-none focus-visible:ring-2 focus-visible:ring-sf-primary">Ouvrir les réglages IA</Link>
        {children}
      </div>
    </Notice>
  );
}

export type SaveStatus = "idle" | "saving" | "saved" | "error";

export function SaveBadge({ status, label }: { status: SaveStatus; label?: string }) {
  const text = { idle: label ?? "Brouillon enregistré", saving: "Enregistrement…", saved: "Enregistré", error: "Échec de l'enregistrement" }[status];
  const tone = status === "error" ? "danger" : status === "saving" ? "warning" : "success";
  if (!text) return null; // rien a dire tant que rien n'a ete modifie
  return <span role="status" className="inline-flex items-center gap-1.5 text-xs text-sf-muted"><Dot tone={tone} />{text}</span>;
}

/** Enregistre `value` apres une courte pause de saisie. Ne lance rien tant que la valeur n'a pas change. */
export function useAutosave<T>(value: T, save: (value: T) => Promise<unknown>, enabled = true, delay = 700): SaveStatus {
  const [status, setStatus] = useState<SaveStatus>("idle");
  const last = useRef(JSON.stringify(value));
  const saver = useRef(save);
  saver.current = save;
  useEffect(() => {
    const text = JSON.stringify(value);
    if (!enabled || text === last.current) return;
    setStatus("saving");
    const timer = setTimeout(() => {
      saver.current(value).then(() => { last.current = text; setStatus("saved"); }, () => setStatus("error"));
    }, delay);
    return () => clearTimeout(timer);
  }, [value, enabled, delay]);
  return status;
}

/** Une generation en cours : duree reelle affichee (pas de faux pourcentage) et annulation. */
export function useGeneration() {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [seconds, setSeconds] = useState(0);
  const current = useRef<{ id: string; controller: AbortController } | null>(null);

  useEffect(() => {
    if (!busy) return;
    setSeconds(0);
    const timer = setInterval(() => setSeconds((s) => s + 1), 1000);
    return () => clearInterval(timer);
  }, [busy]);
  useEffect(() => () => current.current?.controller.abort(), []);

  const run = useCallback(async <T,>(label: string, call: (requestId: string, signal: AbortSignal) => Promise<T>): Promise<T | undefined> => {
    if (current.current) return undefined;
    const job = { id: crypto.randomUUID(), controller: new AbortController() };
    current.current = job;
    setBusy(label);
    setError(null);
    try {
      return await call(job.id, job.controller.signal);
    } catch (err) {
      if (!job.controller.signal.aborted) setError(err);
      return undefined;
    } finally {
      current.current = null;
      setBusy(null);
    }
  }, []);

  const cancel = useCallback(() => {
    const job = current.current;
    if (!job) return;
    void wizard.cancel(job.id).catch(() => undefined); // le resultat sera ignore par le moteur
    job.controller.abort();
  }, []);

  return { busy, error, seconds, run, cancel, clearError: () => setError(null) };
}

export function Generating({ gen }: { gen: ReturnType<typeof useGeneration> }) {
  if (gen.busy) {
    return (
      <Notice tone="primary" title={gen.busy}>
        <p>En cours depuis {gen.seconds} s. La durée dépend du modèle ; aucune estimation fiable n'est disponible.</p>
        <Btn className="mt-2" onClick={gen.cancel}>Annuler</Btn>
      </Notice>
    );
  }
  if (!gen.error) return null;
  const err = gen.error;
  const title = err instanceof ApiError && err.status === 0 ? "Connexion au moteur perdue"
    : err instanceof ApiError && err.kind === "quota" ? "Quota du fournisseur atteint"
    : err instanceof ApiError && err.kind === "invalid_key" ? "Clé API refusée"
    : err instanceof ApiError && err.kind === "needs_paid_confirmation" ? "Modèle payant non autorisé"
    : "La génération a échoué";
  return (
    <Notice tone="danger" title={title}>
      <p>{message(err)} Rien n'a été perdu.</p>
      <div className="mt-2 flex flex-wrap gap-2">
        <Btn onClick={gen.clearError}>Fermer</Btn>
        <Link to="/parametres/ia" className="inline-flex min-h-[40px] items-center px-2 text-sm text-violet-300 underline">Réglages IA</Link>
      </div>
    </Notice>
  );
}

export function Confirm({ title, children, confirm, danger, onConfirm, onClose, busy }: {
  title: string; children: ReactNode; confirm: string; danger?: boolean; onConfirm: () => void; onClose: () => void; busy?: boolean;
}) {
  return (
    <Dialog title={title} onClose={onClose}
      footer={<><Btn variant="ghost" onClick={onClose}>Annuler</Btn><Btn variant={danger ? "danger" : "primary"} busy={busy} onClick={onConfirm}>{confirm}</Btn></>}>
      {children}
    </Dialog>
  );
}

export function StateGate({ query, children }: { query: ReturnType<typeof useWizard>; children: (state: WizardState) => ReactNode }) {
  if (query.isLoading) return <div className="space-y-3"><Skeleton className="h-10 w-80" /><Skeleton className="h-40" /></div>;
  if (query.isError || !query.data) {
    return (
      <Notice tone="danger" title="Projet introuvable ou moteur injoignable">
        <p>{message(query.error)}</p>
        <Btn className="mt-2" onClick={() => void query.refetch()}>Réessayer</Btn>
      </Notice>
    );
  }
  return <>{children(query.data)}</>;
}
