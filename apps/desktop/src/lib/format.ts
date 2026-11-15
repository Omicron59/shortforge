// Mise en forme en francais : montants, durees, dates et libelles.
import type { Importance, StepStatus } from "../api/types";

const amountFormat = new Intl.NumberFormat("fr-FR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

/** Montant en dollars, a la francaise : « 0,35 $ ». */
export const usd = (value: number | null | undefined) =>
  value === null || value === undefined ? "tarif inconnu" : `${amountFormat.format(value)} $`;

export const seconds = (value: number) => `${Number(value.toFixed(1)).toLocaleString("fr-FR")} s`;

export function dateTime(value: string | null | undefined): string {
  if (!value) return "—";
  // Le backend renvoie des dates UTC sans fuseau.
  const date = new Date(/[zZ+]/.test(value.slice(10)) ? value : `${value}Z`);
  return date.toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" });
}

export const STEP_STATUS_LABELS: Record<StepStatus, string> = {
  pending: "En attente",
  running: "En cours",
  done: "Terminé",
  failed: "Échec",
  needs_validation: "À valider",
  cancelled: "Annulé",
};

export const PROJECT_STATUS_LABELS: Record<string, string> = {
  draft: "Brouillon",
  in_progress: "En production",
  done: "Terminé",
  cancelled: "Annulé",
};

export const IMPORTANCE_LABELS: Record<Importance, string> = {
  simple: "Simple",
  transition: "Transition",
  important: "Importante",
  exceptional: "Exceptionnelle",
};

export const VIDEO_MODE_LABELS: Record<string, string> = {
  economique: "Économique (100 % local)",
  standard: "Standard (Gemini Omni pour les scènes importantes)",
  premium: "Premium (Veo 3 pour les scènes exceptionnelles)",
  personnalise: "Personnalisé (mes règles)",
};

export const TRANSITION_LABELS: Record<string, string> = {
  cut: "Coupe",
  fondu: "Fondu",
  zoom: "Zoom",
  glissement: "Glissement",
  flash: "Flash",
};

export const REUSE_RISK_LABELS: Record<string, string> = {
  low: "Risque faible",
  medium: "Risque moyen",
  high: "Risque élevé",
};

export const JOB_STATUS_LABELS: Record<string, string> = {
  pending: "En attente",
  queued: "Dans la file",
  running: "En cours",
  succeeded: "Réussi",
  failed: "Échec",
};

export const OPERATION_LABELS: Record<string, string> = {
  generate_from_text: "Texte → vidéo",
  generate_from_image: "Image → vidéo",
  generate_from_first_and_last_frame: "Première et dernière image",
  edit_video: "Modification",
};

export const LANGUAGES: Record<string, string> = { fr: "Français", en: "Anglais", es: "Espagnol", de: "Allemand" };

/** Duree parlee estimee (meme regle que le backend : 2,5 mots par seconde). */
export const spokenDuration = (text: string) => text.split(/\s+/).filter(Boolean).length / 2.5;
