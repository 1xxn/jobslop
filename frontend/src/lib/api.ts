import type {
  ActivityItem,
  Answer,
  ApplicationDetail,
  ApplicationSummary,
  ApplyMode,
  CrawlRun,
  Exclusion,
  JobDetail,
  JobList,
  JobSummary,
  Pipeline,
  Preset,
  ProfileResponse,
  Profile,
  Prompt,
  RunnerState,
  SearchConfig,
  Settings,
  Stats,
  Status,
  SystemReport,
} from "./types";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

function detail(body: unknown, fallback: string): string {
  if (body && typeof body === "object" && "detail" in body) {
    const d = (body as { detail: unknown }).detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d)) return d.map((e) => (e as { msg?: string }).msg ?? String(e)).join(", ");
  }
  return fallback;
}

async function request<T>(method: string, path: string, body?: unknown, form?: FormData): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (method !== "GET") headers["X-Jobslop"] = "1"; // CSRF-Schutz des lokalen Servers
  if (body !== undefined) headers["Content-Type"] = "application/json";
  let res: Response;
  try {
    res = await fetch(path, {
      method,
      headers,
      body: form ?? (body !== undefined ? JSON.stringify(body) : undefined),
    });
  } catch {
    throw new ApiError(0, "jobslop ist nicht erreichbar – läuft das Programm noch?");
  }
  const text = await res.text();
  let data: unknown = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    // z. B. „Internal Server Error“ als Klartext – die Statuszeile ist dann die bessere Meldung
    if (res.ok) throw new ApiError(res.status, "Unerwartete Antwort von jobslop");
  }
  if (!res.ok) throw new ApiError(res.status, detail(data, `${res.status} ${res.statusText}`));
  return data as T;
}

const get = <T>(path: string) => request<T>("GET", path);
const post = <T>(path: string, body?: unknown) => request<T>("POST", path, body ?? {});
const put = <T>(path: string, body: unknown) => request<T>("PUT", path, body);
const patch = <T>(path: string, body: unknown) => request<T>("PATCH", path, body);
const del = <T>(path: string) => request<T>("DELETE", path);

function qs(params: Record<string, string | number | boolean | undefined>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== "") p.set(k, String(v));
  const s = p.toString();
  return s ? `?${s}` : "";
}

export interface JobQuery {
  q?: string;
  category?: string;
  where?: string;
  level?: string;
  status?: string;
  view?: string;
  min_fit?: number;
  sort?: string;
  limit?: number;
  offset?: number;
}

