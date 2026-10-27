import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Ban,
  BookmarkCheck,
  Bookmark,
  Building2,
  CalendarClock,
  ChevronDown,
  CircleAlert,
  Clock,
  Ellipsis,
  ExternalLink,
  Languages,
  Play,
  Sparkles,
} from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { useBackendText } from "@/lib/backendText";
import { useRoleNames } from "@/lib/hooks";
import { useI18n } from "@/lib/i18n";
import type { MessageKey } from "@/lib/messages";
import type { JobDetail } from "@/lib/types";
import { cn, formatDate, formatRelative, hostOf, sourceName } from "@/lib/utils";
import { ApplyDialog } from "./actions";
import { CompanyAvatar, FitDots, RoleBadge, ScoreRing, StatusBadge, WhereLabel } from "./domain";
import { Menu, MenuContent, MenuItem, MenuLabel, MenuSeparator, MenuTrigger, Sheet } from "./ui/overlays";
import { Badge, Button, Skeleton, Textarea } from "./ui/primitives";

function ScoreBreakdown({ job }: { job: JobDetail }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const label = (key: string) =>
    key === "role" ? t("score.role", { role: job.category }) : t(`score.${key}` as MessageKey);
  return (
    <section className="mx-6 mt-6">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex w-full items-center justify-between text-[0.875rem] font-semibold"
        aria-expanded={open}
      >
        {t("score.title")}
        <span className="flex items-center gap-2 font-normal text-fg-muted">
          {t("score.total", { score: Math.round(job.score * 10) / 10, max: job.score_max })}
          <ChevronDown className={cn("size-4 transition-transform", open && "rotate-180")} />
        </span>
      </button>
      {open && (
        <ul className="mt-2 divide-y divide-border rounded-lg border border-border text-footnote">
          {job.score_parts.map((p) => (
            <li key={p.key} className="flex items-center justify-between gap-3 px-3 py-2">
              <span className="text-fg-muted">{label(p.key)}</span>
              <span className={cn("tabular font-medium", p.points < 0 ? "text-danger" : p.points > 0 ? "text-fg" : "text-fg-subtle")}>
                {p.points > 0 ? "+" : ""}
                {Math.round(p.points * 10) / 10}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function JobSheet({ jobId, onClose }: { jobId: number | null; onClose: () => void }) {
  const { t, lang } = useI18n();
  const backendText = useBackendText();
  const qc = useQueryClient();
  const roles = useRoleNames();
  const { data: job, isLoading } = useQuery({
    queryKey: ["job", jobId],
    queryFn: () => api.job(jobId as number),
    enabled: jobId !== null,
  });
  const [notes, setNotes] = useState("");
  const [showDesc, setShowDesc] = useState(false);
  const [applyOpen, setApplyOpen] = useState(false);
  useEffect(() => {
    setNotes(job?.notes ?? "");
    setShowDesc(false);
  }, [job?.id, job?.notes]);

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["job", jobId] });
    qc.invalidateQueries({ queryKey: ["jobs"] });
    qc.invalidateQueries({ queryKey: ["status"] });
    qc.invalidateQueries({ queryKey: ["pipeline"] });
  };
  const patchJob = useMutation({
    mutationFn: (body: Parameters<typeof api.patchJob>[1]) => api.patchJob(jobId as number, body),
    onSuccess: refresh,
    onError: (e: Error) => toast.error(e.message),
  });
  const mark = useMutation({
    mutationFn: (status: "applied" | "interview" | "rejected" | "offer") => api.markJob(jobId as number, status),
    onSuccess: () => {
      toast.success(t("job.marked"));
      refresh();
    },
  });
  const exclude = useMutation({
    mutationFn: (kind: "job" | "company") =>
      api.createExclusion(kind, kind === "job" ? String(jobId) : (job?.company ?? ""), t("job.excluded_reason")),
    onSuccess: () => {
      toast.success(t("job.excluded"));
      refresh();
      onClose();
    },
  });

  return (
    <Sheet
      open={jobId !== null}
      onOpenChange={(v) => !v && onClose()}
      title={job ? job.company : t("common.loading")}
      actions={
        job && (
          <Button asChild variant="ghost" size="icon-sm" aria-label={t("job.open_posting")}>
            <a href={job.url} target="_blank" rel="noreferrer">
              <ExternalLink />
            </a>
          </Button>
        )
      }
    >
      {isLoading || !job ? (
        <div className="space-y-4 p-6">
          <Skeleton className="h-8 w-2/3" />
          <Skeleton className="h-4 w-1/3" />
          <Skeleton className="h-32 w-full" />
        </div>
      ) : (
        <div className="pb-10">
          <div className="px-6 pt-6">
            <div className="flex items-start gap-4">
              <CompanyAvatar name={job.company} size={48} />
              <div className="min-w-0 flex-1">
                <h2 className="text-title2 font-bold tracking-[-0.02em] text-balance">{job.title}</h2>
                <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-footnote text-fg-muted">
                  <span className="inline-flex items-center gap-1">
                    <Building2 className="size-3.5" />
                    {job.company}
                  </span>
                  <span>·</span>
                  <WhereLabel where={job.where} workplace={job.workplace} location={job.location} />
                </div>
              </div>
              <ScoreRing score={job.score} size={44} />
            </div>
            <div className="mt-4 flex flex-wrap items-center gap-1.5">
              <RoleBadge category={job.category} roles={roles} />
              <Badge>{t(`level.${job.level}` as MessageKey)}</Badge>
              <Badge tone="outline">
                <FitDots fit={job.fit} />
                <span className="ml-1">{t("job.stack")}</span>
              </Badge>
              {job.status === "closed" && <Badge tone="danger">{t("job.closed")}</Badge>}
              <StatusBadge status={job.app_status} />
              <Badge tone="outline">
                {sourceName(job.source)}
                {hostOf(job.url) && !hostOf(job.url).includes(sourceName(job.source).toLowerCase()) ? ` · ${hostOf(job.url)}` : ""}
              </Badge>
            </div>

            <div className="mt-5 flex flex-wrap gap-2">
              <Button
                variant="primary"
                onClick={() => setApplyOpen(true)}
                disabled={!job.verdict.ok && job.app_status !== "failed"}
              >
                <Play />
                {t("job.apply_now")}
              </Button>
              <Button
                variant={job.queued ? "soft" : "outline"}
                onClick={() => patchJob.mutate({ queued: !job.queued })}
                disabled={!job.verdict.ok && !job.queued}
              >
                <Clock />
                {job.queued ? t("job.queued") : t("job.queue")}
              </Button>
              <Button variant="outline" size="icon" onClick={() => patchJob.mutate({ starred: !job.starred })} aria-label={t("job.star")}>
                {job.starred ? <BookmarkCheck className="text-primary" /> : <Bookmark />}
              </Button>
              <Menu>
                <MenuTrigger asChild>
                  <Button variant="outline" size="icon" aria-label={t("common.more")}>
                    <Ellipsis />
                  </Button>
                </MenuTrigger>
                <MenuContent>
                  <MenuLabel>{t("job.set_status")}</MenuLabel>
                  {(["applied", "interview", "offer", "rejected"] as const).map((s) => (
                    <MenuItem key={s} onSelect={() => mark.mutate(s)}>
                      {t(`mark.${s}` as MessageKey)}
                    </MenuItem>
                  ))}
                  <MenuSeparator />
                  <MenuItem icon={<Ban />} onSelect={() => exclude.mutate("job")}>
                    {t("job.exclude_job")}
                  </MenuItem>
                  <MenuItem icon={<Ban />} danger onSelect={() => exclude.mutate("company")}>
                    {t("job.exclude_company", { company: job.company })}
                  </MenuItem>
                </MenuContent>
              </Menu>
            </div>
            {!job.verdict.ok && (
              <p className="mt-3 flex items-start gap-2 rounded-md bg-surface-2 px-3 py-2 text-footnote text-fg-muted">
                <CircleAlert className="mt-0.5 size-4 shrink-0" />
                {backendText(job.verdict.code, job.verdict.params, job.verdict.reason)}
              </p>
            )}
          </div>

          <ScoreBreakdown job={job} />

          {job.enriched && (
            <section className="mx-6 mt-6 rounded-lg border border-border bg-surface-2/50 p-4">
              <h3 className="flex items-center gap-2 text-[0.875rem] font-semibold">
                <Sparkles className="size-4 text-primary" />
                {t("job.assessment")}
              </h3>
              {job.enrichment.summary && <p className="mt-2 text-body leading-relaxed">{job.enrichment.summary}</p>}
              {job.enrichment.fit_reason && (
                <p className="mt-2 text-footnote text-fg-muted">
                  <span className="font-medium text-fg">{t("job.fit_reason")}: </span>
                  {job.enrichment.fit_reason}
                </p>
              )}
              <div className="mt-3 flex flex-wrap gap-1.5">
                {typeof job.enrichment.required_years === "number" && job.enrichment.required_years > 0 && (
                  <Badge tone="outline">{t("job.years", { n: job.enrichment.required_years })}</Badge>
                )}
                {job.enrichment.german_required && (
                  <Badge tone="outline">
                    <Languages />
                    {t("job.german")}
                  </Badge>
                )}
                {(job.enrichment.red_flags ?? []).map((f) => (
                  <Badge key={f} tone="warning">
                    <CircleAlert />
                    {f}
                  </Badge>
                ))}
              </div>
            </section>
          )}

          <section className="mx-6 mt-6">
            <h3 className="mb-2 text-[0.875rem] font-semibold">{t("job.notes")}</h3>
            <Textarea
              value={notes}
              placeholder={t("job.notes_placeholder")}
              onChange={(e) => setNotes(e.target.value)}
              onBlur={() => notes !== job.notes && patchJob.mutate({ notes })}
              className="min-h-20"
            />
          </section>

          {job.applications.length > 0 && (
            <section className="mx-6 mt-6">
              <h3 className="mb-2 text-[0.875rem] font-semibold">{t("job.applications")}</h3>
              <div className="divide-y divide-border overflow-hidden rounded-lg border border-border">
                {job.applications.map((a) => (
                  <Link
                    key={a.id}
                    to={`/applications/${a.id}`}
                    className="flex items-center justify-between gap-3 px-4 py-3 hover:bg-surface-2"
                  >
                    <div className="min-w-0">
                      <div className="text-footnote text-fg-muted">
                        #{a.id} · {formatRelative(a.started_at, lang)}
                      </div>
                      <div className="truncate text-[0.875rem]">{a.error || a.confirmation || t(`mode.${a.mode}` as MessageKey)}</div>
                    </div>
                    <StatusBadge status={a.status} />
                  </Link>
                ))}
              </div>
            </section>
          )}

          {job.description && (
            <section className="mx-6 mt-6">
              <button
                type="button"
                onClick={() => setShowDesc(!showDesc)}
                className="flex w-full items-center justify-between text-[0.875rem] font-semibold"
              >
                {t("job.description")}
                <ChevronDown className={cn("size-4 text-fg-muted transition-transform", showDesc && "rotate-180")} />
              </button>
              <div
                className={cn(
                  "mt-2 whitespace-pre-line text-footnote leading-relaxed text-fg-muted",
                  !showDesc && "line-clamp-6",
                )}
              >
                {job.description}
              </div>
            </section>
          )}

          <section className="mx-6 mt-6">
            <h3 className="mb-2 flex items-center gap-2 text-[0.875rem] font-semibold">
              <CalendarClock className="size-4 text-fg-muted" />
              {t("job.history")}
            </h3>
            <ol className="space-y-1.5 text-footnote text-fg-muted">
              {job.history.map((h, i) => (
                <li key={i} className="flex gap-3">
                  <span className="tabular w-28 shrink-0">{formatDate(h.seen_at, lang)}</span>
                  <span>{t(`change.${h.change}` as MessageKey)}</span>
                </li>
              ))}
            </ol>
          </section>
          <ApplyDialog open={applyOpen} onOpenChange={setApplyOpen} jobIds={[job.id]} />
        </div>
      )}
    </Sheet>
  );
}
