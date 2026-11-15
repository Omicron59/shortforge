// Composants d'interface reutilisables.
import type { ButtonHTMLAttributes, ReactNode } from "react";
import type { StepStatus } from "../api/types";
import { STEP_STATUS_LABELS } from "../lib/format";

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: ReactNode }) {
  return (
    <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-2xl font-semibold">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-zinc-400">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </header>
  );
}

export function Card({ title, children, actions, className = "" }: {
  title?: string;
  children: ReactNode;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <section className={`rounded-xl border border-zinc-800 bg-zinc-900/60 p-5 ${className}`}>
      {(title || actions) && (
        <div className="mb-4 flex items-center justify-between gap-3">
          {title && <h2 className="font-medium text-zinc-200">{title}</h2>}
          {actions}
        </div>
      )}
      {children}
    </section>
  );
}

type Variant = "primary" | "secondary" | "danger" | "ghost";
const VARIANTS: Record<Variant, string> = {
  primary: "bg-violet-600 text-white hover:bg-violet-500",
  secondary: "bg-zinc-800 text-zinc-100 hover:bg-zinc-700",
  danger: "bg-red-700/80 text-white hover:bg-red-600",
  ghost: "text-zinc-300 hover:bg-zinc-800",
};

export function Button({ variant = "secondary", busy, className = "", children, disabled, ...props }:
  ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; busy?: boolean }) {
  return (
    <button
      type="button"
      disabled={disabled || busy}
      className={`inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-50 ${VARIANTS[variant]} ${className}`}
      {...props}
    >
      {busy && <Spinner />}
      {children}
    </button>
  );
}

export function Spinner() {
  return <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" />;
}

const TONES = {
  zinc: "bg-zinc-800 text-zinc-300",
  green: "bg-emerald-900/60 text-emerald-300",
  yellow: "bg-amber-900/60 text-amber-300",
  red: "bg-red-900/60 text-red-300",
  blue: "bg-sky-900/60 text-sky-300",
  violet: "bg-violet-900/60 text-violet-300",
};
export type Tone = keyof typeof TONES;

export function Badge({ tone = "zinc", children }: { tone?: Tone; children: ReactNode }) {
  return <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${TONES[tone]}`}>{children}</span>;
}

const STATUS_TONES: Record<StepStatus, Tone> = {
  pending: "zinc",
  running: "blue",
  done: "green",
  failed: "red",
  needs_validation: "yellow",
  cancelled: "zinc",
};

export function StatusBadge({ status }: { status: StepStatus }) {
  return (
    <Badge tone={STATUS_TONES[status]}>
      {status === "running" && <span className="mr-1 h-1.5 w-1.5 animate-pulse rounded-full bg-current" />}
      {STEP_STATUS_LABELS[status]}
    </Badge>
  );
}

export function Alert({ tone = "yellow", title, children }: { tone?: "yellow" | "red" | "blue" | "green"; title?: string; children: ReactNode }) {
  const styles = {
    yellow: "border-amber-700/60 bg-amber-950/40 text-amber-200",
    red: "border-red-700/60 bg-red-950/40 text-red-200",
    blue: "border-sky-700/60 bg-sky-950/40 text-sky-200",
    green: "border-emerald-700/60 bg-emerald-950/40 text-emerald-200",
  }[tone];
  return (
    <div className={`rounded-lg border px-4 py-3 text-sm ${styles}`}>
      {title && <p className="mb-1 font-medium">{title}</p>}
      <div className="whitespace-pre-line">{children}</div>
    </div>
  );
}

export function Empty({ children, action }: { children: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed border-zinc-800 p-10 text-center text-sm text-zinc-400">
      {children}
      {action}
    </div>
  );
}

export function Loading({ label = "Chargement…" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 p-6 text-sm text-zinc-400">
      <Spinner /> {label}
    </div>
  );
}

export function ErrorBox({ error }: { error: unknown }) {
  return <Alert tone="red">{error instanceof Error ? error.message : "Erreur inconnue."}</Alert>;
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1 text-sm">
      <span className="text-zinc-300">{label}</span>
      {children}
      {hint && <span className="text-xs text-zinc-500">{hint}</span>}
    </label>
  );
}

export const inputClass =
  "w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100 placeholder:text-zinc-600 focus:border-violet-500 focus:outline-none disabled:opacity-60";

export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-4">
      <p className="text-xs uppercase tracking-wide text-zinc-500">{label}</p>
      <p className="mt-1 text-2xl font-semibold">{value}</p>
      {hint && <p className="mt-1 text-xs text-zinc-500">{hint}</p>}
    </div>
  );
}

/** Barre horizontale simple (statistiques et budget). */
export function Meter({ value, max, tone = "violet" }: { value: number; max: number; tone?: "violet" | "red" | "green" }) {
  const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0;
  const color = { violet: "bg-violet-500", red: "bg-red-500", green: "bg-emerald-500" }[tone];
  return (
    <div className="h-2 w-full overflow-hidden rounded-full bg-zinc-800">
      <div className={`h-full ${color}`} style={{ width: `${pct}%` }} />
    </div>
  );
}
