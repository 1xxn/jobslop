import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronUp, Ellipsis } from "lucide-react";
import { type ReactNode, useEffect, useState } from "react";
import { Link } from "react-router";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { useBackendText } from "@/lib/backendText";
import { useI18n } from "@/lib/i18n";
import type { MessageKey } from "@/lib/messages";
import type { JobDetail as Job } from "@/lib/types";
import { cn, formatDate, formatRelative, hostOf, sourceName } from "@/lib/utils";
import { ApplyDialog } from "./actions";
import { SCORE_MAX, StatusLabel } from "./domain";
import { Menu, MenuContent, MenuItem, MenuLabel, MenuSeparator, MenuTrigger } from "./ui/overlays";
import { Button, Kbd, rowHover, Skeleton, Textarea } from "./ui/primitives";

/** Die drei Entscheidungen zu einer Stelle – liegen bei der Liste, weil sie dort die Auswahl weiterschieben. */
export interface Decisions {
  queue: () => void;
  star: () => void;
  dismiss: () => void;
  busy?: boolean;
}

export interface Position {
  index: number;
  total: number;
  prev: () => void;
  next: () => void;
}

/** Bewerben · Merken · Aussortieren als gleichwertige Wahl (kein Primärknopf) – mit Tastenkürzel A, S, X. */
export function DecisionButtons({ job, decisions, fill }: { job: Job; decisions: Decisions; fill?: boolean }) {
  const { t } = useI18n();
  const pressed = "aria-pressed:border-accent aria-pressed:bg-accent-soft aria-pressed:text-accent";
  const restoreOnly = job.excluded && job.verdict.code !== "guard.excluded_job";
  return (
    <>
      <Button
        aria-pressed={job.queued}
        className={cn(pressed, fill && "flex-1")}
        onClick={decisions.queue}
        disabled={decisions.busy || (!job.verdict.ok && !job.queued && job.app_status !== "failed")}
      >
        {job.queued ? t("decide.queued_state") : t("decide.queue")}
        {!fill && <Kbd>A</Kbd>}
      </Button>
      <Button aria-pressed={job.starred} className={cn(pressed, fill && "flex-1")} onClick={decisions.star} disabled={decisions.busy}>
        {job.starred ? t("decide.starred_state") : t("decide.star")}
        {!fill && <Kbd>S</Kbd>}
      </Button>
      <Button className={cn(fill && "flex-1")} onClick={decisions.dismiss} disabled={decisions.busy || restoreOnly}>
        {job.excluded ? t("decide.restore") : t("decide.dismiss")}
        {!fill && <Kbd>X</Kbd>}
      </Button>
    </>
  );
}

function Block({ title, children, aside }: { title: ReactNode; children: ReactNode; aside?: ReactNode }) {
  return (
    <section className="grid gap-1.5">
      <div className="flex items-baseline justify-between gap-3">
        <h3 className="text-body font-semibold">{title}</h3>
        {aside}
      </div>
      {children}
    </section>
  );
}

/**
 * Eine Stelle: Kopf, Entscheidungen, warum sie so viele Punkte hat, Einschätzung von Claude, Beschreibung, Notizen,
 * Bewerbungen und Verlauf. Wird neben der Liste (breit) oder in einer Seitenleiste (schmal) gezeigt.
 */
