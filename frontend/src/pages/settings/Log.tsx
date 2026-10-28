import { useQuery } from "@tanstack/react-query";
import { Tooltip } from "@/components/ui/overlays";
import { Button, EmptyState, Section } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { codeOf, useBackendText } from "@/lib/backendText";
import { useAutopilotRun, useCrawl, useStatus } from "@/lib/hooks";
import { useI18n } from "@/lib/i18n";
import { hasMessage } from "@/lib/messages";
import type { ActivityItem } from "@/lib/types";
import { formatDateTime, groupByDay, parseDate } from "@/lib/utils";

/** Protokoll: Suchläufe und alles, was jobslop zuletzt getan hat (früher die Seite „Aktivität“). */
export function LogSettings() {
  const { t, lang } = useI18n();
  const { data: status } = useStatus();
  const crawls = useQuery({
    queryKey: ["crawls"],
    queryFn: api.crawls,
    refetchInterval: status?.crawl.running ? 3000 : 30_000,
  });
  const activity = useQuery({ queryKey: ["activity", 60], queryFn: () => api.activity(60), refetchInterval: 10_000 });
  const crawl = useCrawl();
  const autopilot = useAutopilotRun();

  return (
    <div className="grid gap-10">
      <div className="flex flex-wrap gap-2">
        <Button size="sm" onClick={() => crawl.mutate()} loading={!!status?.crawl.running}>
          {status?.crawl.running ? t("crawl.running_short") : t("crawl.start")}
        </Button>
        <Button
          size="sm"
          onClick={() => autopilot.mutate()}
          loading={!!status?.autopilot.running}
          disabled={!!status?.demo}
        >
          {t("autopilot.run_now")}
        </Button>
      </div>

      <Section title={t("activity.crawls")}>
        {crawls.data?.length === 0 && <EmptyState title={t("activity.no_crawls")} />}
        {!!crawls.data?.length && (
          <div className="overflow-x-auto">
            <table className="w-full text-meta">
              <thead className="text-left text-small text-ink-3">
                <tr className="border-b border-line">
                  <th className="py-2 pr-3 font-medium">#</th>
                  <th className="py-2 pr-3 font-medium">{t("activity.when")}</th>
                  <th className="hidden py-2 pr-3 text-right font-medium sm:table-cell">{t("activity.fetched")}</th>
                  <th className="py-2 pr-3 text-right font-medium">{t("activity.matching")}</th>
                  <th className="py-2 pr-3 text-right font-medium">{t("activity.new")}</th>
                  <th className="hidden py-2 pr-3 text-right font-medium sm:table-cell">{t("activity.closed")}</th>
                  <th className="py-2 font-medium">{t("activity.state")}</th>
                </tr>
              </thead>
              <tbody className="tabular">
                {crawls.data.map((c) => (
                  <tr key={c.id} className="border-b border-line">
                    <td className="py-2 pr-3 text-ink-3">{c.id}</td>
                    <td className="py-2 pr-3 whitespace-nowrap">{formatDateTime(c.started_at, lang)}</td>
                    <td className="hidden py-2 pr-3 text-right text-ink-2 sm:table-cell">{c.stats.fetched ?? "–"}</td>
                    <td className="py-2 pr-3 text-right text-ink-2">{c.stats.kept ?? "–"}</td>
                    <td className="py-2 pr-3 text-right font-semibold">{c.stats.new ? `+${c.stats.new}` : "0"}</td>
                    <td className="hidden py-2 pr-3 text-right text-ink-2 sm:table-cell">{c.stats.closed ?? 0}</td>
                    <td className="py-2 whitespace-nowrap">
                      {c.status === "running" ? (
                        <span className="text-accent">{t("activity.running")}</span>
                      ) : c.errors.length ? (
                        <Tooltip content={<span className="whitespace-pre-line">{c.errors.slice(0, 4).join("\n")}</span>}>
                          <button type="button" className="text-danger underline decoration-dotted underline-offset-4">
                            {t("activity.errors", { n: c.errors.length })}
                          </button>
                        </Tooltip>
                      ) : (
                        <span className="text-ink-3">{t("activity.ok")}</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>

      <Section title={t("activity.log")}>
        {activity.data?.length === 0 && <EmptyState title={t("overview.no_activity")} />}
        <ActivityByDay items={activity.data ?? []} />
      </Section>
    </div>
  );
}

/** Ereignisse nach Tagen gruppiert, neueste zuerst. */
function ActivityByDay({ items }: { items: ActivityItem[] }) {
  const { t, lang } = useI18n();
  const backendText = useBackendText();
  const kindLabel = (kind: string) => {
    const key = `kind.${kind}`;
    return hasMessage(key) ? t(key) : kind;
  };
  return (
    <div className="grid gap-4 pt-3">
      {groupByDay(items, (item) => item.ts, lang, true).map(([day, list]) => (
        <section key={day}>
          <h3 className="pb-1 text-small font-semibold text-ink-2">{day}</h3>
          <ol className="grid gap-1 text-meta">
            {list.map((item) => (
              <li key={item.id} className="grid grid-cols-[3.5rem_minmax(0,1fr)] gap-x-4">
                <span className="tabular text-ink-3">
                  {parseDate(item.ts)?.toLocaleTimeString(lang, { hour: "2-digit", minute: "2-digit" })}
                </span>
                <span className="break-words">
                  {backendText(...codeOf(item.data), item.message)}
                  <span className="text-ink-3"> · {kindLabel(item.kind)}</span>
                </span>
              </li>
            ))}
          </ol>
        </section>
      ))}
    </div>
  );
}
