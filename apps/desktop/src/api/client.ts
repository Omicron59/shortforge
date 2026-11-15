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
} from "./types";

export const API_URL: string = import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8787";

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
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
    res = await fetch(`${API_URL}${path}`, { headers: { "Content-Type": "application/json" }, ...init });
  } catch {
    throw new ApiError("Moteur local injoignable : lance le backend (python -m shortforge).", 0);
  }
  const body: unknown = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(errorMessage(res.status, body), res.status);
  return body as T;
}

const get = <T,>(path: string) => request<T>(path);
const send = <T,>(method: string, path: string, body?: unknown) =>
  request<T>(path, { method, body: body === undefined ? undefined : JSON.stringify(body) });

export const assetUrl = (assetId: string) => `${API_URL}/api/assets/${assetId}/file`;
export const eventsUrl = (projectId: string) => `${API_URL.replace(/^http/, "ws")}/api/projects/${projectId}/events`;

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
};
