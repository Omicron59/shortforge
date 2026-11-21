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
  archived_at?: string | null;
}

/** Ce qu'une suppression definitive effacerait (dossier du projet et medias). */
export interface ProjectFootprint {
  project_id: string;
  title: string;
  bytes: number;
  files: number;
  images: number;
  videos: number;
  audio: number;
  renders: number;
  scheduled_posts: number;
  archived: boolean;
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

// ── Studio : voix, musique, marque, croissance, planning, videos longues, publications ──

export interface VoiceEngine { id: string; name: string; local: boolean; available: boolean; detail: string }
export interface VoiceState {
  settings: { engine: string; speed: number; enabled: boolean };
  engines: VoiceEngine[];
  elevenlabs_cost_per_1000_chars: number | null;
}
export interface SubtitlePreset { id: string; label: string; style: SubtitleStyle & { effect: string; highlight_color: string; words_per_line: number; box: boolean; bold: boolean } }
export interface MusicTrack { id: string; title: string; mood: string; license: string; volume: number; is_default: boolean }
export interface Brand {
  logo_position: string; logo_scale: number; logo_opacity: number; subtitle_preset: string; has_logo: boolean;
}
export interface CompetitorVideo {
  id: string; title: string; url: string; views: number; ratio: number; outlier: boolean; duration_s: number;
  recipe: { hook_type: string; structure: string[]; pacing: string; ending: string; why_it_works: string } | null;
  source: string;
}
export interface Competitor {
  id: string; platform: "youtube" | "tiktok"; handle: string; title: string; median_views: number;
  last_checked_at: string | null; videos: CompetitorVideo[];
}
export interface StyleProfile {
  tone?: string; sentence_length?: string; vocabulary?: string; expressions?: string[]; hooks?: string;
  structure?: string; avoid?: string; summary: string; samples: number; source: string; updated_at: string; enabled: boolean;
}
export interface PerformanceRow {
  project_id: string | null; title: string; platform: string; views: number; likes: number; comments: number;
  average_view_duration_s: number; hook: string; duration_s: number; collected_at: string;
}
export interface Insights { summary: string; what_works: string[]; avoid: string[]; next_week: string[]; based_on: number; updated_at: string }
export interface Slots { youtube: string; tiktok: string; instagram: string; days: number[]; per_day: number }
export interface PoolIdea { id: string; title: string; hook: string; potential_score: number; reuse_risk: string; original_angle: string }
export interface Validation {
  project_id: string; project_title: string; step: string; label: string; kind: string; message: string;
  planned_for: string | null; since: string;
}
export interface SourceVideo {
  id: string; title: string; duration_s: number; status: string; error: string | null; segments: number; busy: boolean;
  proposals: { start: number; end: number; title: string; hook: string; why: string }[];
}
export interface SocialPostT {
  id: string; platform: "youtube" | "tiktok" | "instagram"; label: string; enabled: boolean; caption: string;
  scheduled_at: string | null; method: "youtube_api" | "postiz" | "manual"; status: string; external_id: string | null; error: string | null;
}
export interface Onboarding {
  steps: { id: string; label: string; ok: boolean; help: string }[];
  done: boolean; data_dir: string; env_file: string; platform: string; free_space_gb: number;
}

export interface ComfyCheck {
  running: boolean; url: string; switched: boolean; checkpoints: string[]; expected_checkpoint: string;
  chosen_checkpoint: string; ready: boolean; message: string;
}

// --- Intelligence artificielle ---
export interface AiProviderInfo {
  id: string;
  label: string;
  type: string;
  mode: "local" | "cloud";
  billing: "free" | "subscription" | "usage";
  needs_key: boolean;
  key_set: boolean;
  key_hint: string;
  key_help: string;
  base_url: string;
  default_base_url: string;
  base_url_editable: boolean;
  /** Serveur local joignable (null pour un fournisseur cloud). */
  reachable: boolean | null;
  last_test: { ok: boolean; message: string; key_checked: boolean; at: string | null } | null;
}
/** Modele tel que le fournisseur le declare ; `null` = information non fournie. */
export interface AiModel {
  id: string;
  label: string;
  provider_id: string;
  mode: "local" | "cloud";
  paid: boolean | null;
  context_length: number | null;
  size_bytes: number | null;
  price_in_per_mtok: number | null;
  price_out_per_mtok: number | null;
  description: string;
}
export interface AiTask {
  task: string;
  label: string;
  is_default: boolean;
  mode: "local" | "cloud";
  configured: boolean;
  provider_id: string;
  provider_label: string;
  model: string;
  fallback_provider_id: string;
  fallback_model: string;
  allow_paid_fallback: boolean;
  temperature: number | null;
  max_tokens: number | null;
  strict_json: boolean;
  timeout_s: number | null;
}
export type AiTaskInput = Pick<AiTask, "provider_id" | "model"> &
  Partial<Omit<AiTask, "task" | "label" | "is_default" | "provider_label" | "mode" | "configured">> & { confirm_paid?: boolean; apply_to_all?: boolean };
export interface AiTestResult {
  ok: boolean;
  message: string;
  kind: string;
  key_checked: boolean;
  models_count: number | null;
}
export interface AiCall {
  id: string;
  at: string;
  task: string;
  provider_id: string;
  model: string;
  mode: string;
  ok: boolean;
  used_fallback: boolean;
  error_kind: string;
  error: string;
  duration_ms: number;
  input_tokens: number | null;
  output_tokens: number | null;
  cost_usd: number | null;
  billing: "free" | "subscription" | "usage";
}
export interface SecurityStatus {
  vault_available: boolean;
  vault_protection: string;
  vault_message: string;
  api_token_required: boolean;
  youtube_token_encrypted: boolean | null;
}