export function JobDetail({
  jobId,
  decisions,
  position,
  showDecisions = true,
}: {
  jobId: number;
  decisions: Decisions;
  position?: Position;
  showDecisions?: boolean;
}) {
  const { t, lang } = useI18n();
  const backendText = useBackendText();
  const qc = useQueryClient();
  const { data: job, isLoading, isError } = useQuery({ queryKey: ["job", jobId], queryFn: () => api.job(jobId) });
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
  const saveNotes = useMutation({
    mutationFn: (value: string) => api.patchJob(jobId, { notes: value }),
    onSuccess: refresh,
    onError: (e: Error) => toast.error(e.message),
  });
  const mark = useMutation({
    mutationFn: (status: "applied" | "interview" | "rejected" | "offer") => api.markJob(jobId, status),
    onSuccess: () => {
      toast.success(t("job.marked"));
      refresh();
    },
    onError: (e: Error) => toast.error(e.message),
  });
  const excludeCompany = useMutation({
    mutationFn: (company: string) => api.createExclusion("company", company, t("job.excluded_reason")),
    onSuccess: (r, company) => {
      toast(t("decide.company_dismissed", { company }), {
        action: { label: t("common.undo"), onClick: () => api.deleteExclusion(r.id).then(refresh) },
      });
      refresh();
    },
    onError: (e: Error) => toast.error(e.message),
  });

  if (isError) return <p className="py-8 text-meta text-danger">{t("jobs.load_error")}</p>;
  if (isLoading || !job) {
    return (
      <div className="grid gap-3 py-2" aria-busy="true">
        <Skeleton className="h-6 w-3/4" />
        <Skeleton className="h-4 w-1/2" />
        <Skeleton className="mt-4 h-24" />
      </div>
    );
  }

  const place = [job.location.split(";")[0] || t(job.where === "R" ? "where.remote" : "where.onsite"), job.workplace]
    .filter(Boolean)
    .join(", ");
  const source = sourceName(job.source, t) + (!job.board && hostOf(job.url) ? ` · ${hostOf(job.url)}` : "");
  const label = (key: string) => (key === "role" ? t("score.role", { role: job.category }) : t(`score.${key}` as MessageKey));
  const e = job.enrichment ?? {};
  const watch = [
    ...(e.red_flags ?? []),
    ...(typeof e.required_years === "number" && e.required_years > 0 ? [t("job.years", { n: e.required_years })] : []),
    ...(e.german_required ? [t("job.german")] : []),
  ];
  const headingId = `job-${job.id}-title`;

  return (
    <article aria-labelledby={headingId} className="grid gap-6">
      <header className="grid gap-1">
        <h2 id={headingId} className="text-title font-semibold tracking-[-0.01em] text-balance">
          {job.title}
        </h2>
        <p className="text-meta text-ink-2">
          {[job.company, place, job.level === "S" ? t("level.S") : null, source, t("job.found", { when: formatRelative(job.first_seen, lang) })]
            .filter(Boolean)
            .join(" · ")}
          {" · "}
          <a href={job.url} target="_blank" rel="noreferrer" className="font-medium text-accent hover:underline">
            {t("job.open_posting")} ↗
          </a>
        </p>
        {job.status === "closed" && <p className="text-meta font-medium text-danger">{t("job.closed")}</p>}
      </header>

      {showDecisions && (
        <div className="flex flex-wrap items-center gap-2">
          <DecisionButtons job={job} decisions={decisions} />
          <div className="ml-auto flex items-center gap-1">
            {position && (
              <>
                <Button variant="quiet" size="icon-sm" onClick={position.prev} disabled={position.index <= 0} aria-label={t("jobs.prev")}>
                  <ChevronUp />
                </Button>
                <span className="tabular text-small text-ink-3">
                  {position.index + 1} / {position.total}
                </span>
                <Button
                  variant="quiet"
                  size="icon-sm"
                  onClick={position.next}
                  disabled={position.index >= position.total - 1}
                  aria-label={t("jobs.next")}
                >
                  <ChevronDown />
                </Button>
              </>
            )}
            <JobMenu job={job} onApply={() => setApplyOpen(true)} onMark={mark.mutate} onExcludeCompany={excludeCompany.mutate} />
          </div>
        </div>
      )}
      {!showDecisions && (
        <div className="-mt-3 flex justify-end">
          <JobMenu job={job} onApply={() => setApplyOpen(true)} onMark={mark.mutate} onExcludeCompany={excludeCompany.mutate} />
        </div>
      )}

      {!job.verdict.ok && (
        <p className="-mt-3 text-meta text-ink-2">
          {backendText(job.verdict.code, job.verdict.params, job.verdict.reason)}
          {job.excluded && job.verdict.code !== "guard.excluded_job" && (
            <>
              {" "}
              <Link to="/settings/exclusions" className="font-medium text-accent hover:underline">
                {t("decide.edit_rules")}
              </Link>
            </>
          )}
        </p>
      )}

      <Block title={t("score.why", { score: (Math.round(job.score * 10) / 10).toLocaleString(lang), max: SCORE_MAX })}>
        <dl className="border-t border-line text-meta">
          {job.score_parts.map((p) => (
            <div key={p.key} className="flex justify-between gap-3 border-b border-line py-1.5">
              <dt className="text-ink-2">{label(p.key)}</dt>
              <dd className={cn("tabular font-semibold", p.points < 0 ? "text-danger" : p.points === 0 && "font-normal text-ink-3")}>
                {p.points > 0 ? "+" : ""}
                {(Math.round(p.points * 10) / 10).toLocaleString(lang)}
              </dd>
            </div>
          ))}
        </dl>
      </Block>

      {job.enriched && (
        <Block title={t("job.assessment")}>
          {e.summary && <p className="text-read">{e.summary}</p>}
          {e.fit_reason && (
            <p className="text-meta text-ink-2">
              <span className="font-medium text-ink">{t("job.fit_reason")}: </span>
              {e.fit_reason}
            </p>
          )}
          {watch.length > 0 && (
            <p className="text-meta text-ink-2">
              <span className="font-medium text-amber">{t("job.watch")}: </span>
              {watch.join(" · ")}
            </p>
          )}
        </Block>
      )}

      {job.description && (
        <Block
          title={t("job.description")}
          aside={
            <button type="button" onClick={() => setShowDesc(!showDesc)} className="text-meta font-medium text-accent hover:underline">
              {showDesc ? t("job.description_less") : t("job.description_more")}
            </button>
          }
        >
          <p className={cn("text-meta whitespace-pre-line text-ink-2", !showDesc && "line-clamp-6")}>{job.description}</p>
        </Block>
      )}

      <Block title={t("job.notes")}>
        <Textarea
          value={notes}
          aria-label={t("job.notes")}
          placeholder={t("job.notes_placeholder")}
          onChange={(ev) => setNotes(ev.target.value)}
          onBlur={() => notes !== job.notes && saveNotes.mutate(notes)}
          className="min-h-20"
        />
      </Block>

      {job.applications.length > 0 && (
        <Block title={t("job.applications")}>
          <ul className="border-t border-line">
            {job.applications.map((a) => (
              <li key={a.id} className="border-b border-line">
                <Link
                  to={`/applications/${a.id}`}
                  className={cn(rowHover, "flex items-center justify-between gap-3 py-2")}
                >
                  <span className="min-w-0 truncate text-meta text-ink-2">
                    {formatRelative(a.started_at, lang)} · {a.error || a.confirmation || t(`mode.${a.mode}` as MessageKey)}
                  </span>
                  <StatusLabel status={a.status} />
                </Link>
              </li>
            ))}
          </ul>
        </Block>
      )}

      <Block title={t("job.history")}>
        <ol className="grid gap-1 text-meta text-ink-2">
          {job.history.map((h, i) => (
            <li key={i} className="grid grid-cols-[7rem_minmax(0,1fr)] gap-3">
              <span className="tabular text-ink-3">{formatDate(h.seen_at, lang)}</span>
              <span>{t(`change.${h.change}` as MessageKey)}</span>
            </li>
          ))}
        </ol>
      </Block>

      <ApplyDialog open={applyOpen} onOpenChange={setApplyOpen} jobIds={[job.id]} />
    </article>
  );
}

function JobMenu({
  job,
  onApply,
  onMark,
  onExcludeCompany,
}: {
  job: Job;
  onApply: () => void;
  onMark: (s: "applied" | "interview" | "rejected" | "offer") => void;
  onExcludeCompany: (company: string) => void;
}) {
  const { t } = useI18n();
  return (
    <Menu>
      <MenuTrigger asChild>
        <Button variant="quiet" size="icon-sm" aria-label={t("common.more")}>
          <Ellipsis />
        </Button>
      </MenuTrigger>
      <MenuContent>
        <MenuItem onSelect={onApply} disabled={!job.verdict.ok && job.app_status !== "failed"}>
          {t("decide.apply_now")}
        </MenuItem>
        <MenuSeparator />
        <MenuLabel>{t("job.set_status")}</MenuLabel>
        {(["applied", "interview", "offer", "rejected"] as const).map((s) => (
          <MenuItem key={s} onSelect={() => onMark(s)}>
            {t(`mark.${s}` as MessageKey)}
          </MenuItem>
        ))}
        <MenuSeparator />
        <MenuItem danger onSelect={() => onExcludeCompany(job.company)}>
          {t("job.exclude_company", { company: job.company })}
        </MenuItem>
      </MenuContent>
    </Menu>
  );
}
