import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type Ref, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router";
import { toast } from "sonner";
import { ApplicationsSummary, PageHeader, Score, StatusGlyph } from "@/components/domain";
import { PROMPT_KIND, PromptCard } from "@/components/PromptCard";
import { Button, Card, EmptyState, Section, Skeleton } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { useStatus } from "@/lib/hooks";
import { useI18n } from "@/lib/i18n";
import type { ApplicationSummary, Prompt } from "@/lib/types";
import { cn, formatDate, formatRelative, formatWhen } from "@/lib/utils";

type Item =
  | { key: string; kind: "prompt"; prompt: Prompt }
  | { key: string; kind: "followup"; app: ApplicationSummary };

// Reihenfolge: Freigaben (der Browser wartet) → Rückfragen (der Lauf wartet) → Übergaben → fälliges Nachfassen
const PROMPT_ORDER: Record<Prompt["kind"], number> = { confirm: 0, questions: 1, handoff: 2 };

/** Heute: das eine, was dich gerade braucht, voll aufgeklappt – alles Weitere wartet als Liste darunter. */
export function TodayPage() {
  const { t, tp, lang } = useI18n();
  const { data: status } = useStatus();
  const pipeline = useQuery({ queryKey: ["pipeline"], queryFn: api.pipeline, refetchInterval: 60_000 });
  const fresh = useQuery({
    queryKey: ["jobs", "triage", "today"],
    queryFn: () => api.jobs({ view: "triage", level: "noS", limit: 3 }),
  });
  const stats = useQuery({ queryKey: ["stats"], queryFn: api.stats, refetchInterval: 60_000 });

  const items = useMemo<Item[]>(() => {
    const prompts = [...(status?.prompts ?? [])].sort(
      (a, b) => PROMPT_ORDER[a.kind] - PROMPT_ORDER[b.kind] || a.id - b.id,
    );
    return [
      ...prompts.map((p) => ({ key: `p${p.id}`, kind: "prompt" as const, prompt: p })),
      ...(pipeline.data?.follow_ups_due ?? []).map((a) => ({ key: `f${a.id}`, kind: "followup" as const, app: a })),
    ];
  }, [status?.prompts, pipeline.data]);

  const [focusKey, setFocusKey] = useState<string | null>(null);
  const focus = items.find((i) => i.key === focusKey) ?? items[0];
  const rest = items.filter((i) => i !== focus);
  const focusRef = useRef<HTMLDivElement>(null);
  const moved = useRef(false);
  useEffect(() => {
    // nach dem Auswählen in „Danach“: Fokus auf die Karte, damit Tastatur und Screenreader mitkommen
    if (moved.current) focusRef.current?.focus();
    moved.current = false;
  }, [focus?.key]);
  const pick = (key: string) => {
    moved.current = true;
    setFocusKey(key);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const toReview = status?.counts.to_review ?? 0;
  const queued = status?.counts.queued ?? 0;
  const loading = !status || pipeline.isLoading;

  return (
    <>
      <PageHeader
        title={loading ? " " : items.length ? tp("today.title", items.length) : t("today.title_none")}
        actions={
          <span className="text-meta text-ink-3">
            {new Date().toLocaleDateString(lang, { weekday: "long", day: "numeric", month: "long" })}
          </span>
        }
      />

      {loading && <Skeleton className="h-48 rounded-lg" />}

      {!loading && !items.length && (
        <p className="-mt-3 mb-2 text-meta text-ink-2">
          {status?.autopilot.enabled
            ? t("today.next_search", { when: formatWhen(status.autopilot.next_run, lang) })
            : t("today.autopilot_off")}
        </p>
      )}

      {focus?.kind === "prompt" && <PromptCard ref={focusRef} key={focus.key} prompt={focus.prompt} />}
      {focus?.kind === "followup" && <FollowUpCard ref={focusRef} key={focus.key} app={focus.app} />}

      <div className="mt-8 grid gap-10">
        {rest.length > 0 && (
          <Section title={t("today.after")} aside={rest.length}>
            <ul>
              {rest.map((item) => (
                <li key={item.key} className="border-b border-line">
                  <QueueRow item={item} onPick={() => pick(item.key)} />
                </li>
              ))}
            </ul>
          </Section>
        )}

        <Section
          title={t("today.new_jobs")}
          aside={
            <span className="flex items-center gap-3">
              {queued > 0 && (
                <Link to="/jobs?view=queued" className="hover:text-ink">
                  {tp("queue.up_next", queued)}
                </Link>
              )}
              {toReview > 0 && (
                <Link to="/jobs" className="font-medium text-accent hover:underline">
                  {tp("today.review_all", toReview)}
                </Link>
              )}
            </span>
          }
        >
          {fresh.isLoading && <Skeleton className="mt-3 h-24" />}
          {fresh.data?.items.length === 0 && (
            <EmptyState
              title={t("today.all_reviewed")}
              description={
                status?.autopilot.enabled
                  ? t("today.next_search", { when: formatWhen(status.autopilot.next_run, lang) })
                  : t("today.autopilot_off")
              }
            />
          )}
          <ul>
            {fresh.data?.items.map((j) => (
              <li key={j.id} className="border-b border-line">
                <Link
                  to={`/jobs?job=${j.id}`}
                  className="-mx-2 grid grid-cols-[minmax(0,1fr)_auto] items-center gap-4 rounded-md px-2 py-2.5 transition-colors hover:bg-sunken"
                >
                  <span className="min-w-0">
                    <span className="block truncate font-semibold">{j.title}</span>
                    <span className="block truncate text-meta text-ink-2">
                      {[j.company, j.location.split(";")[0], j.category].filter(Boolean).join(" · ")}
                    </span>
                  </span>
                  <Score score={j.score} />
                </Link>
              </li>
            ))}
          </ul>
          {!items.length && toReview > 0 && (
            <Button asChild variant="primary" className="mt-4">
              <Link to="/jobs">{tp("today.review_cta", toReview)}</Link>
            </Button>
          )}
        </Section>

        {!!stats.data?.applications.sent_total && (
          <Section
            title={t("today.applications")}
            aside={
              <Link to="/applications" className="hover:text-ink">
                {t("today.all_applications")}
              </Link>
            }
          >
            <ApplicationsSummary stats={stats.data} className="pt-3" />
          </Section>
        )}
      </div>
    </>
  );
}

/** Zeile in „Danach“: ein Klick holt den Eintrag nach oben. */
function QueueRow({ item, onPick }: { item: Item; onPick: () => void }) {
  const { t, tp, lang } = useI18n();
  const title =
    item.kind === "prompt"
      ? t(PROMPT_KIND[item.prompt.kind])
      : t("followup.with", { company: item.app.company });
  const meta =
    item.kind === "prompt"
      ? [
          item.prompt.payload.title,
          item.prompt.kind === "questions" && tp("prompt.questions_count", item.prompt.payload.questions?.length ?? 0),
        ]
          .filter(Boolean)
          .join(" · ")
      : item.app.title;
  return (
    <button
      type="button"
      onClick={onPick}
      className="-mx-2 grid w-[calc(100%+1rem)] grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3 rounded-md px-2 py-2.5 text-left transition-colors hover:bg-sunken"
    >
      <StatusGlyph status={item.kind === "prompt" ? "needs_input" : "submitted"} />
      <span className="min-w-0">
        <span className="block truncate font-semibold">{title}</span>
        <span className="block truncate text-meta text-ink-2">{meta}</span>
      </span>
      <span
        className={cn(
          "text-meta whitespace-nowrap",
          item.kind === "followup" ? "font-medium text-accent" : "text-ink-3",
        )}
      >
        {item.kind === "prompt"
          ? formatRelative(item.prompt.created_at, lang)
          : t("followup.due", { when: formatRelative(item.app.follow_up_at, lang) })}
      </span>
    </button>
  );
}

/** Fälliges Nachfassen als Fokus-Karte: erledigt (mit Rückgängig) oder in einer Woche erneut erinnern. */
function FollowUpCard({ app, ref }: { app: ApplicationSummary; ref?: Ref<HTMLDivElement> }) {
  const { t, lang } = useI18n();
  const qc = useQueryClient();
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["pipeline"] });
    qc.invalidateQueries({ queryKey: ["status"] });
  };
  const patch = useMutation({
    mutationFn: (body: Parameters<typeof api.patchApplication>[1]) => api.patchApplication(app.id, body),
    onSuccess: refresh,
    onError: (e: Error) => toast.error(e.message),
  });
  const done = () =>
    patch.mutate(
      { clear_follow_up: true },
      {
        onSuccess: () =>
          toast(t("followup.done_toast"), {
            action: {
              label: t("common.undo"),
              onClick: () => api.patchApplication(app.id, { follow_up_at: app.follow_up_at }).then(refresh),
            },
          }),
      },
    );
  const later = () => {
    const next = new Date();
    next.setDate(next.getDate() + 7);
    next.setHours(9, 0, 0, 0);
    patch.mutate(
      { follow_up_at: next.toISOString() },
      { onSuccess: () => toast(t("followup.later_toast", { when: formatDate(next.toISOString(), lang) })) },
    );
  };
  const headingId = `followup-${app.id}`;
  return (
    <Card ref={ref} tabIndex={-1} aria-labelledby={headingId} className="px-5 py-4 focus:outline-none animate-slide-up">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="text-small text-ink-3">
            {t("followup.kind")} · {app.title} · {t("followup.due", { when: formatRelative(app.follow_up_at, lang) })}
          </p>
          <h2 id={headingId} className="mt-0.5 text-heading font-semibold">
            {t("followup.with", { company: app.company })}
          </h2>
        </div>
        <Link to={`/applications/${app.id}`} className="shrink-0 text-meta font-medium text-accent hover:underline">
          {t("prompt.open_run")}
        </Link>
      </div>
      <p className="mt-2 text-meta text-ink-2">
        {t("followup.sent_on", { date: formatDate(app.submitted_at ?? app.started_at, lang) })}
      </p>
      {app.notes && <p className="mt-2 text-read whitespace-pre-line">{app.notes}</p>}
      <div className="mt-4 flex flex-wrap justify-end gap-2">
        <Button variant="secondary" onClick={later} disabled={patch.isPending}>
          {t("followup.later")}
        </Button>
        <Button variant="primary" onClick={done} loading={patch.isPending}>
          {t("followup.done")}
        </Button>
      </div>
    </Card>
  );
}
