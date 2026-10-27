import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowRight,
  Bot,
  History,
  Inbox,
  Play,
  RefreshCw,
  } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { toast } from "sonner";
import { ApplyDialog } from "@/components/actions";
import { CompanyAvatar, PageHeader, Score, Stat, StatusLabel } from "@/components/domain";
import { PromptCard } from "@/components/PromptCard";
import { Switch } from "@/components/ui/controls";
import { Button, Card, CardBody, CardHeader, EmptyState, Skeleton } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { codeOf, useBackendText } from "@/lib/backendText";
import { useStatus } from "@/lib/hooks";
import { useI18n } from "@/lib/i18n";
import { formatDateTime, formatRelative, percent } from "@/lib/utils";

function greeting(t: ReturnType<typeof useI18n>["t"]) {
  const h = new Date().getHours();
  return h < 11 ? t("overview.morning") : h < 18 ? t("overview.day") : t("overview.evening");
}

/** Startseite: was dich braucht, die besten Treffer, was als Nächstes ansteht – Statistik und Verlauf haben eigene Seiten. */
export function OverviewPage() {
  const { t, lang } = useI18n();
  const backendText = useBackendText();
  const qc = useQueryClient();
  const { data: status } = useStatus();
  const profile = useQuery({ queryKey: ["profile"], queryFn: api.profile });
  const stats = useQuery({ queryKey: ["stats"], queryFn: api.stats, refetchInterval: 30_000 });
  const top = useQuery({
    queryKey: ["jobs", "top"],
    queryFn: () => api.jobs({ view: "todo", level: "noS", limit: 6 }),
  });
  const pipeline = useQuery({ queryKey: ["pipeline"], queryFn: api.pipeline });
  const activity = useQuery({ queryKey: ["activity", 1], queryFn: () => api.activity(1), refetchInterval: 15_000 });
  const settings = useQuery({ queryKey: ["settings"], queryFn: api.settings });
  const [applyOpen, setApplyOpen] = useState(false);

  const crawl = useMutation({
    mutationFn: api.crawl,
    onSuccess: (r) => {
      toast(r.started ? t("crawl.started") : t("crawl.running"));
      qc.invalidateQueries({ queryKey: ["status"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });
  const queueTop = useMutation({
    mutationFn: () => api.queueTop(10),
    onSuccess: (r) => {
      toast.success(t("queue.added", { n: r.changed.length }));
      qc.invalidateQueries({ queryKey: ["status"] });
      qc.invalidateQueries({ queryKey: ["jobs"] });
    },
  });
  const autopilotToggle = useMutation({
    mutationFn: (enabled: boolean) => api.saveSettings({ autopilot_enabled: enabled }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["settings"] });
      qc.invalidateQueries({ queryKey: ["status"] });
    },
  });
  const autopilotRun = useMutation({
    mutationFn: api.autopilotRun,
    onSuccess: () => toast(t("autopilot.started")),
    onError: (e: Error) => toast.error(e.message),
  });

  const name = profile.data?.profile.personal.first_name;
  const prompts = status?.prompts ?? [];
  const queued = status?.counts.queued ?? 0;
  const a = stats.data?.applications;
  const followUps = pipeline.data?.follow_ups_due ?? [];
  const last = activity.data?.[0];

  return (
    <>
      <PageHeader
        title={name ? `${greeting(t)}, ${name}` : greeting(t)}
        description={new Date().toLocaleDateString(lang, { weekday: "long", day: "numeric", month: "long" })}
        actions={
          <>
            <Button variant="secondary" onClick={() => crawl.mutate()} loading={!!status?.crawl.running}>
              {!status?.crawl.running && <RefreshCw />}
              {status?.crawl.running ? t("crawl.running_short") : t("crawl.start")}
            </Button>
            <Button variant="primary" onClick={() => setApplyOpen(true)} disabled={!queued || !!status?.runner.active}>
              <Play />
              {t("overview.apply_queue", { n: queued })}
            </Button>
          </>
        }
      />

      {prompts.length > 0 && (
        <section className="mb-8 space-y-4" aria-label={t("overview.needs_you")}>
          <h2 className="flex items-center gap-2 text-heading font-semibold">
            <Inbox className="size-[18px] text-amber" />
            {t("overview.needs_you")}
          </h2>
          {prompts.map((p) => (
            <PromptCard key={p.id} prompt={p} />
          ))}
        </section>
      )}


      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {stats.isLoading ? (
          Array.from({ length: 4 }, (_, i) => <Skeleton key={i} className="h-[106px] rounded-lg" />)
        ) : (
          <>
            <Stat
              label={t("stat.open")}
              value={stats.data?.jobs.open ?? 0}
              hint={t("stat.new7", { n: stats.data?.jobs.new_7d ?? 0 })}
            />
            <Stat label={t("stat.queued")} value={queued} hint={t("stat.queued_hint")} />
            <Stat
              label={t("stat.sent")}
              value={a?.sent_total ?? 0}
              hint={t("stat.sent7", { n: a?.sent_7d ?? 0 })}
            />
            <Stat
              label={t("stat.response")}
              value={percent(a?.response_rate ?? 0, lang)}
              hint={t("stat.interview_rate", { p: percent(a?.interview_rate ?? 0, lang) })}
            />
          </>
        )}
      </div>

      <div className="mt-6 grid grid-cols-[minmax(0,1fr)] gap-6 xl:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <Card>
          <CardHeader
            title={t("overview.top_matches")}
            description={t("overview.top_matches_hint")}
            action={
              <Button asChild variant="quiet" size="sm">
                <Link to="/jobs">
                  {t("common.all")} <ArrowRight />
                </Link>
              </Button>
            }
          />
          <div className="divide-y divide-line">
            {top.isLoading &&
              Array.from({ length: 4 }, (_, i) => (
                <div key={i} className="px-5 py-3">
                  <Skeleton className="h-10" />
                </div>
              ))}
            {top.data?.items.length === 0 && (
              <EmptyState
                title={t("overview.no_jobs")}
                description={t("overview.no_jobs_hint")}
                action={
                  <Button variant="primary" onClick={() => crawl.mutate()}>
                    <RefreshCw />
                    {t("crawl.start")}
                  </Button>
                }
              />
            )}
            {top.data?.items.map((j) => (
              <Link
                key={j.id}
                to={`/jobs?job=${j.id}`}
                className="flex items-center gap-3.5 px-5 py-3 transition-colors hover:bg-sunken"
              >
                <CompanyAvatar name={j.company} />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-body font-semibold">{j.title}</div>
                  <div className="truncate text-meta text-ink-2">
                    {j.company} · {j.location.split(";")[0]}
                  </div>
                </div>
                <div className="hidden sm:block">
                  <span className="text-meta text-ink-2">{j.category}</span>
                </div>
                {j.queued && <StatusLabel status="queued" />}
                <Score score={j.score} />
              </Link>
            ))}
          </div>
          {!!top.data?.items.length && (
            <CardBody className="flex flex-wrap items-center justify-between gap-3 border-t border-line pt-4">
              <span className="text-meta text-ink-2">{t("overview.queue_hint")}</span>
              <Button size="sm" variant="secondary" onClick={() => queueTop.mutate()} loading={queueTop.isPending}>
                {t("overview.queue_top")}
              </Button>
            </CardBody>
          )}
        </Card>

        <Card className="self-start">
          <CardHeader title={t("overview.next")} />
          <div className="divide-y divide-line">
            {followUps.slice(0, 4).map((app) => (
              <Link
                key={app.id}
                to="/pipeline"
                className="flex items-center justify-between gap-3 px-5 py-3 hover:bg-sunken"
              >
                <div className="min-w-0">
                  <div className="truncate text-body font-medium">
                    {t("overview.followup_with", { company: app.company })}
                  </div>
                  <div className="truncate text-meta text-ink-2">{app.title}</div>
                </div>
                <span className="shrink-0 text-small text-amber">{formatRelative(app.follow_up_at, lang)}</span>
              </Link>
            ))}
            <div className="flex items-center gap-3 px-5 py-3">
              <Bot className="size-4 shrink-0 text-ink-2" />
              <div className="min-w-0 flex-1">
                <div className="text-body font-medium">{t("autopilot.title")}</div>
                <div className="truncate text-meta text-ink-2">
                  {status?.autopilot.next_run
                    ? t("autopilot.next", { when: formatDateTime(status.autopilot.next_run, lang) })
                    : t("autopilot.off_hint")}
                </div>
              </div>
              <Button
                size="sm"
                variant="quiet"
                onClick={() => autopilotRun.mutate()}
                loading={!!status?.autopilot.running}
                aria-label={t("autopilot.run_now")}
                disabled={!!status?.demo}
              >
                {!status?.autopilot.running && <Play />}
              </Button>
              <Switch
                label={t("autopilot.title")}
                checked={!!settings.data?.autopilot_enabled}
                onCheckedChange={(v) => autopilotToggle.mutate(v)}
              />
            </div>
            {last && (
              <Link to="/settings/log" className="flex items-center gap-3 px-5 py-3 hover:bg-sunken">
                <History className="size-4 shrink-0 text-ink-2" />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-meta">{backendText(...codeOf(last.data), last.message)}</div>
                  <div className="text-small text-ink-3">{formatRelative(last.ts, lang)}</div>
                </div>
                <ArrowRight className="size-4 shrink-0 text-ink-3" />
              </Link>
            )}
          </div>
        </Card>
      </div>
      <ApplyDialog open={applyOpen} onOpenChange={setApplyOpen} queuedCount={queued} />
    </>
  );
}
