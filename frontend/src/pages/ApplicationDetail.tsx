import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router";
import { toast } from "sonner";
import { StatusLabel } from "@/components/domain";
import { PromptCard } from "@/components/PromptCard";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/controls";
import { Dialog, DialogContent } from "@/components/ui/overlays";
import { Button, EmptyState, Field, Input, Section, Select, Skeleton, Textarea } from "@/components/ui/primitives";
import { api, artifactUrl } from "@/lib/api";
import { effectiveStatus } from "@/lib/applications";
import { useI18n } from "@/lib/i18n";
import { hasMessage, type MessageKey } from "@/lib/messages";
import type { ApplicationDetail as Detail } from "@/lib/types";
import { cn, formatDate, formatDateTime, parseDate } from "@/lib/utils";

// Stände, die du nach dem Absenden selbst pflegst (wie im Board)
const PIPELINE = ["submitted", "manual", "interview", "offer", "rejected"];

/** Eine Bewerbung: was passiert ist (Verlauf, Felder, Screenshots, Dokumente) – und rechts, was du pflegst. */
export function ApplicationDetailPage() {
  const { id } = useParams();
  const appId = Number(id);
  const { t, lang } = useI18n();
  const app = useQuery({ queryKey: ["application", appId], queryFn: () => api.application(appId), refetchInterval: 4000 });
  const [shot, setShot] = useState<string | null>(null);

  if (app.isError) {
    return (
      <EmptyState
        title={t("detail.load_error")}
        action={
          <Button asChild size="sm">
            <Link to="/applications">{t("nav.applications")}</Link>
          </Button>
        }
      />
    );
  }
  if (app.isLoading || !app.data) {
    return (
      <div className="grid gap-4" aria-busy="true">
        <Skeleton className="h-6 w-1/2" />
        <Skeleton className="h-48" />
      </div>
    );
  }
  const a = app.data;
  const sent = a.submitted_at ? t("detail.sent_on", { date: formatDateTime(a.submitted_at, lang) }) : null;

  return (
    <>
      <Link to="/applications" className="mb-3 inline-flex items-center gap-1 text-meta font-medium text-ink-2 hover:text-ink">
        <ArrowLeft className="size-4" aria-hidden />
        {t("nav.applications")}
      </Link>

      <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_15rem]">
        <div className="grid min-w-0 content-start gap-6">
          <header className="grid gap-1">
            <h1 className="text-title font-semibold tracking-[-0.01em] text-balance">{a.title}</h1>
            <p className="text-meta text-ink-2">
              {[a.company, sent ?? t("detail.started_on", { date: formatDateTime(a.started_at, lang) }), t(`mode.${a.mode}` as MessageKey)]
                .filter(Boolean)
                .join(" · ")}
              {" · "}
              <Link to={`/jobs?job=${a.job_id}`} className="font-medium text-accent hover:underline">
                {t("detail.job")}
              </Link>
              {a.final_url && (
                <>
                  {" · "}
                  <a href={a.final_url} target="_blank" rel="noreferrer" className="font-medium text-accent hover:underline">
                    {t("detail.final_url")} ↗
                  </a>
                </>
              )}
            </p>
          </header>

          {a.error && <p className="text-body text-danger [overflow-wrap:anywhere]">{a.error}</p>}
          {!a.error && a.confirmation && (
            <blockquote className="border-l-2 border-line pl-3 text-meta text-ink-2 [overflow-wrap:anywhere]">
              {a.confirmation}
            </blockquote>
          )}

          {a.prompts.map((p) => (
            <PromptCard key={p.id} prompt={p} showLink={false} />
          ))}

          {a.questions.length > 0 && a.prompts.length === 0 && <OpenQuestions app={a} />}

          <Tabs defaultValue="timeline">
            <TabsList>
              <TabsTrigger value="timeline">{t("detail.timeline")}</TabsTrigger>
              <TabsTrigger value="filled" count={a.filled.length}>
                {t("detail.filled")}
              </TabsTrigger>
              <TabsTrigger value="shots" count={a.screenshots.length}>
                {t("detail.screenshots")}
              </TabsTrigger>
              <TabsTrigger value="docs" count={a.documents.length}>
                {t("detail.documents")}
              </TabsTrigger>
            </TabsList>

            <TabsContent value="timeline" className="pt-4 focus:outline-none">
              {a.events.length === 0 ? (
                <p className="text-meta text-ink-3">{t("detail.no_events")}</p>
              ) : (
                <Timeline events={a.events} />
              )}
            </TabsContent>

            <TabsContent value="filled" className="pt-4 focus:outline-none">
              {a.filled.length === 0 ? (
                <p className="text-meta text-ink-3">{t("detail.no_filled")}</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-meta">
                    <thead className="text-left text-small text-ink-3">
                      <tr className="border-b border-line">
                        <th className="py-2 pr-3 font-medium">{t("detail.field")}</th>
                        <th className="py-2 pr-3 font-medium">{t("detail.value")}</th>
                        <th className="py-2 font-medium">{t("detail.source")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {a.filled.map((r, i) => (
                        <tr key={i} className="border-b border-line">
                          <td className="max-w-56 py-2 pr-3 align-top text-ink-2">{r.label}</td>
                          <td className="py-2 pr-3 align-top [overflow-wrap:anywhere]">
                            {r.ok === false ? (
                              <span className="text-danger">
                                {r.value} – {r.detail}
                              </span>
                            ) : (
                              r.value
                            )}
                          </td>
                          <td className="py-2 align-top whitespace-nowrap text-ink-3">
                            {r.source}
                            {r.confidence === "low" && (
                              <span className="ml-2 font-semibold text-amber">? {t("prompt.unsure")}</span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </TabsContent>

            <TabsContent value="shots" className="pt-4 focus:outline-none">
              {a.screenshots.length === 0 ? (
                <p className="text-meta text-ink-3">{t("detail.no_shots")}</p>
              ) : (
                <ul className="grid grid-cols-2 gap-3 md:grid-cols-3">
                  {a.screenshots.map((s) => (
                    <li key={s}>
                      <button
                        type="button"
                        onClick={() => setShot(s)}
                        className="w-full overflow-hidden rounded-md border border-line bg-sunken text-left hover:border-line-input"
                      >
                        <img src={artifactUrl(a.id, s)} alt={s} loading="lazy" className="aspect-[4/3] w-full object-cover object-top" />
                        <span className="block truncate px-2 py-1.5 text-small text-ink-2">{s}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </TabsContent>

            <TabsContent value="docs" className="pt-4 focus:outline-none">
              {a.documents.length === 0 ? (
                <p className="text-meta text-ink-3">{t("detail.no_docs")}</p>
              ) : (
                <ul className="grid gap-1">
                  {a.documents.map((d) => (
                    <li key={d}>
                      <a href={artifactUrl(a.id, d)} target="_blank" rel="noreferrer" className="text-body font-medium text-accent hover:underline">
                        {d} ↗
                      </a>
                    </li>
                  ))}
                </ul>
              )}
            </TabsContent>
          </Tabs>
        </div>

        <Rail app={a} />
      </div>

      <Dialog open={shot !== null} onOpenChange={(v) => !v && setShot(null)}>
        {shot && (
          <DialogContent title={shot} wide>
            <img src={artifactUrl(a.id, shot)} alt={shot} className="w-full rounded-md border border-line" />
          </DialogContent>
        )}
      </Dialog>
    </>
  );
}

/** Rechte Spalte: Stand, Nachfassen und Notizen – das, was du nach dem Absenden pflegst. */
function Rail({ app }: { app: Detail }) {
  const { t, lang } = useI18n();
  const qc = useQueryClient();
  const [notes, setNotes] = useState(app.notes);
  const [date, setDate] = useState(app.follow_up_at?.slice(0, 10) ?? "");
  useEffect(() => setNotes(app.notes), [app.notes]);
  useEffect(() => setDate(app.follow_up_at?.slice(0, 10) ?? ""), [app.follow_up_at]);
  const patch = useMutation({
    mutationFn: (body: Parameters<typeof api.patchApplication>[1]) => api.patchApplication(app.id, body),
    onSuccess: () => {
      toast.success(t("common.saved"));
      qc.invalidateQueries({ queryKey: ["application", app.id] });
      qc.invalidateQueries({ queryKey: ["applications"] });
      qc.invalidateQueries({ queryKey: ["pipeline"] });
      qc.invalidateQueries({ queryKey: ["status"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });
  const editable = PIPELINE.includes(app.status);
  return (
    <aside className="grid content-start gap-4 lg:border-l lg:border-line lg:pl-6" aria-label={t("detail.rail")}>
      <Field label={t("detail.stage")} htmlFor="app-stage">
        {editable ? (
          <Select id="app-stage" value={app.status} onChange={(e) => patch.mutate({ status: e.target.value })}>
            {(["submitted", "interview", "offer", "rejected"] as const).map((s) => (
              <option key={s} value={s}>
                {t(`status.${s}`)}
              </option>
            ))}
            {app.status === "manual" && <option value="manual">{t("status.manual")}</option>}
          </Select>
        ) : (
          <StatusLabel status={effectiveStatus(app, app.prompts)} className="h-8" />
        )}
      </Field>
      {editable && (
        <Field label={t("pipeline.followup")} hint={t("pipeline.followup_hint")} htmlFor="app-followup">
          <Input
            id="app-followup"
            type="date"
            value={date}
            onChange={(e) => {
              setDate(e.target.value);
              patch.mutate(e.target.value ? { follow_up_at: `${e.target.value}T09:00:00` } : { clear_follow_up: true });
            }}
          />
        </Field>
      )}
      <Field label={t("job.notes")} htmlFor="app-notes">
        <Textarea
          id="app-notes"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          onBlur={() => notes !== app.notes && patch.mutate({ notes })}
          placeholder={t("pipeline.notes_placeholder")}
          className="min-h-28"
        />
      </Field>
      <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1 border-t border-line pt-3 text-meta">
        <dt className="text-ink-3">{t("detail.mode")}</dt>
        <dd className="text-right">{t(`mode.${app.mode}` as MessageKey)}</dd>
        <dt className="text-ink-3">{t("detail.run")}</dt>
        <dd className="tabular text-right">#{app.id}</dd>
        <dt className="text-ink-3">{t("detail.started")}</dt>
        <dd className="tabular text-right">{formatDate(app.started_at, lang)}</dd>
      </dl>
    </aside>
  );
}

/** Verlauf nach Tagen gruppiert: Uhrzeit, Ereignis in Worten, Meldung. */
function Timeline({ events }: { events: Detail["events"] }) {
  const { t, lang } = useI18n();
  const days = new Map<string, Detail["events"]>();
  for (const e of events) {
    const day = parseDate(e.ts)?.toLocaleDateString(lang, { weekday: "long", day: "numeric", month: "long" }) ?? "";
    days.set(day, [...(days.get(day) ?? []), e]);
  }
  const kind = (k: string) => (hasMessage(`event.${k}`) ? t(`event.${k}` as MessageKey) : k);
  return (
    <div className="grid gap-4">
      {[...days].map(([day, list]) => (
        <section key={day}>
          <h3 className="pb-1 text-small font-semibold text-ink-2">{day}</h3>
          <ol className="grid gap-1.5 text-meta">
            {list.map((e, i) => (
              <li key={i} className="grid grid-cols-[3.5rem_minmax(0,1fr)] gap-x-4">
                <span className="tabular text-ink-3">
                  {parseDate(e.ts)?.toLocaleTimeString(lang, { hour: "2-digit", minute: "2-digit" })}
                </span>
                <span className="[overflow-wrap:anywhere] whitespace-pre-line">
                  <span className={cn("font-medium", e.kind === "error" ? "text-danger" : e.kind === "submit" && "text-positive")}>
                    {kind(e.kind)}
                  </span>
                  <span className="text-ink-2"> · {e.message}</span>
                </span>
              </li>
            ))}
          </ol>
        </section>
      ))}
    </div>
  );
}

/** Fragen, die ein Lauf offen gelassen hat: Antworten wandern in die Antwortbank, die Stelle kommt wieder dran. */
function OpenQuestions({ app }: { app: Detail }) {
  const { t, tp } = useI18n();
  const qc = useQueryClient();
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const save = useMutation({
    mutationFn: () => api.answerApplication(app.id, answers, true),
    onSuccess: (r) => {
      toast.success(tp("detail.answers_saved", r.saved));
      qc.invalidateQueries({ queryKey: ["application", app.id] });
      qc.invalidateQueries({ queryKey: ["status"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });
  return (
    <Section title={t("detail.questions")}>
      <form
        className="grid gap-4 pt-3"
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate();
        }}
      >
        <p className="text-meta text-ink-2">{t("detail.questions_hint")}</p>
        {app.questions.map((q, i) => (
          <Field key={i} label={q.label || q.question} htmlFor={`aq-${i}`}>
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
          </Field>
        ))}
        <div className="flex justify-end">
          <Button type="submit" variant="primary" loading={save.isPending} disabled={!Object.values(answers).some(Boolean)}>
            {t("detail.save_requeue")}
          </Button>
        </div>
      </form>
    </Section>
  );
}
