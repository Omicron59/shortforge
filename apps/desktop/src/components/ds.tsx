// Composants de base du nouveau design (sombre, premium). Couleurs : jetons `sf-*` de tailwind.config.js.
// Regles : un seul bouton `primary` par ecran, focus toujours visible, transitions de 200 ms.
import { useEffect, useId, useState, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode } from "react";

const focus = "focus:outline-none focus-visible:ring-2 focus-visible:ring-sf-primary focus-visible:ring-offset-2 focus-visible:ring-offset-sf-bg";

export function Page({ title, subtitle, children }: { title: string; subtitle?: string; children: ReactNode }) {
  return (
    <div className="text-sf-text">
      <header className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {subtitle && <p className="mt-1 max-w-2xl text-sm text-sf-muted">{subtitle}</p>}
      </header>
      <div className="space-y-6">{children}</div>
    </div>
  );
}

export function Panel({ title, hint, actions, children }: { title?: string; hint?: string; actions?: ReactNode; children: ReactNode }) {
  return (
    <section className="rounded-sf border border-sf-border bg-sf-surface p-5 shadow-sf">
      {(title || actions) && (
        <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
          <div>
            {title && <h2 className="text-base font-medium">{title}</h2>}
            {hint && <p className="mt-0.5 text-sm text-sf-muted">{hint}</p>}
          </div>
          {actions}
        </div>
      )}
      {children}
    </section>
  );
}

type Variant = "primary" | "secondary" | "accent" | "ghost" | "danger";
const VARIANTS: Record<Variant, string> = {
  primary: "bg-sf-primary text-white hover:bg-sf-primary-hover",
  secondary: "border border-sf-border bg-sf-raised text-sf-text hover:border-sf-muted/50",
  accent: "border border-sf-primary/70 text-violet-200 hover:bg-sf-primary/15",
  ghost: "text-sf-muted hover:bg-sf-raised hover:text-sf-text",
  danger: "border border-sf-danger/40 text-sf-danger hover:bg-sf-danger/10",
};

export function Btn({ variant = "secondary", busy, className = "", children, disabled, ...props }:
  ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; busy?: boolean }) {
  return (
    <button
      type="button"
      disabled={disabled || busy}
      aria-busy={busy || undefined}
      className={`inline-flex min-h-[40px] items-center justify-center gap-2 rounded-xl px-4 text-sm font-medium transition duration-sf disabled:cursor-not-allowed disabled:opacity-50 ${focus} ${VARIANTS[variant]} ${className}`}
      {...props}
    >
      {busy && <span className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" aria-hidden />}
      {children}
    </button>
  );
}

/** Choix exclusif ou filtre : `aria-pressed` annonce l'etat aux lecteurs d'ecran. */
export function Pill({ active, onClick, children, dot }: { active: boolean; onClick: () => void; children: ReactNode; dot?: Tone }) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={`inline-flex min-h-[36px] items-center gap-2 rounded-full border px-3.5 text-sm transition duration-sf ${focus} ${
        active ? "border-sf-primary bg-sf-primary/15 text-sf-text" : "border-sf-border bg-sf-raised text-sf-muted hover:text-sf-text"}`}
    >
      {dot && <Dot tone={dot} />}
      {children}
    </button>
  );
}

export type Tone = "neutral" | "success" | "warning" | "danger" | "primary";
const DOTS: Record<Tone, string> = { neutral: "bg-sf-muted", success: "bg-sf-success", warning: "bg-sf-warning", danger: "bg-sf-danger", primary: "bg-sf-primary" };
const TAGS: Record<Tone, string> = {
  neutral: "border-sf-border text-sf-muted",
  success: "border-sf-success/40 text-sf-success",
  warning: "border-sf-warning/40 text-sf-warning",
  danger: "border-sf-danger/40 text-sf-danger",
  primary: "border-sf-primary/50 text-violet-300",
};

