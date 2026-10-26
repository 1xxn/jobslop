import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, CircleAlert, CircleCheck, ExternalLink, FileText, Image, ListTree, MessageCircleQuestion } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router";
import { toast } from "sonner";
import { CompanyAvatar, StatusBadge } from "@/components/domain";
import { PromptCard } from "@/components/PromptCard";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/controls";
import { Dialog, DialogContent } from "@/components/ui/overlays";
import { Badge, Button, Card, CardBody, CardHeader, EmptyState, Input, Select, Skeleton } from "@/components/ui/primitives";
import { api, artifactUrl } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import type { MessageKey } from "@/lib/messages";
import { cn, formatDateTime } from "@/lib/utils";

export function ApplicationDetailPage() {
  const { id } = useParams();
  const appId = Number(id);
  const { t, lang } = useI18n();
  const qc = useQueryClient();
  const app = useQuery({ queryKey: ["application", appId], queryFn: () => api.application(appId), refetchInterval: 4000 });
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [shot, setShot] = useState<string | null>(null);
  const answer = useMutation({
    mutationFn: () => api.answerApplication(appId, answers, true),
    onSuccess: (r) => {
      toast.success(t("detail.answers_saved", { n: r.saved }));
      qc.invalidateQueries({ queryKey: ["application", appId] });
      qc.invalidateQueries({ queryKey: ["status"] });
    },
  });
  const setStatus = useMutation({
    mutationFn: (status: string) => api.patchApplication(appId, { status }),
    onSuccess: () => {
      toast.success(t("common.saved"));
      qc.invalidateQueries({ queryKey: ["application", appId] });
      qc.invalidateQueries({ queryKey: ["pipeline"] });
    },
  });

  if (app.isLoading || !app.data) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-10 w-1/2" />
        <Skeleton className="h-64" />
      </div>
    );
  }
  const a = app.data;
  const inPipeline = ["submitted", "manual", "interview", "offer", "rejected"].includes(a.status);

  return (
    <>
      <Link to="/applications" className="mb-4 inline-flex items-center gap-1.5 text-footnote font-medium text-fg-muted hover:text-fg">
        <ArrowLeft className="size-4" />
        {t("nav.applications")}
      </Link>
      <header className="mb-6 flex flex-wrap items-start gap-4 animate-slide-up">
        <CompanyAvatar name={a.company} size={52} />
        <div className="min-w-0 flex-1">
          <h1 className="text-title1 font-bold tracking-[-0.025em] text-balance">{a.title}</h1>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-footnote text-fg-muted">
            <span>{a.company}</span>
            <span>·</span>
            <span>
              #{a.id} · {t(`mode.${a.mode}` as MessageKey)} · {formatDateTime(a.started_at, lang)}
            </span>
            <StatusBadge status={a.status} />
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          {inPipeline && (
            <Select value={a.status} onChange={(e) => setStatus.mutate(e.target.value)} className="w-44" aria-label={t("job.set_status")}>
              {(["submitted", "interview", "offer", "rejected"] as const).map((s) => (
                <option key={s} value={s}>
                  {t(`status.${s}` as MessageKey)}
                </option>
              ))}
            </Select>
          )}
          <Button asChild variant="outline">
            <Link to={`/jobs?job=${a.job_id}`}>{t("detail.job")}</Link>
          </Button>
          {a.final_url && (
            <Button asChild variant="ghost" size="icon" aria-label={t("detail.final_url")}>
              <a href={a.final_url} target="_blank" rel="noreferrer">
                <ExternalLink />
              </a>
            </Button>
          )}
        </div>
      </header>

      {a.error && (
        <div className="mb-6 flex items-start gap-3 rounded-lg border border-danger/30 bg-danger-soft px-4 py-3 text-[0.875rem]">
          <CircleAlert className="mt-0.5 size-4 shrink-0 text-danger" />
          <span className="break-words">{a.error}</span>
        </div>
      )}
      {!a.error && a.confirmation && (
        <div className="mb-6 flex items-start gap-3 rounded-lg border border-border bg-surface-2 px-4 py-3 text-[0.875rem]">
          <CircleCheck className="mt-0.5 size-4 shrink-0 text-success" />
          <span className="break-words">{a.confirmation}</span>
        </div>
      )}

      {a.prompts.length > 0 && (
        <div className="mb-6 space-y-4">
          {a.prompts.map((p) => (
            <PromptCard key={p.id} prompt={p} />
          ))}
        </div>
      )}

      {a.questions.length > 0 && a.prompts.length === 0 && (
        <Card className="mb-6">
          <CardHeader title={t("detail.questions")} description={t("detail.questions_hint")} icon={<MessageCircleQuestion />} />
          <CardBody>
            <form
              className="space-y-4"
              onSubmit={(e) => {
                e.preventDefault();
                answer.mutate();
              }}
            >
              {a.questions.map((q, i) => (
                <div key={i} className="space-y-1.5">
                  <label className="block text-[0.875rem] font-medium" htmlFor={`aq-${i}`}>
                    {q.label || q.question}
                  </label>
                  {q.options?.length ? (
                    <Select id={`aq-${i}`} value={answers[String(i)] ?? ""} onChange={(e) => setAnswers({ ...answers, [String(i)]: e.target.value })}>
                      <option value="">{t("common.choose")}</option>
                      {q.options.map((o) => (
                        <option key={o}>{o}</option>
                      ))}
                    </Select>
                  ) : (
                    <Input id={`aq-${i}`} value={answers[String(i)] ?? ""} onChange={(e) => setAnswers({ ...answers, [String(i)]: e.target.value })} />
                  )}
                </div>
              ))}
              <div className="flex justify-end">
                <Button type="submit" variant="primary" loading={answer.isPending} disabled={!Object.values(answers).some(Boolean)}>
                  {t("detail.save_requeue")}
                </Button>
              </div>
            </form>
          </CardBody>
        </Card>
      )}

      <Tabs defaultValue="timeline">
        <TabsList>
          <TabsTrigger value="timeline">
            <ListTree className="size-4" />
            {t("detail.timeline")}
          </TabsTrigger>
          <TabsTrigger value="shots" count={a.screenshots.length}>
            <Image className="size-4" />
            {t("detail.screenshots")}
          </TabsTrigger>
          <TabsTrigger value="filled" count={a.filled.length}>
            <CircleCheck className="size-4" />
            {t("detail.filled")}
          </TabsTrigger>
          <TabsTrigger value="docs" count={a.documents.length}>
            <FileText className="size-4" />
            {t("detail.documents")}
          </TabsTrigger>
        </TabsList>

        <TabsContent value="timeline" className="pt-5">
          {a.events.length === 0 ? (
            <EmptyState title={t("detail.no_events")} />
          ) : (
            <ol className="relative ml-2 border-l border-border">
              {a.events.map((e, i) => (
                <li key={i} className="relative pb-5 pl-6 last:pb-0">
                  <span
                    className={cn(
                      "absolute top-1.5 -left-[5px] size-[9px] rounded-full border-2 border-bg",
                      e.kind === "error" ? "bg-danger" : e.kind === "submit" ? "bg-success" : "bg-primary",
                    )}
                  />
                  <div className="flex flex-wrap items-baseline gap-2">
                    <Badge tone="outline">{e.kind}</Badge>
                    <span className="tabular text-caption text-fg-subtle">{formatDateTime(e.ts, lang)}</span>
                  </div>
                  <p className="mt-1 text-[0.875rem] leading-relaxed break-words whitespace-pre-line">{e.message}</p>
                </li>
              ))}
            </ol>
          )}
        </TabsContent>

        <TabsContent value="shots" className="pt-5">
          {a.screenshots.length === 0 ? (
            <EmptyState title={t("detail.no_shots")} />
          ) : (
            <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
              {a.screenshots.map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => setShot(s)}
                  className="group overflow-hidden rounded-lg border border-border bg-surface-2 text-left"
                >
                  <img src={artifactUrl(a.id, s)} alt={s} loading="lazy" className="aspect-[4/3] w-full object-cover object-top transition-transform group-hover:scale-[1.02]" />
                  <div className="truncate px-3 py-2 text-caption text-fg-muted">{s}</div>
                </button>
              ))}
            </div>
          )}
        </TabsContent>

        <TabsContent value="filled" className="pt-5">
          {a.filled.length === 0 ? (
            <EmptyState title={t("detail.no_filled")} />
          ) : (
            <Card className="overflow-x-auto">
              <table className="w-full text-footnote">
                <thead className="border-b border-border text-left text-caption text-fg-subtle">
                  <tr>
                    <th className="px-4 py-2 font-medium">{t("detail.field")}</th>
                    <th className="px-4 py-2 font-medium">{t("detail.value")}</th>
                    <th className="px-4 py-2 font-medium">{t("detail.source")}</th>
                  </tr>
                </thead>
                <tbody>
                  {a.filled.map((r, i) => (
                    <tr key={i} className="border-b border-border last:border-0">
                      <td className="max-w-56 px-4 py-2 align-top text-fg-muted">{r.label}</td>
                      <td className="px-4 py-2 align-top break-words">
                        {r.ok === false ? (
                          <span className="text-danger">
                            {r.value} – {r.detail}
                          </span>
                        ) : (
                          r.value
                        )}
                      </td>
                      <td className="px-4 py-2 align-top whitespace-nowrap text-fg-subtle">
                        {r.source} {r.confidence === "low" && <Badge tone="warning">{t("prompt.unsure")}</Badge>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          )}
        </TabsContent>

        <TabsContent value="docs" className="pt-5">
          {a.documents.length === 0 ? (
            <EmptyState title={t("detail.no_docs")} />
          ) : (
            <div className="flex flex-wrap gap-2">
              {a.documents.map((d) => (
                <Button key={d} asChild variant="outline">
                  <a href={artifactUrl(a.id, d)} target="_blank" rel="noreferrer">
                    <FileText />
                    {d}
                  </a>
                </Button>
              ))}
            </div>
          )}
        </TabsContent>
      </Tabs>

      <Dialog open={shot !== null} onOpenChange={(v) => !v && setShot(null)}>
        {shot && (
          <DialogContent title={shot} wide>
            <img src={artifactUrl(a.id, shot)} alt={shot} className="w-full rounded-md border border-border" />
          </DialogContent>
        )}
      </Dialog>
    </>
  );
}
