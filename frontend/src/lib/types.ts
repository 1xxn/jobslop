export type ApplyMode = "review" | "auto" | "dry-run";

export type AppStatus =
  | "running"
  | "needs_input"
  | "needs_review"
  | "ready"
  | "paused"
  | "submitted"
  | "failed"
  | "skipped"
  | "manual"
  | "interview"
  | "rejected"
  | "offer"
  | "queued"
  | "";

export interface Prompt {
  id: number;
  kind: "questions" | "confirm" | "handoff";
  application_id: number;
  created_at: string;
  payload: {
    title?: string;
    message?: string;
    screenshot?: string;
    rows?: FilledRow[];
    questions?: Question[];
  };
}

export interface Question {
  field_id: string;
  question: string;
  why: string;
  options: string[];
  label?: string;
}

export interface FilledRow {
  step?: number;
  field_id?: string;
  label: string;
  action?: string;
  value: string;
  ok?: boolean;
  detail?: string;
  source?: string;
  confidence?: string;
}

export interface RunnerState {
  active: boolean;
  label: string;
  mode: string;
  started_at: string | null;
  finished_at: string | null;
  returncode: number | null;
  log?: string;
}

export interface Status {
  version: string;
  setup_completed: boolean;
  demo: boolean;
  prompts: Prompt[];
  runner: RunnerState;
  crawl: { running: boolean; started_at: string | null; last: CrawlSummary | null };
  autopilot: { enabled: boolean; running: boolean; next_run: string | null };
  counts: { open_jobs: number; queued: number; attention: number };
  notify_desktop: boolean;
}

export interface CrawlSummary {
  run_id?: number;
  new?: number;
  closed?: number;
  kept?: number;
  queued?: number[];
  errors?: number;
  error?: string;
}

export interface JobSummary {
  id: number;
  company: string;
  title: string;
  location: string;
  where: string;
  workplace: string;
  category: string;
  level: string;
  fit: number;
  score: number;
  status: string;
  queued: boolean;
  starred: boolean;
  source: string;
  url: string;
  posted: string;
  first_seen: string | null;
  enriched: boolean;
  summary: string;
  app_status: AppStatus;
  app_id: number | null;
}

export interface JobDetail extends JobSummary {
  description: string;
  apply_url: string;
  alt_urls: string[];
  notes: string;
  enrichment: {
    required_years?: number;
    seniority?: string;
    fit_reason?: string;
    german_required?: boolean;
    workplace?: string;
    red_flags?: string[];
    summary?: string;
  };
  segment: string;
  language: string;
  last_seen: string | null;
  verdict: { ok: boolean; reason: string; code?: string; params?: Record<string, unknown> };
  score_parts: { key: string; points: number }[];
  score_max: number;
  history: { seen_at: string; change: string; diff: Record<string, unknown> }[];
  applications: ApplicationSummary[];
}

export interface JobList {
  items: JobSummary[];
  total: number;
  facets: { category: Record<string, number> };
}

export interface ApplicationSummary {
  id: number;
  job_id: number;
  company: string;
  title: string;
  job_url: string;
  status: AppStatus;
  mode: string;
  origin: string;
  started_at: string | null;
  finished_at: string | null;
  submitted_at: string | null;
  error: string;
  confirmation: string;
  notes: string;
  follow_up_at: string | null;
  open_questions: number;
}

export interface ApplicationDetail extends ApplicationSummary {
  events: { ts: string; kind: string; message: string }[];
  screenshots: string[];
  documents: string[];
  filled: FilledRow[];
  questions: Question[];
  usage: Record<string, number>;
  final_url: string;
  prompts: Prompt[];
}

export interface Pipeline {
  stages: Record<"applied" | "interview" | "offer" | "rejected", ApplicationSummary[]>;
  follow_ups_due: ApplicationSummary[];
}

export interface CrawlRun {
  id: number;
  started_at: string;
  finished_at: string | null;
  status: string;
  stats: {
    fetched?: number;
    kept?: number;
    new?: number;
    updated?: number;
    closed?: number;
    per_source?: Record<string, number>;
    rejected?: Record<string, number>;
  };
  errors: string[];
}

export interface ActivityItem {
  id: number;
  ts: string;
  kind: string;
  message: string;
  data?: Record<string, unknown>;
}

export interface Stats {
  jobs: { open: number; new_7d: number; by_category: Record<string, number> };
  applications: {
    by_status: Record<string, number>;
    sent_total: number;
    sent_7d: number;
    response_rate: number;
    interview_rate: number;
    per_week: { week: string; sent: number }[];
  };
}

export interface Role {
  name: string;
  keywords: string[];
}

