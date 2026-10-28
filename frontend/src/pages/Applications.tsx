import { useQuery } from "@tanstack/react-query";
import { type ReactNode, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { ApplicationsSummary, PageHeader, StatusGlyph } from "@/components/domain";
import { Segmented } from "@/components/ui/controls";
import { Button, EmptyState, rowHover, SearchInput, Skeleton } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { useStatus } from "@/lib/hooks";
import { type AppGroup, canFollowUp, followUpDue, GROUPS, groupApplications } from "@/lib/applications";
import { useI18n } from "@/lib/i18n";
import type { MessageKey } from "@/lib/messages";
import type { ApplicationSummary, JobSummary, Prompt } from "@/lib/types";
import { cn, formatDate, formatRelative } from "@/lib/utils";
import { PipelineBoard } from "./Pipeline";

type View = "list" | "board";

// Abgeschlossenes ist eingeklappt, bleibt aber mit Zahl sichtbar
const COLLAPSED: AppGroup[] = ["rejected", "failed"];

/** Alle Bewerbungen – als Liste nach Stand oder als Board (die frühere Pipeline). */
export function ApplicationsPage() {
  const { t } = useI18n();
  const [params, setParams] = useSearchParams();
  const view: View = params.get("view") === "board" ? "board" : "list";
  const stats = useQuery({ queryKey: ["stats"], queryFn: api.stats, refetchInterval: 60_000 });
  return (
    <>
      <PageHeader
        title={t("apps.title")}
        actions={
          <Segmented<View>
            label={t("apps.view")}
            value={view}
            onChange={(v) => setParams(v === "board" ? { view: "board" } : {}, { replace: true })}
            options={[
              { value: "list", label: t("apps.view_list") },
              { value: "board", label: t("apps.view_board") },
            ]}
          />
        }
      >
        {!!stats.data?.applications.sent_total && <ApplicationsSummary stats={stats.data} className="mt-2" />}
      </PageHeader>
      {view === "board" ? <PipelineBoard /> : <ApplicationList />}
    </>
  );
}

function ApplicationList() {
  const { t } = useI18n();
  const [q, setQ] = useState("");
  const [open, setOpen] = useState<Record<AppGroup, boolean>>(
    () => Object.fromEntries(GROUPS.map((g) => [g, !COLLAPSED.includes(g)])) as Record<AppGroup, boolean>,
  );
  const apps = useQuery({ queryKey: ["applications", "all"], queryFn: () => api.applications(), refetchInterval: 10_000 });
  const queued = useQuery({ queryKey: ["jobs", "queued", "apps"], queryFn: () => api.jobs({ view: "queued", limit: 100 }) });
  const { data: status } = useStatus();
  const groups = useMemo(() => groupApplications(apps.data ?? [], q), [apps.data, q]);
  const upNext = (queued.data?.items ?? []).filter(
    (j) => !q || `${j.company} ${j.title}`.toLowerCase().includes(q.trim().toLowerCase()),
  );

  if (apps.isLoading) {
    return (
      <div className="grid gap-3 pt-4" aria-busy="true">
        {Array.from({ length: 6 }, (_, i) => (
          <Skeleton key={i} className="h-9" />
        ))}
      </div>
    );
  }
  if (apps.isError) {
    return (
      <EmptyState
        title={t("apps.load_error")}
        description={t("jobs.load_error_hint")}
        action={<Button size="sm" onClick={() => apps.refetch()}>{t("common.retry")}</Button>}
      />
    );
  }
  if (!apps.data?.length && !upNext.length && !q) {
    return (
      <EmptyState
        title={t("apps.empty")}
        description={t("apps.empty_hint")}
        action={
          <Button asChild size="sm">
            <Link to="/jobs">{t("apps.go_jobs")}</Link>
          </Button>
        }
      />
    );
  }

  return (
    <div className="grid gap-6">
      <SearchInput
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder={t("apps.search")}
        aria-label={t("apps.search")}
        className="max-w-sm"
      />
      {GROUPS.map((g) => {
        const list = groups[g];
        const extra = g === "running" ? upNext : [];
        const n = list.length + extra.length;
        if (!n) return null;
        return (
          <Group key={g} id={`group-${g}`} title={t(`apps.group_${g}` as MessageKey)} count={n} open={open[g]} onToggle={() => setOpen({ ...open, [g]: !open[g] })} you={g === "waiting"}>
            {list.map((a) => (
              <AppRow key={a.id} app={a} prompt={status?.prompts.find((p) => p.application_id === a.id)} />
            ))}
            {extra.map((j) => (
              <QueuedRow key={`job-${j.id}`} job={j} />
            ))}
          </Group>
        );
      })}
      {q && GROUPS.every((g) => !groups[g].length) && !upNext.length && <EmptyState title={t("apps.no_match")} />}
    </div>
  );
}

function Group({
  id,
  title,
  count,
  open,
  onToggle,
  you,
  children,
}: {
  id: string;
  title: string;
  count: number;
  open: boolean;
  onToggle: () => void;
  you?: boolean;
  children: ReactNode;
}) {
  return (
    <section aria-labelledby={id}>
      <h2 id={id} className="border-b border-line">
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={open}
          className="flex w-full items-baseline gap-2 py-2 text-left text-heading font-semibold"
        >
          <span aria-hidden className={cn("inline-block w-3 text-ink-3 transition-transform", open && "rotate-90")}>
            ›
          </span>
          {title}
          <span className={cn("tabular text-meta font-normal", you ? "font-semibold text-accent" : "text-ink-3")}>{count}</span>
        </button>
      </h2>
      {open && <ul>{children}</ul>}
    </section>
  );
}

const rowClass = cn(
  rowHover,
  "grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3 py-2.5 sm:grid-cols-[auto_minmax(0,1.2fr)_minmax(0,1fr)_auto]",
);

function AppRow({ app, prompt }: { app: ApplicationSummary; prompt?: Prompt }) {
  const { t, tp, lang } = useI18n();
  const due = followUpDue(app);
  let info: ReactNode = null;
  let tone = "text-ink-2";
  if (app.status === "needs_input") {
    const n = prompt?.payload.questions?.length || app.open_questions;
    info = n ? `${t("prompt.kind_questions")} · ${tp("prompt.questions_count", n)}` : t("prompt.kind_questions");
    tone = "font-medium text-accent";
  } else if (app.status === "needs_review" || app.status === "ready") {
    info = t(app.status === "ready" ? "status.ready" : "prompt.kind_confirm");
    tone = "font-medium text-accent";
  } else if (app.status === "running" || app.status === "paused" || app.status === "skipped") {
    info = t(`status.${app.status}`);
  } else if (app.status === "failed") {
    info = app.error || t("status.failed");
    tone = "text-danger";
  } else if (due) {
    info = t("apps.followup_due", { when: formatRelative(app.follow_up_at, lang) });
    tone = "font-medium text-accent";
  } else if (app.follow_up_at && canFollowUp(app.status)) {
    info = t("apps.followup_at", { when: formatRelative(app.follow_up_at, lang) });
  } else if (app.notes) {
    info = app.notes.split("\n")[0];
  }
  return (
    <li className="border-b border-line">
      <Link to={`/applications/${app.id}`} className={rowClass}>
        <StatusGlyph status={app.status} />
        <span className="min-w-0">
          <span className="block truncate font-semibold">{app.title}</span>
          <span className="block truncate text-meta text-ink-2">
            {app.company}
            {info && <span className={cn("sm:hidden", tone)}> · {info}</span>}
          </span>
        </span>
        <span className={cn("hidden truncate text-meta sm:block", tone)}>{info}</span>
        <span className="tabular text-meta whitespace-nowrap text-ink-3">{formatDate(app.submitted_at ?? app.started_at, lang)}</span>
      </Link>
    </li>
  );
}

function QueuedRow({ job }: { job: JobSummary }) {
  const { t } = useI18n();
  return (
    <li className="border-b border-line">
      <Link to={`/jobs?view=queued&job=${job.id}`} className={rowClass}>
        <StatusGlyph status="queued" />
        <span className="min-w-0">
          <span className="block truncate font-semibold">{job.title}</span>
          <span className="block truncate text-meta text-ink-2">{job.company}</span>
        </span>
        <span className="hidden truncate text-meta text-ink-2 sm:block">{t("status.queued")}</span>
        <span className="text-meta text-ink-3">–</span>
      </Link>
    </li>
  );
}
