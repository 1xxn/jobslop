import { useQuery } from "@tanstack/react-query";
import { ChevronRight } from "lucide-react";
import { useState } from "react";
import { Link, useSearchParams } from "react-router";
import { CompanyAvatar, PageHeader, StatusLabel, WeeklyChart } from "@/components/domain";
import { Segmented } from "@/components/ui/controls";
import { Card, CardBody, CardHeader, EmptyState, Skeleton } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import type { MessageKey } from "@/lib/messages";
import { formatRelative } from "@/lib/utils";
import { PipelineBoard } from "./Pipeline";

const FILTERS = {
  all: "",
  attention: "needs_input,needs_review,paused,ready",
  sent: "submitted,manual,interview,offer,rejected",
  failed: "failed,skipped",
} as const;
type Filter = keyof typeof FILTERS;

type View = "list" | "board";

/** Alle Bewerbungen – als Liste oder als Board (die frühere Pipeline). */
export function ApplicationsPage() {
  const { t } = useI18n();
  const [params, setParams] = useSearchParams();
  const view: View = params.get("view") === "board" ? "board" : "list";
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
      />
      {view === "board" ? <PipelineBoard /> : <ApplicationList />}
    </>
  );
}

function ApplicationList() {
  const { t, lang } = useI18n();
  const [filter, setFilter] = useState<Filter>("all");
  const apps = useQuery({
    queryKey: ["applications", filter],
    queryFn: () => api.applications(FILTERS[filter]),
    refetchInterval: 5000,
  });
  const stats = useQuery({ queryKey: ["stats"], queryFn: api.stats, refetchInterval: 30_000 });
  const weeks = stats.data?.applications.per_week ?? [];
  return (
    <>
      {weeks.some((w) => w.sent > 0) && (
        <Card className="mb-6">
          <CardHeader title={t("overview.weekly")} description={t("overview.weekly_hint")} />
          <CardBody>
            <WeeklyChart weeks={weeks} />
          </CardBody>
        </Card>
      )}
      <Segmented<Filter>
        className="mb-4"
        value={filter}
        onChange={setFilter}
        options={[
          { value: "all", label: t("apps.filter_all") },
          { value: "attention", label: t("apps.filter_attention") },
          { value: "sent", label: t("apps.filter_sent") },
          { value: "failed", label: t("apps.filter_failed") },
        ]}
      />
      <Card className="overflow-hidden">
        {apps.isLoading && (
          <div className="space-y-2 p-4">
            {Array.from({ length: 6 }, (_, i) => (
              <Skeleton key={i} className="h-12" />
            ))}
          </div>
        )}
        {apps.data?.length === 0 && <EmptyState title={t("apps.empty")} description={t("apps.empty_hint")} />}
        <ul className="divide-y divide-line">
          {apps.data?.map((a) => (
            <li key={a.id}>
              <Link to={`/applications/${a.id}`} className="flex items-center gap-4 px-4 py-3 transition-colors hover:bg-sunken/70">
                <CompanyAvatar name={a.company} />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-body font-semibold">{a.title}</div>
                  <div className="truncate text-meta text-ink-2">
                    {a.company} · {t(`mode.${a.mode}` as MessageKey)} · {formatRelative(a.started_at, lang)}
                  </div>
                  {(a.error || a.confirmation) && (
                    <div className="mt-0.5 truncate text-small text-ink-3">{a.error || a.confirmation}</div>
                  )}
                </div>
                <StatusLabel status={a.status} />
                <ChevronRight className="size-4 shrink-0 text-ink-3" />
              </Link>
            </li>
          ))}
        </ul>
      </Card>
    </>
  );
}