export interface SearchConfig {
  roles: Role[];
  filters: {
    include_titles: string[];
    exclude_titles: string[];
    stretch_markers: string[];
    onsite_locations: string[];
    remote_regions: string[];
    remote_keywords: string[];
    allow_remote: boolean;
    keep_stretch: boolean;
  };
  limits: {
    max_per_company_window: number;
    company_window_days: number;
    max_applications_per_run: number;
    min_delay_seconds: number;
    min_score_for_auto_queue: number;
    max_enrich_per_crawl: number;
  };
  sources: {
    greenhouse: string[];
    ashby: string[];
    lever: string[];
    smartrecruiters: string[];
    personio: string[];
    recruitee: string[];
    workable: string[];
    workday: { company: string; host: string; tenant: string; site: string; search_text: string }[];
    amazon_queries: string[];
    amazon_country: string;
    queries: string[];
    arbeitnow: boolean;
    arbeitnow_max_pages: number;
    himalayas: boolean;
    himalayas_country: string;
    arbeitsagentur: boolean;
    arbeitsagentur_radius_km: number;
    arbeitsagentur_skip_agencies: boolean;
    portals: Portal[];
    portal_country: string;
    portal_results: number;
    portal_hours_old: number;
    discover_boards: boolean;
    discover_max_per_crawl: number;
    generic: { company: string; url: string }[];
  };
  segments: Record<string, string[]>;
  skills: string[];
}

export type Portal = "linkedin" | "indeed" | "glassdoor";

export interface Preset {
  id: string;
  label: { de: string; en: string };
  roles: Role[];
  skills: string[];
}

export interface Settings {
  home: string;
  llm_model: string;
  llm_model_fast: string;
  claude_parallel: number;
  claude_effort: string;
  apply_mode: ApplyMode;
  headless: boolean;
  vision: "auto" | "always" | "never";
  autofill: boolean;
  max_steps_per_application: number;
  autopilot_enabled: boolean;
  autopilot_days: number[];
  autopilot_time: string;
  autopilot_apply: boolean;
  autopilot_apply_max: number;
  autopilot_apply_mode: ApplyMode;
  notify_desktop: boolean;
  notify_ntfy_url: string;
  notify_webhook_url: string;
  follow_up_days: number;
  setup_completed: boolean;
  extension_portals: boolean;
  extension_portal_daily_limit: number;
}

export interface ExtensionInfo {
  path: string;
  installed: boolean;
  outdated: boolean;
  version: string;
  portals: boolean;
  portal_limit: number;
  portal_used: number;
}

export interface Experience {
  company: string;
  title: string;
  start: string;
  end: string;
  location: string;
  highlights: string[];
}

export interface Profile {
  personal: {
    first_name: string;
    last_name: string;
    email: string;
    phone: string;
    street: string;
    postal_code: string;
    city: string;
    country: string;
    linkedin: string;
    github: string;
    website: string;
    date_of_birth: string;
    pronouns: string;
  };
  work: {
    current_title: string;
    current_employer: string;
    years_experience_total: string;
    years_experience_relevant: string;
    notice_period: string;
    earliest_start: string;
    salary_expectation_eur: string;
    work_authorization_eu: boolean;
    requires_visa_sponsorship: boolean;
    nationality: string;
    willing_to_relocate: boolean;
    workplace_preference: string;
    security_clearance: string;
    drivers_license: string;
  };
  summary: string;
  skills: string[];
  languages: { language: string; level: string }[];
  experience: Experience[];
  education: { institution: string; degree: string; start: string; end: string; location: string; grade: string }[];
  certifications: string[];
  documents: { cv: string; cv_en: string; certificates: string[]; cover_letter: string };
  preferences: {
    cover_letter_language: "auto" | "de" | "en";
    diversity_questions: "decline" | "answer";
    diversity_answers: Record<string, string>;
    consent_privacy: boolean;
    consent_talent_pool: boolean;
    newsletter: boolean;
    how_did_you_hear: string;
    tone: string;
  };
  standard_answers: Record<string, string>;
}

export interface ProfileResponse {
  profile: Profile;
  missing: string[];
  documents: { cv: { name: string; exists: boolean } | null; cv_en: { name: string; exists: boolean } | null };
  message?: string;
}

export interface SystemReport {
  version: string;
  home: string;
  setup_completed: boolean;
  claude: {
    installed: boolean;
    ok: boolean;
    message: string;
    method: string;
    version: string;
    account: string;
    plan: string;
  };
  browser: { ok: boolean; message: string; detail: Record<string, string> };
  browser_install: { running: boolean; returncode: number | null; log: string[] };
  profile: { exists: boolean; missing: string[]; cv: string; cv_ok: boolean; name: string };
}

export interface Answer {
  id: number;
  question: string;
  answer: string;
  updated_at: string;
}

export interface Exclusion {
  id: number;
  kind: "company" | "job" | "title" | "url";
  value: string;
  reason: string;
  created_at: string;
}
