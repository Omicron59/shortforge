// Client du nouveau parcours de creation (brief, idees, script et storyboard, studio).
import { fileUrl, request } from "./client";
import type { Idea, ProjectDetail, Scene } from "./types";

export interface Brief {
  subject: string;
  niche: string;
  audience: string;
  goal: string;
  language: string;
  tone: string;
  duration_s: number;
  platform: string;
  visual_style: string;
  constraints: string;
  avoid: string;
}
export interface WizardOptions {
  goals: Record<string, string>;
  tones: Record<string, string>;
  platforms: Record<string, string>;
  languages: Record<string, string>;
  durations: number[];
  defaults: Brief;
}
/** Moteur prevu ou utilise pour une tache : jamais invente, il vient du routeur du moteur local. */
export interface Engine {
  task: string;
  provider_id: string;
  provider_label: string;
  model: string;
  mode: "local" | "cloud";
  configured?: boolean;
  used_fallback?: boolean;
}
export type WizardIdea = Idea & {
  summary: string;
  difficulty: string;
  resources: string[];
  fit_reason: string;
  saved: boolean;
  batch: number;
  parent_id: string | null;
};
export type WizardScene = Scene & { on_screen_text: string; visual_intent: string };
export interface WizardScript {
  id: string;
  version: number;
  status: string;
  call_to_action: string;
  estimated_duration_s: number;
  scenes: WizardScene[];
}
export interface WizardState {
  project: ProjectDetail;
  brief: Brief;
  step: "ideas" | "script" | "studio";
  ideas: WizardIdea[];
  selected_idea_id: string | null;
  script: WizardScript | null;
  script_approved: boolean;
  problems: string[];
  stale: { images: string[]; voice: boolean; subtitles: boolean; render: boolean };
  engines: Record<string, Engine>;
  new_idea_ids?: string[];
  rejected?: string[];
  used?: Engine | null;
  warning?: string;
  scene_id?: string;
}
export interface ScriptVersion {
  version: number;
  current: boolean;
  scenes: number;
  updated_at: string;
  preview: string;
}
export type SceneField = "text" | "on_screen_text" | "visual_prompt";
export type ScenePatch = Partial<Pick<WizardScene, "text" | "on_screen_text" | "visual_intent" | "visual_prompt" | "transition">>;

const json = (method: string, body?: unknown, signal?: AbortSignal): RequestInit => ({ method, body: JSON.stringify(body ?? {}), signal });
const base = "/api/wizard";

export const wizard = {
  options: () => request<WizardOptions>(`${base}/options`),
  engines: () => request<Record<string, Engine>>(`${base}/engines`),
  create: (brief: Brief) => request<WizardState>(`${base}/projects`, json("POST", brief)),
  state: (id: string) => request<WizardState>(`${base}/projects/${id}`),
  saveBrief: (id: string, brief: Brief) => request<Brief>(`${base}/projects/${id}/brief`, json("PUT", brief)),
  cancel: (requestId: string) => request<{ cancelled: boolean }>(`${base}/cancel/${requestId}`, json("POST")),

  ideas: (id: string, requestId: string, signal: AbortSignal, variantOf?: string) =>
    request<WizardState>(`${base}/projects/${id}/ideas`, json("POST", { request_id: requestId, variant_of: variantOf ?? null }, signal)),
  patchIdea: (ideaId: string, body: Partial<Pick<WizardIdea, "title" | "hook" | "original_angle" | "summary" | "saved">>) =>
    request<WizardIdea>(`${base}/ideas/${ideaId}`, json("PATCH", body)),
  choose: (id: string, ideaId: string) => request<WizardState>(`${base}/projects/${id}/ideas/${ideaId}/choose`, json("POST")),

  generateScript: (id: string, requestId: string, signal: AbortSignal) =>
    request<WizardState>(`${base}/projects/${id}/script/generate`, json("POST", { request_id: requestId }, signal)),
  manualScript: (id: string) => request<WizardState>(`${base}/projects/${id}/script/manual`, json("POST")),
  transform: (id: string, requestId: string, signal: AbortSignal, body: { kind: "shorten" | "tone"; tone?: string }) =>
    request<WizardState>(`${base}/projects/${id}/script/transform`, json("POST", { request_id: requestId, ...body }, signal)),
  hooks: (id: string, requestId: string, signal: AbortSignal) =>
    request<{ hooks: string[]; used: Engine | null }>(`${base}/projects/${id}/script/hooks`, json("POST", { request_id: requestId }, signal)),
  patchScript: (id: string, body: { call_to_action: string }) => request<WizardState>(`${base}/projects/${id}/script`, json("PUT", body)),
  versions: (id: string) => request<ScriptVersion[]>(`${base}/projects/${id}/script/versions`),
  snapshot: (id: string) => request<ScriptVersion[]>(`${base}/projects/${id}/script/snapshot`, json("POST")),
  restore: (id: string, version: number) => request<WizardState>(`${base}/projects/${id}/script/versions/${version}/restore`, json("POST")),
  approve: (id: string) => request<WizardState>(`${base}/projects/${id}/script/approve`, json("POST")),
  reopen: (id: string) => request<WizardState>(`${base}/projects/${id}/script/reopen`, json("POST")),

  addScene: (id: string, after: number | null) => request<WizardState>(`${base}/projects/${id}/scenes`, json("POST", { after })),
  reorder: (id: string, ids: string[]) => request<WizardState>(`${base}/projects/${id}/scenes/order`, json("PUT", { ids })),
  patchScene: (sceneId: string, body: ScenePatch) => request<WizardScene>(`${base}/scenes/${sceneId}`, json("PATCH", body)),
  deleteScene: (sceneId: string) => request<WizardState>(`${base}/scenes/${sceneId}`, { method: "DELETE" }),
  regenerateField: (sceneId: string, field: SceneField, requestId: string, signal: AbortSignal) =>
    request<{ scene: WizardScene; used: Engine | null }>(`${base}/scenes/${sceneId}/regenerate-field`, json("POST", { request_id: requestId, field }, signal)),
  duplicate: (id: string) => request<WizardState>(`${base}/projects/${id}/duplicate`, json("POST")),
  imageUploadPath: (sceneId: string) => `${base}/scenes/${sceneId}/image`,
};

export { fileUrl };
