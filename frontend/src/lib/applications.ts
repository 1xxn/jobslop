import type { AppStatus, ApplicationSummary } from "./types";
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

/** Stände, bei denen Nachfassen noch Sinn hat (gesendet, Interview) – wie im Backend. */
export function canFollowUp(status: AppStatus): boolean {
  return status === "submitted" || status === "manual" || status === "interview";
}

/** Ist ein Nachfass-Termin fällig? (nur solange die Bewerbung noch offen ist) */
export function followUpDue(a: ApplicationSummary, now = Date.now()): boolean {
  return !!a.follow_up_at && time(a.follow_up_at) <= now && canFollowUp(a.status);
}

/**
 * Pro Stelle zählt die letzte Bewerbung (wie in der Pipeline), gefiltert nach Suchtext und gruppiert nach Stand.
 * Gesendete mit fälligem Nachfassen stehen oben, sonst die neuesten zuerst.
 */
export function groupApplications(apps: ApplicationSummary[], query = "", now = Date.now()) {
  const latest = new Map<number, ApplicationSummary>();
  for (const a of apps) if ((latest.get(a.job_id)?.id ?? -1) < a.id) latest.set(a.job_id, a);
  const q = query.trim().toLowerCase();
  const groups = Object.fromEntries(GROUPS.map((g) => [g, [] as ApplicationSummary[]])) as Record<
    AppGroup,
    ApplicationSummary[]
  >;
  for (const a of latest.values()) {
    if (q && !`${a.company} ${a.title}`.toLowerCase().includes(q)) continue;
    groups[groupOf(a.status)].push(a);
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
