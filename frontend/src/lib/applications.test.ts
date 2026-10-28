import { describe, expect, it } from "vitest";
import { followUpDue, groupApplications } from "./applications";
import type { ApplicationSummary } from "./types";

const app = (id: number, job_id: number, status: ApplicationSummary["status"], extra: Partial<ApplicationSummary> = {}) =>
  ({
    id,
    job_id,
    status,
    company: `Firma ${job_id}`,
    title: "Site Reliability Engineer",
    started_at: `2026-10-${String(id).padStart(2, "0")}T10:00:00Z`,
    submitted_at: null,
    follow_up_at: null,
    ...extra,
  }) as ApplicationSummary;

const now = Date.parse("2026-10-27T12:00:00Z");

describe("groupApplications", () => {
  it("keeps only the latest application per job and groups it by stage", () => {
    const g = groupApplications(
      [app(1, 1, "failed"), app(2, 1, "submitted"), app(3, 2, "needs_review"), app(4, 3, "rejected")],
      "",
      now,
    );
    expect(g.sent.map((a) => a.id)).toEqual([2]);
    expect(g.failed).toEqual([]);
    expect(g.waiting.map((a) => a.id)).toEqual([3]);
    expect(g.rejected.map((a) => a.id)).toEqual([4]);
  });

  it("puts due follow-ups first and filters by company or title", () => {
    const due = app(5, 5, "submitted", { follow_up_at: "2026-10-26T09:00:00Z" });
    const later = app(6, 6, "submitted", { follow_up_at: "2026-11-02T09:00:00Z" });
    expect(groupApplications([later, due], "", now).sent.map((a) => a.id)).toEqual([5, 6]);
    expect(groupApplications([later, due], "firma 6", now).sent.map((a) => a.id)).toEqual([6]);
  });
});

describe("followUpDue", () => {
  it("is only due for open applications with a date in the past", () => {
    expect(followUpDue(app(1, 1, "submitted", { follow_up_at: "2026-10-01T09:00:00Z" }), now)).toBe(true);
    expect(followUpDue(app(1, 1, "rejected", { follow_up_at: "2026-10-01T09:00:00Z" }), now)).toBe(false);
    expect(followUpDue(app(1, 1, "submitted"), now)).toBe(false);
  });
});
