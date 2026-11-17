// Client de l'API locale ShortForge (backend FastAPI sur http://127.0.0.1:8787).
import type {
  AppSettings,
  Asset,
  Budget,
  Cost,
  CostEstimate,
  Health,
  HistoryEvent,
  Idea,
  Importance,
  Job,
  Project,
  ProjectDetail,
  Provider,
  Scene,
  SceneEdit,
  ScriptDetail,
  ServicesStatus,
  Stats,
  Step,
  VideoMode,
  Workflow,
  Render,
  YoutubeDraft,
  FinalCheck,
  YoutubeStatus,
  SubtitleInfo,
  SubtitleStyle,
  VoiceState,
  SubtitlePreset,
  MusicTrack,
  Brand,
  Competitor,
  CompetitorVideo,
  StyleProfile,
  PerformanceRow,
  Insights,
  Slots,
  PoolIdea,
  Validation,
  SourceVideo,
  SocialPostT,
  Onboarding,
  ComfyCheck,
  AiProviderInfo,
  AiModel,
  AiTask,
  AiTaskInput,
  AiTestResult,
  AiCall,
  SecurityStatus,
} from "./types";

export const API_URL: string = import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8787";

export class ApiError extends Error {
  /** `kind` : raison donnee par le moteur (invalid_key, quota, needs_paid_confirmation...). */
  constructor(message: string, readonly status: number, readonly kind = "") {
    super(message);
  }
}

// Jeton de session de l'API locale, donne par l'application de bureau au lancement (vide en developpement).
let apiToken = "";

/** A appeler une fois avant d'afficher l'interface. */
export async function initApiToken(): Promise<void> {
  if (!("__TAURI_INTERNALS__" in window)) return;
  try {
    const { invoke } = await import("@tauri-apps/api/core");
    apiToken = await invoke<string>("api_token");
  } catch {
    apiToken = "";
  }
}

const authHeaders = (): Record<string, string> => (apiToken ? { Authorization: `Bearer ${apiToken}` } : {});

/** Adresse d'un fichier du moteur pour une balise image, audio ou video (qui ne peut pas envoyer d'en-tete). */
export function fileUrl(path: string, params: Record<string, string | number> = {}): string {
  const query = new URLSearchParams(Object.fromEntries(Object.entries(params).map(([k, v]) => [k, String(v)])));
  if (apiToken) query.set("token", apiToken);
  const text = query.toString();
  return `${API_URL}${path}${text ? `?${text}` : ""}`;
}

function errorMessage(status: number, body: unknown): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return "Valeur refusée : vérifie les champs saisis.";
  return `Erreur ${status}`;
}

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, { headers: { "Content-Type": "application/json", ...authHeaders() }, ...init });
  } catch {
    throw new ApiError("Moteur local injoignable : lance le backend (python -m shortforge).", 0);
  }
  const body: unknown = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(errorMessage(res.status, body), res.status, String((body as { kind?: unknown } | null)?.kind ?? ""));
  return body as T;
}

export const get = <T,>(path: string) => request<T>(path);
const send = <T,>(method: string, path: string, body?: unknown) =>
  request<T>(path, { method, body: body === undefined ? undefined : JSON.stringify(body) });

