// Types des reponses de l'API locale (miroir de backend/shortforge/schemas.py).

export type StepStatus = "pending" | "running" | "done" | "failed" | "needs_validation" | "cancelled";
export type VideoMode = "economique" | "standard" | "premium" | "personnalise";
export type Importance = "simple" | "transition" | "important" | "exceptional";

export interface ConfirmationItem {
  scene_id: string;
  position: number;
  provider_id: string;
  provider: string;
  duration_s: number;
  estimated_cost_usd: number | null;
  message: string;
}

export interface Step {
  name: string;
  label: string;
  position: number;
  status: StepStatus;
  human_gate: boolean;
  attempts: number;
  output: (Record<string, unknown> & { confirmation_required?: ConfirmationItem[]; message?: string }) | null;
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
  validated_at: string | null;
  validated_by: string | null;
}

export interface Project {
  id: string;
  title: string;
  niche: string;
  language: string;
  status: string;
  current_step: string | null;
  video_mode: VideoMode;
  default_provider: string;
  engine_scope: "scene" | "short";
  created_at: string;
  updated_at: string;
}

export interface ProjectDetail extends Project {
  steps: Step[];
}

export interface Idea {
  id: string;
  title: string;
  hook: string;
  original_angle: string;
  estimated_duration_s: number;
  potential_score: number;
  keywords: string[];
  reuse_risk: "low" | "medium" | "high";
  visual_style: string;
  sources: string[];
  selected: boolean;
}

export interface Scene {
  id: string;
  position: number;
  text: string;
  visual_prompt: string;
  negative_prompt: string;
  transition: string;
  duration_s: number;
  importance: Importance;
  provider_id: string | null;
  provider_locked: boolean;
  provider_reason: string;
  estimated_cost_usd: number;
  seed: number | null;
  image_status: string;
  status: string;
}

export interface Script {
  id: string;
  version: number;
  hook: string;
  body: string;
  conclusion: string;
  call_to_action: string;
  estimated_duration_s: number;
  status: "draft" | "approved" | "rejected";
}

export interface ScriptDetail {
  script: Script;
  scenes: Scene[];
  warnings: string[];
}

export interface SceneEdit {
  text: string;
  visual_prompt: string;
  negative_prompt: string;
  transition: string;
  duration_s: number;
  importance: Importance;
}

export interface Provider {
  id: string;
  name: string;
  kind: "local" | "external";
  tier: string;
  enabled: boolean;
  is_default: boolean;
  cost_per_second_usd: number | null;
  config: Record<string, string>;
  configured: boolean;
  configuration_hint: string;
  operations: string[];
}

export interface Budget {
  budget_max_per_scene: number;
  budget_max_per_short: number;
  budget_max_per_day: number;
  budget_max_per_month: number;
  spent_today: number;
  spent_month: number;
  remaining_today: number;
  remaining_month: number;
}

export interface Cost {
  id: number;
  project_id: string | null;
  scene_id: string | null;
  provider_id: string | null;
  amount_usd: number;
  kind: "confirmation" | "actual";
  description: string;
  created_at: string;
}

export interface CostEstimate {
  scenes: { scene_id: string; position: number; provider: string; duration_s: number; estimated_cost_usd: number | null }[];
  estimated_total_usd: number;
  pending_confirmations: ConfirmationItem[];
  budget: Budget;
}

export interface Health {
  status: "ok";
  version: string;
  database: string;
  youtube_publish_enabled: boolean;
}

export interface ServicesStatus {
  comfyui: { running: boolean; url: string };
  ollama: { running: boolean; model: string };
  ffmpeg: { available: boolean; path: string };
  gpu: { available: boolean; name: string; vram_total_mb: number; vram_free_mb: number };
}

export interface AppSettings {
  engine_rules: Record<Importance, string>;
  preset_rules: Record<string, Record<Importance, string>>;
  manual_trends: string[];
  comfyui_image_workflow: string;
  youtube_publish_enabled: boolean;
}

export interface Workflow {
  id: string;
  name: string;
  kind: "image" | "video";
  inputs: string[];
  user: boolean;
}

export interface Asset {
  id: string;
  project_id: string;
  scene_id: string | null;
  kind: string;
  mime_type: string;
  origin: string;
  created_at: string;
}

export interface Job {
  id: string;
  provider_id: string;
  project_id: string;
  scene_id: string | null;
  operation: string;
  status: string;
  estimated_cost_usd: number;
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface HistoryEvent {
  at: string | null;
  type: string;
  project_id: string | null;
  project_title: string;
  label: string;
  detail: string;
  amount_usd: number | null;
}

export interface Stats {
  projects_total: number;
  projects_by_status: Record<string, number>;
  ideas_total: number;
  scenes_total: number;
  images_total: number;
  videos_total: number;
  jobs_by_status: Record<string, number>;
  scenes_by_provider: Record<string, number>;
  spent_total_usd: number;
  spent_by_provider: Record<string, number>;
  spent_by_month: Record<string, number>;
  youtube: { available: boolean; message: string };
}

export interface Render {
  id: string;
  asset_id: string | null;
  width: number;
  height: number;
  codec: string;
  status: string;
  approved_at: string | null;
  approved_by: string | null;
  created_at: string;
}

export interface YoutubeDraft {
  id: string;
  title: string;
  description: string;
  tags: string[];
  privacy: "private" | "unlisted" | "public";
  made_for_kids: boolean;
  ai_disclosure: boolean;
  status: "draft" | "uploading" | "published" | "failed";
  youtube_video_id: string | null;
  error: string | null;
  human_approved_by: string | null;
}

export interface FinalCheck {
  ready: boolean;
  checks: { id: string; label: string; ok: boolean; detail: string }[];
}

export interface YoutubeStatus {
  publish_enabled: boolean;
  client_secrets_configured: boolean;
  channel: { id: string; title: string } | null;
  ai_disclosure_text: string;
}

export interface SubtitleStyle {
  font: string;
  size: number;
  color: string;
  outline_color: string;
  outline: number;
  position: "bottom" | "middle" | "top";
  uppercase: boolean;
}

export interface SubtitleInfo {
  segments: { start: number; end: number; text: string }[];
  position: "bottom" | "middle" | "top";
  style: SubtitleStyle;
}
