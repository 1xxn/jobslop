import { useQuery } from "@tanstack/react-query";
import { ChartColumn, ChevronRight, ListChecks } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { CompanyAvatar, PageHeader, StatusBadge, WeeklyChart } from "@/components/domain";
import { Segmented } from "@/components/ui/controls";
import { Card, CardBody, CardHeader, EmptyState, Skeleton } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import type { MessageKey } from "@/lib/messages";
import { formatRelative } from "@/lib/utils";

const FILTERS = {
  all: "",
  attention: "needs_input,needs_review,paused,ready",
  sent: "submitted,manual,interview,offer,rejected",
  failed: "failed,skipped",
} as const;
type Filter = keyof typeof FILTERS;

export function ApplicationsPage() {
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
      <PageHeader title={t("apps.title")} description={t("apps.description")} />
      {weeks.some((w) => w.sent > 0) && (
        <Card className="mb-6">
          <CardHeader title={t("overview.weekly")} description={t("overview.weekly_hint")} icon={<ChartColumn />} />
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
        {apps.data?.length === 0 && <EmptyState icon={<ListChecks />} title={t("apps.empty")} description={t("apps.empty_hint")} />}
        <ul className="divide-y divide-border">
          {apps.data?.map((a) => (
            <li key={a.id}>
              <Link to={`/applications/${a.id}`} className="flex items-center gap-4 px-4 py-3 transition-colors hover:bg-surface-2/70">
                <CompanyAvatar name={a.company} />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-[0.9375rem] font-semibold">{a.title}</div>
                  <div className="truncate text-footnote text-fg-muted">
                    {a.company} · {t(`mode.${a.mode}` as MessageKey)} · {formatRelative(a.started_at, lang)}
                  </div>
                  {(a.error || a.confirmation) && (
                    <div className="mt-0.5 truncate text-caption text-fg-subtle">{a.error || a.confirmation}</div>
                  )}
                </div>
                <StatusBadge status={a.status} />
                <ChevronRight className="size-4 shrink-0 text-fg-subtle" />
              </Link>
            </li>
          ))}
        </ul>
      </Card>
    </>
  );
}