export function Dot({ tone }: { tone: Tone }) {
  return <span className={`inline-block h-2 w-2 shrink-0 rounded-full ${DOTS[tone]}`} aria-hidden />;
}

export function Tag({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return <span className={`inline-flex items-center rounded-md border px-1.5 py-0.5 text-xs ${TAGS[tone]}`}>{children}</span>;
}

/** Message d'etat : succes, avertissement, erreur ou information. */
export function Notice({ tone = "neutral", title, children }: { tone?: Tone; title?: string; children: ReactNode }) {
  const border = { neutral: "border-sf-border", success: "border-sf-success/40", warning: "border-sf-warning/40", danger: "border-sf-danger/40", primary: "border-sf-primary/40" }[tone];
  return (
    <div role={tone === "danger" ? "alert" : "status"} className={`flex gap-3 rounded-xl border bg-sf-raised px-4 py-3 text-sm ${border}`}>
      <span className="mt-1.5"><Dot tone={tone} /></span>
      <div className="min-w-0">
        {title && <p className="font-medium">{title}</p>}
        <div className="text-sf-muted">{children}</div>
      </div>
    </div>
  );
}

export const fieldClass = `w-full min-h-[40px] rounded-xl border border-sf-border bg-sf-bg px-3 text-sm text-sf-text placeholder:text-sf-muted/60 transition duration-sf focus:border-sf-primary disabled:opacity-60 ${focus}`;

export function Labeled({ label, hint, children }: { label: string; hint?: string; children: (id: string) => ReactNode }) {
  const id = useId();
  return (
    <div className="flex flex-col gap-1.5 text-sm">
      <label htmlFor={id} className="text-sf-text">{label}</label>
      {children(id)}
      {hint && <p className="text-xs text-sf-muted">{hint}</p>}
    </div>
  );
}

/** Champ de secret : la valeur saisie est masquee et n'est jamais relue depuis le moteur. */
export function SecretInput(props: InputHTMLAttributes<HTMLInputElement>) {
  const [shown, setShown] = useState(false);
  return (
    <div className="flex gap-2">
      <input {...props} type={shown ? "text" : "password"} autoComplete="off" spellCheck={false} className={fieldClass} />
      <Btn variant="ghost" onClick={() => setShown((v) => !v)} aria-label={shown ? "Masquer la clé" : "Afficher la clé saisie"}>
        {shown ? "Masquer" : "Afficher"}
      </Btn>
    </div>
  );
}

export function Skeleton({ className = "h-10" }: { className?: string }) {
  return <div className={`animate-pulse rounded-xl bg-sf-raised ${className}`} aria-hidden />;
}

/** Fenetre de confirmation : Echap ferme, le fond est inerte. */
export function Dialog({ title, onClose, children, footer }: { title: string; onClose: () => void; children: ReactNode; footer: ReactNode }) {
  const id = useId();
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/60 p-4 sm:items-center" onClick={onClose}>
      <div role="dialog" aria-modal="true" aria-labelledby={id} onClick={(e) => e.stopPropagation()}
        className="w-full max-w-lg rounded-sf border border-sf-border bg-sf-surface p-5 text-sf-text shadow-sf">
        <h2 id={id} className="text-lg font-medium">{title}</h2>
        <div className="mt-3 space-y-3 text-sm">{children}</div>
        <div className="mt-5 flex flex-wrap justify-end gap-2">{footer}</div>
      </div>
    </div>
  );
}

/** Section repliee par defaut (parametres avances). */
export function Collapsible({ label, children }: { label: string; children: ReactNode }) {
  return (
    <details className="group rounded-xl border border-sf-border bg-sf-raised">
      <summary className={`cursor-pointer list-none rounded-xl px-4 py-2.5 text-sm text-sf-muted transition duration-sf hover:text-sf-text ${focus}`}>
        <span className="mr-2 inline-block transition duration-sf group-open:rotate-90" aria-hidden>›</span>{label}
      </summary>
      <div className="border-t border-sf-border p-4">{children}</div>
    </details>
  );
}
