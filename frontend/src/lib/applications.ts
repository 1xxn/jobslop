import type { AppStatus, ApplicationSummary, Prompt } from "./types";
import { parseDate } from "./utils";

/** Gruppen der Bewerbungsliste – die früheren Pipeline-Spalten plus das, was davor und daneben passiert. */
export const GROUPS = ["waiting", "running", "sent", "interview", "offer", "rejected", "failed"] as const;
export type AppGroup = (typeof GROUPS)[number];

const GROUP_OF: Record<AppStatus, AppGroup> = {
  needs_input: "waiting",
  needs_review: "waiting",
  ready: "waiting",
  running: "running",
  paused: "running",
  queued: "running",
  submitted: "sent",
  manual: "sent",
  interview: "interview",
  offer: "offer",
  rejected: "rejected",
  failed: "failed",
  skipped: "failed",
  "": "failed",
};

export function groupOf(status: AppStatus): AppGroup {
  return GROUP_OF[status] ?? "failed";
}

const time = (v: string | null | undefined) => parseDate(v)?.getTime() ?? 0;

/**
 * Stand, wie du ihn siehst: Während ein Lauf auf deine Freigabe oder Antwort wartet, steht die Bewerbung technisch noch
 * auf „running“ – für dich ist sie aber dran. Offene Rückfragen überstimmen deshalb den gespeicherten Stand.
 */
export function effectiveStatus(app: Pick<ApplicationSummary, "id" | "status">, prompts: Prompt[] = []): AppStatus {
  const open = prompts.filter((p) => p.application_id === app.id);
  if (open.some((p) => p.kind === "confirm")) return "needs_review";
  if (open.length) return "needs_input";
  return app.status;
}

/** Ist ein Nachfass-Termin fällig? (nur solange die Bewerbung noch offen ist) */
export function followUpDue(a: ApplicationSummary, now = Date.now()): boolean {
  return !!a.follow_up_at && time(a.follow_up_at) <= now && ["submitted", "manual", "interview"].includes(a.status);
}

/**
 * Pro Stelle zählt die letzte Bewerbung (wie in der Pipeline), gefiltert nach Suchtext und gruppiert nach Stand.
 * Gesendete mit fälligem Nachfassen stehen oben, sonst die neuesten zuerst.
 */
export function groupApplications(apps: ApplicationSummary[], query = "", now = Date.now(), prompts: Prompt[] = []) {
  const latest = new Map<number, ApplicationSummary>();
  for (const a of apps) if ((latest.get(a.job_id)?.id ?? -1) < a.id) latest.set(a.job_id, a);
  const q = query.trim().toLowerCase();
  const groups = Object.fromEntries(GROUPS.map((g) => [g, [] as ApplicationSummary[]])) as Record<
    AppGroup,
    ApplicationSummary[]
  >;
  for (const a of latest.values()) {
    if (q && !`${a.company} ${a.title}`.toLowerCase().includes(q)) continue;
    const status = effectiveStatus(a, prompts);
    groups[groupOf(status)].push(status === a.status ? a : { ...a, status });
  }
  const recent = (a: ApplicationSummary) => time(a.submitted_at ?? a.started_at);
  for (const g of GROUPS) {
    groups[g].sort((a, b) =>
      g === "waiting"
        ? time(a.started_at) - time(b.started_at)
        : Number(followUpDue(b, now)) - Number(followUpDue(a, now)) || recent(b) - recent(a),
    );
  }
  return groups;
}