export const api = {
  status: () => get<Status>("/api/status"),
  system: (refresh = false) => get<SystemReport>(`/api/system${refresh ? "?refresh=1" : ""}`),
  claudeLogin: () => post<{ opened: boolean; installed: boolean; install_command: string }>("/api/system/claude-login"),
  claudeInstall: () => post<{ opened: boolean }>("/api/system/claude-install"),
  browserInstall: () => post<SystemReport["browser_install"]>("/api/system/browser-install"),
  openFolder: () => post<{ opened: boolean }>("/api/system/open-folder"),

  profile: () => get<ProfileResponse>("/api/profile"),
  saveProfile: (profile: Profile) => put<ProfileResponse>("/api/profile", profile),
  uploadDocument: (file: File, kind: "cv" | "cv_en" | "certificate", importCv: boolean) => {
    const form = new FormData();
    form.append("file", file);
    form.append("kind", kind);
    form.append("import_cv", importCv ? "true" : "false");
    return request<ProfileResponse>("POST", "/api/profile/document", undefined, form);
  },

  search: () => get<SearchConfig>("/api/search"),
  saveSearch: (config: SearchConfig) => put<SearchConfig>("/api/search", config),
  presets: () => get<Preset[]>("/api/presets"),
  presetPreview: (body: { presets: string[]; cities: string[]; remote: boolean; exclude_leadership: boolean }) =>
    post<SearchConfig>("/api/search/preset", body),

  settings: () => get<Settings>("/api/settings"),
  saveSettings: (s: Partial<Settings>) => put<Settings>("/api/settings", s),
  completeSetup: (startCrawl = true) =>
    post<{ ok: boolean; crawl_started: boolean }>(`/api/setup/complete${qs({ start_crawl: startCrawl })}`),

  jobs: (q: JobQuery) => get<JobList>(`/api/jobs${qs(q as Record<string, string>)}`),
  job: (id: number) => get<JobDetail>(`/api/jobs/${id}`),
  addJob: (url: string) => post<{ id: number; created: boolean; via: string }>("/api/jobs", { url }),
  patchJob: (id: number, body: Partial<Pick<JobSummary, "queued" | "starred">> & { notes?: string }) =>
    patch<JobSummary>(`/api/jobs/${id}`, body),
  markJob: (id: number, status: "applied" | "interview" | "rejected" | "offer", note = "") =>
    post<JobSummary>(`/api/jobs/${id}/status`, { status, note }),
  bulk: (ids: number[], action: "queue" | "unqueue" | "star" | "unstar" | "exclude") =>
    post<{ changed: number[]; skipped: string[] }>("/api/jobs/bulk", { ids, action }),
  queueTop: (count: number) => post<{ changed: number[]; skipped: string[] }>(`/api/queue/top${qs({ count })}`),
  queueClear: () => post<{ changed: number[] }>("/api/queue/clear"),

  apply: (body: { job_ids?: number[]; mode?: ApplyMode; max?: number; force?: boolean }) =>
    post<RunnerState>("/api/apply", body),
  runner: (lines = 200) => get<RunnerState>(`/api/runner?lines=${lines}`),
  stopRunner: () => post<RunnerState & { stopped: boolean }>("/api/runner/stop"),

  crawl: () => post<{ started: boolean }>("/api/crawl"),
  crawls: () => get<CrawlRun[]>("/api/crawls"),
  autopilotRun: () => post<{ started: boolean }>("/api/autopilot/run"),
  activity: (limit = 30) => get<ActivityItem[]>(`/api/activity?limit=${limit}`),
  stats: () => get<Stats>("/api/stats"),

  applications: (status = "") => get<ApplicationSummary[]>(`/api/applications${qs({ status })}`),
  application: (id: number) => get<ApplicationDetail>(`/api/applications/${id}`),
  patchApplication: (
    id: number,
    body: { status?: string; notes?: string; follow_up_at?: string | null; clear_follow_up?: boolean },
  ) => patch<ApplicationSummary>(`/api/applications/${id}`, body),
  answerApplication: (id: number, answers: Record<string, string>, requeue = true) =>
    post<{ saved: number }>(`/api/applications/${id}/answers`, { answers, requeue }),
  pipeline: () => get<Pipeline>("/api/pipeline"),

  answerPrompt: (
    id: number,
    body: { answers?: Record<string, string>; skip?: boolean; decision?: string; done?: boolean; abort?: boolean },
  ) => post<Prompt>(`/api/prompts/${id}`, body),

  answers: () => get<Answer[]>("/api/answers"),
  createAnswer: (question: string, answer: string) => post<{ id: number }>("/api/answers", { question, answer }),
  updateAnswer: (id: number, question: string, answer: string) =>
    put<{ id: number }>(`/api/answers/${id}`, { question, answer }),
  deleteAnswer: (id: number) => del<{ deleted: number }>(`/api/answers/${id}`),

  exclusions: () => get<Exclusion[]>("/api/exclusions"),
  createExclusion: (kind: Exclusion["kind"], value: string, reason = "") =>
    post<{ id: number }>("/api/exclusions", { kind, value, reason }),
  deleteExclusion: (id: number) => del<{ deleted: number }>(`/api/exclusions/${id}`),
};

export const artifactUrl = (appId: number, name: string) => `/artifacts/${appId}/${encodeURIComponent(name)}`;