/** Envoi d'un fichier brut (musique, logo, video longue) : le backend l'ecrit par morceaux. */
export async function upload<T>(path: string, file: File, params: Record<string, string | number | boolean>): Promise<T> {
  const query = new URLSearchParams({ filename: file.name, ...Object.fromEntries(Object.entries(params).map(([k, v]) => [k, String(v)])) });
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}?${query}`, { method: "PUT", body: file, headers: authHeaders() });
  } catch {
    throw new ApiError("Moteur local injoignable : lance le backend.", 0);
  }
  const body: unknown = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(errorMessage(res.status, body), res.status);
  return body as T;
}

export const assetUrl = (assetId: string) => fileUrl(`/api/assets/${assetId}/file`);
export const eventsUrl = (projectId: string) => fileUrl(`/api/projects/${projectId}/events`).replace(/^http/, "ws");

type ScriptPatch = Partial<{ hook: string; body: string; conclusion: string; call_to_action: string; scenes: SceneEdit[] }>;
type ScenePatch = Partial<{
  provider_id: string;
  importance: Importance;
  visual_prompt: string;
  negative_prompt: string;
  duration_s: number;
  transition: string;
}>;
type EnginePatch = Partial<{ video_mode: VideoMode; engine_scope: "scene" | "short"; default_provider: string }>;
type BudgetPatch = Partial<
  Pick<Budget, "budget_max_per_scene" | "budget_max_per_short" | "budget_max_per_day" | "budget_max_per_month">
>;
type ProviderPatch = Partial<{ enabled: boolean; cost_per_second_usd: number; config: Record<string, string> }>;
type SettingsPatch = Partial<Pick<AppSettings, "engine_rules" | "manual_trends" | "comfyui_image_workflow">>;

export const api = {
  aiProviders: () => get<AiProviderInfo[]>("/api/ai/providers"),
  aiUpdateProvider: (id: string, body: { base_url?: string; api_key?: string }) =>
    send<AiProviderInfo>("PUT", `/api/ai/providers/${id}`, body),
  aiDeleteKey: (id: string) => send<AiProviderInfo>("DELETE", `/api/ai/providers/${id}/key`),
  aiTestProvider: (id: string) => send<AiTestResult>("POST", `/api/ai/providers/${id}/test`),
  aiModels: (id: string, refresh = false) => get<AiModel[]>(`/api/ai/providers/${id}/models?refresh=${refresh}`),
  aiTasks: () => get<AiTask[]>("/api/ai/tasks"),
  aiSetTask: (task: string, body: AiTaskInput) => send<AiTask[]>("PUT", `/api/ai/tasks/${task}`, body),
  aiResetTask: (task: string) => send<AiTask[]>("DELETE", `/api/ai/tasks/${task}`),
  aiCalls: () => get<AiCall[]>("/api/ai/calls?limit=20"),
  security: () => get<SecurityStatus>("/api/security"),

  health: () => get<Health>("/api/health"),
  status: () => get<ServicesStatus>("/api/status"),

  projects: () => get<Project[]>("/api/projects"),
  project: (id: string) => get<ProjectDetail>(`/api/projects/${id}`),
  createProject: (body: { title: string; niche: string; language: string; video_mode: VideoMode }) =>
    send<ProjectDetail>("POST", "/api/projects", body),
  /** Lance l'etape suivante en arriere-plan ; la progression arrive par WebSocket. */
  advance: (id: string) => send<{ detail: string }>("POST", `/api/projects/${id}/pipeline/advance?background=true`),
  approve: (id: string, step: string, confirm = false) =>
    send<Step>("POST", `/api/projects/${id}/steps/${step}/approve`, { validated_by: "utilisateur", confirm }),
  reject: (id: string, step: string, reason = "") =>
    send<Step>("POST", `/api/projects/${id}/steps/${step}/reject`, { reason }),
  redo: (id: string, step: string) => send<Step>("POST", `/api/projects/${id}/steps/${step}/redo`),
  cancel: (id: string) => send<Project>("POST", `/api/projects/${id}/pipeline/cancel`),
  resume: (id: string) => send<ProjectDetail>("POST", `/api/projects/${id}/pipeline/resume`),

  ideas: (id: string) => get<Idea[]>(`/api/projects/${id}/ideas`),
  selectIdea: (id: string, ideaId: string) => send<Idea>("POST", `/api/projects/${id}/ideas/${ideaId}/select`),

  script: (id: string) => get<ScriptDetail>(`/api/projects/${id}/script`),
  updateScript: (id: string, body: ScriptPatch) => send<ScriptDetail>("PUT", `/api/projects/${id}/script`, body),
  shortenScript: (id: string, target: number) =>
    send<ScriptDetail>("POST", `/api/projects/${id}/script/shorten`, { target_duration_s: target }),
  regenerateScript: (id: string, instructions: string) =>
    send<ScriptDetail>("POST", `/api/projects/${id}/script/regenerate`, { instructions }),

  scenes: (id: string) => get<Scene[]>(`/api/projects/${id}/scenes`),
  patchScene: (sceneId: string, body: ScenePatch) => send<Scene>("PATCH", `/api/scenes/${sceneId}`, body),
  regenerateScene: (sceneId: string, target: "image" | "video") =>
    send<Scene>("POST", `/api/scenes/${sceneId}/regenerate`, { target }),
  costEstimate: (id: string) => get<CostEstimate>(`/api/projects/${id}/cost-estimate`),
  setEngine: (id: string, body: EnginePatch) => send<Project>("PUT", `/api/projects/${id}/engine`, body),
  assets: (id: string, kind?: string) => get<Asset[]>(`/api/projects/${id}/assets${kind ? `?kind=${kind}` : ""}`),

  providers: () => get<Provider[]>("/api/providers"),
  patchProvider: (id: string, body: ProviderPatch) => send<Provider>("PATCH", `/api/providers/${id}`, body),

  budget: () => get<Budget>("/api/budget"),
  setBudget: (body: BudgetPatch) => send<Budget>("PUT", "/api/budget/limits", body),
  costs: (limit = 200) => get<Cost[]>(`/api/budget/history?limit=${limit}`),

  settings: () => get<AppSettings>("/api/settings"),
  updateSettings: (body: SettingsPatch) => send<AppSettings>("PUT", "/api/settings", body),
  workflows: () => get<Workflow[]>("/api/comfyui/workflows"),
  addWorkflow: (body: { id: string; name: string; kind: "image" | "video"; workflow: Record<string, unknown> }) =>
    send<Workflow>("POST", "/api/comfyui/workflows", body),

  jobs: (projectId?: string) => get<Job[]>(`/api/jobs${projectId ? `?project_id=${projectId}` : ""}`),
  history: (projectId?: string) => get<HistoryEvent[]>(`/api/history${projectId ? `?project_id=${projectId}` : ""}`),
  stats: () => get<Stats>("/api/stats"),

  render: (id: string) => get<Render | null>(`/api/projects/${id}/render`),
  subtitles: (id: string) => get<SubtitleInfo>(`/api/projects/${id}/subtitles`),
  setSubtitleStyle: (id: string, body: { position?: SubtitleInfo["position"]; style?: Partial<SubtitleStyle> }) =>
    send<SubtitleInfo>("PUT", `/api/projects/${id}/subtitles`, body),
  draft: (id: string) => get<YoutubeDraft | null>(`/api/projects/${id}/youtube-draft`),
  updateDraft: (id: string, body: Partial<Pick<YoutubeDraft, "title" | "description" | "tags" | "privacy" | "made_for_kids">>) =>
    send<YoutubeDraft>("PUT", `/api/projects/${id}/youtube-draft`, body),
  finalCheck: (id: string) => get<FinalCheck>(`/api/projects/${id}/final-check`),
  youtubeStatus: () => get<YoutubeStatus>("/api/youtube/status"),
  youtubeConnect: () => send<{ url: string }>("POST", "/api/youtube/connect"),
  reviseScript: (id: string, instruction: string) =>
    send<ScriptDetail>("POST", `/api/projects/${id}/script/revise`, { instruction }),
  autopilot: (id: string) => send<{ detail: string }>("POST", `/api/projects/${id}/autopilot`),

  voice: () => get<VoiceState>("/api/voice"),
  setVoice: (body: Partial<VoiceState["settings"]>) => send<VoiceState>("PUT", "/api/voice", body),
  voiceSample: (text?: string) => send<{ engine: string; url: string }>("POST", "/api/voice/sample", text ? { text } : {}),
  subtitlePresets: () => get<{ presets: SubtitlePreset[]; effects: Record<string, string> }>("/api/subtitle-presets"),
  setSubtitlePreset: (id: string, preset: string) => send<SubtitleInfo>("PUT", `/api/projects/${id}/subtitles`, { preset }),

  music: () => get<MusicTrack[]>("/api/music"),
  uploadMusic: (file: File, p: { title: string; license: string; rights_confirmed: boolean; volume: number }) =>
    upload<MusicTrack>("/api/music/upload", file, p),
  patchMusic: (trackId: string, body: { is_default?: boolean; volume?: number }) => send<MusicTrack>("PATCH", `/api/music/${trackId}`, body),
  deleteMusic: (trackId: string) => send<{ deleted: boolean }>("DELETE", `/api/music/${trackId}`),
  brand: () => get<Brand>("/api/brand"),
  setBrand: (body: Partial<Brand> & { remove_logo?: boolean }) => send<Brand>("PUT", "/api/brand", body),
  uploadLogo: (file: File) => upload<Brand>("/api/brand/logo", file, {}),

  competitors: () => get<Competitor[]>("/api/competitors"),
  addCompetitor: (platform: string, handle: string) => send<Competitor>("POST", "/api/competitors", { platform, handle }),
  refreshCompetitor: (cid: string) => send<Competitor>("POST", `/api/competitors/${cid}/refresh`),
  addCompetitorVideo: (cid: string, body: { title: string; views: number; url?: string; duration_s?: number }) =>
    send<Competitor>("POST", `/api/competitors/${cid}/videos`, body),
  deleteCompetitor: (cid: string) => send<{ deleted: boolean }>("DELETE", `/api/competitors/${cid}`),
  recipe: (vid: string) => send<CompetitorVideo["recipe"]>("POST", `/api/competitor-videos/${vid}/recipe`),
  makeShort: (vid: string, body: { niche: string; language: string; video_mode: VideoMode }) =>
    send<{ project_id: string; title: string; reuse_risk: string }>("POST", `/api/competitor-videos/${vid}/make-short`, body),

  style: () => get<StyleProfile | null>("/api/style"),
  learnStyle: (samples: string[]) => send<StyleProfile>("POST", "/api/style/learn", { samples }),
  learnStyleFromVideos: () => send<StyleProfile>("POST", "/api/style/learn-from-videos"),
  toggleStyle: (enabled: boolean) => send<StyleProfile>("PUT", `/api/style/enabled?enabled=${enabled}`),

  performance: () => get<{ rows: PerformanceRow[]; insights: Insights | null }>("/api/performance"),
  addStats: (body: { project_id: string; platform: string; views: number; likes: number; comments: number }) =>
    send<{ rows: PerformanceRow[] }>("POST", "/api/performance/manual", body),
  refreshStats: () => send<{ updated: number }>("POST", "/api/performance/refresh"),
  insights: () => send<Insights>("POST", "/api/performance/insights"),

  slots: () => get<Slots>("/api/planning/slots"),
  setSlots: (body: Partial<Slots>) => send<Slots>("PUT", "/api/planning/slots", body),
  planningPool: (body: { niche: string; language: string; video_mode: VideoMode; count: number }) =>
    send<{ pool_id: string; dates: string[]; ideas: PoolIdea[]; warnings: string[] }>("POST", "/api/planning/pool", body),
  planningWeek: (body: { pool_id: string; idea_ids: string[] }) =>
    send<{ projects: { id: string; title: string; planned_for: string }[] }>("POST", "/api/planning/week", body),
  validations: () => get<Validation[]>("/api/validations"),

  sources: () => get<SourceVideo[]>("/api/sources"),
  uploadSource: (file: File, p: { title: string; rights_confirmed: boolean; language: string }) =>
    upload<SourceVideo>("/api/sources/upload", file, p),
  analyseSource: (sid: string, count: number) => send<{ detail: string }>("POST", `/api/sources/${sid}/analyse?count=${count}`),
  createClips: (sid: string, indexes: number[]) => send<{ projects: { id: string; title: string }[] }>("POST", `/api/sources/${sid}/clips`, { indexes }),
  deleteSource: (sid: string) => send<{ deleted: boolean }>("DELETE", `/api/sources/${sid}`),

  posts: (id: string) => get<SocialPostT[]>(`/api/projects/${id}/posts`),
  patchPost: (postId: string, body: { caption?: string; enabled?: boolean; scheduled_at?: string; clear_schedule?: boolean }) =>
    send<SocialPostT>("PATCH", `/api/posts/${postId}`, body),
  postExported: (postId: string) => send<SocialPostT>("POST", `/api/posts/${postId}/exported`),
  postPublished: (postId: string, url: string) => send<SocialPostT>("POST", `/api/posts/${postId}/published`, { url }),
  finishManual: (id: string) => send<{ status: string }>("POST", `/api/projects/${id}/finish-manual`),

  comfyCheck: () => get<ComfyCheck>("/api/comfyui/check"),
  setComfy: (body: { url?: string; checkpoint?: string }) => send<ComfyCheck>("PUT", "/api/comfyui/settings", body),
  onboarding: () => get<Onboarding>("/api/onboarding"),
  onboardingDone: () => send<{ done: boolean }>("POST", "/api/onboarding/done"),
};
