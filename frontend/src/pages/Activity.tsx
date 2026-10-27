import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, CircleAlert, History, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { RunnerPanel } from "@/components/actions";
import { PageHeader } from "@/components/domain";
import { Tooltip } from "@/components/ui/overlays";
import { Badge, Button, Card, CardHeader, EmptyState } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { codeOf, useBackendText } from "@/lib/backendText";
import { useStatus } from "@/lib/hooks";
import { useI18n } from "@/lib/i18n";
import { type MessageKey, messages } from "@/lib/messages";
import { formatDateTime, formatRelative } from "@/lib/utils";

export function ActivityPage() {
  const { t, lang } = useI18n();
  const backendText = useBackendText();
  const qc = useQueryClient();
  const { data: status } = useStatus();
  const crawls = useQuery({ queryKey: ["crawls"], queryFn: api.crawls, refetchInterval: status?.crawl.running ? 3000 : 30_000 });
  const activity = useQuery({ queryKey: ["activity", 60], queryFn: () => api.activity(60), refetchInterval: 10_000 });
  const crawl = useMutation({
    mutationFn: api.crawl,
    onSuccess: (r) => {
      toast(r.started ? t("crawl.started") : t("crawl.running"));
      qc.invalidateQueries({ queryKey: ["status"] });
    },
  });
  const autopilot = useMutation({
    mutationFn: api.autopilotRun,
    onSuccess: () => toast(t("autopilot.started")),
    onError: (e: Error) => toast.error(e.message),
  });

  return (
    <>
      <PageHeader
        title={t("activity.title")}
        description={t("activity.description")}
        actions={
          <>
            <Button variant="outline" onClick={() => autopilot.mutate()} loading={!!status?.autopilot.running}>
              {!status?.autopilot.running && <Bot />}
              {t("autopilot.run_now")}
            </Button>
            <Button variant="outline" onClick={() => crawl.mutate()} loading={!!status?.crawl.running}>
              {!status?.crawl.running && <RefreshCw />}
              {status?.crawl.running ? t("crawl.running_short") : t("crawl.start")}
            </Button>
          </>
        }
      />
      <RunnerPanel className="mb-6" />

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <Card className="overflow-hidden">
          <CardHeader title={t("activity.crawls")} icon={<History />} />
          {crawls.data?.length === 0 && <EmptyState title={t("activity.no_crawls")} />}
          <div className="overflow-x-auto">
            <table className="w-full text-footnote">
              <thead className="border-y border-border text-left text-caption text-fg-subtle">
                <tr>
                  <th className="px-5 py-2 font-medium">#</th>
                  <th className="px-3 py-2 font-medium">{t("activity.when")}</th>
                  <th className="px-3 py-2 text-right font-medium">{t("activity.fetched")}</th>
                  <th className="px-3 py-2 text-right font-medium">{t("activity.matching")}</th>
                  <th className="px-3 py-2 text-right font-medium">{t("activity.new")}</th>
                  <th className="px-3 py-2 text-right font-medium">{t("activity.closed")}</th>
                  <th className="px-5 py-2 font-medium">{t("activity.state")}</th>
                </tr>
              </thead>
              <tbody className="tabular">
                {crawls.data?.map((c) => (
                  <tr key={c.id} className="border-b border-border last:border-0">
                    <td className="px-5 py-2.5 text-fg-muted">{c.id}</td>
                    <td className="px-3 py-2.5 whitespace-nowrap">{formatDateTime(c.started_at, lang)}</td>
                    <td className="px-3 py-2.5 text-right text-fg-muted">{c.stats.fetched ?? "–"}</td>
                    <td className="px-3 py-2.5 text-right">{c.stats.kept ?? "–"}</td>
                    <td className="px-3 py-2.5 text-right font-semibold text-success">{c.stats.new ? `+${c.stats.new}` : "0"}</td>
                    <td className="px-3 py-2.5 text-right text-fg-muted">{c.stats.closed ?? 0}</td>
                    <td className="px-5 py-2.5">
                      {c.status === "running" ? (
                        <Badge tone="info">{t("activity.running")}</Badge>
                      ) : c.errors.length ? (
                        <Tooltip content={c.errors.slice(0, 4).join("\n")}>
                          <Badge tone="warning">
                            <CircleAlert />
                            {t("activity.errors", { n: c.errors.length })}
                          </Badge>
                        </Tooltip>
                      ) : (
                        <Badge tone="success">{t("activity.ok")}</Badge>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>

        <Card>
          <CardHeader title={t("activity.log")} />
          <ol className="space-y-3 px-5 pb-5">
            {activity.data?.length === 0 && <li className="text-footnote text-fg-muted">{t("overview.no_activity")}</li>}
            {activity.data?.map((item) => (
              <li key={item.id} className="flex gap-3">
                <Badge tone="outline" className="mt-0.5 shrink-0">
                  {`kind.${item.kind}` in messages.de ? t(`kind.${item.kind}` as MessageKey) : item.kind}
                </Badge>
                <div className="min-w-0">
                  <div className="text-footnote leading-snug break-words">{backendText(...codeOf(item.data), item.message)}</div>
                  <div className="text-caption text-fg-subtle">{formatRelative(item.ts, lang)}</div>
                </div>
              </li>
            ))}
          </ol>
        </Card>
      </div>
    </>
  );
}
