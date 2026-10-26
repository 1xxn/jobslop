import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CircleAlert, Hand, MessageCircleQuestion, MonitorSmartphone, Send, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { toast } from "sonner";
import { api, artifactUrl } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import type { Prompt } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Badge, Button, Card, Input, Select } from "./ui/primitives";

function screenshotName(path: string | undefined): string {
  return path ? (path.split(/[\\/]/).pop() ?? "") : "";
}

export function PromptCard({ prompt, compact }: { prompt: Prompt; compact?: boolean }) {
  const { t } = useI18n();
  const qc = useQueryClient();
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [zoom, setZoom] = useState(false);
  const send = useMutation({
    mutationFn: (body: Parameters<typeof api.answerPrompt>[1]) => api.answerPrompt(prompt.id, body),
    onSuccess: () => {
      toast.success(t("prompt.sent"));
      qc.invalidateQueries({ queryKey: ["status"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const title = prompt.payload.title ?? "";
  const icon =
    prompt.kind === "questions" ? <MessageCircleQuestion /> : prompt.kind === "confirm" ? <ShieldCheck /> : <Hand />;
  const heading =
    prompt.kind === "questions"
      ? t("prompt.questions")
      : prompt.kind === "confirm"
        ? t("prompt.confirm")
        : t("prompt.handoff");

  return (
    <Card className="overflow-hidden border-warning/40 animate-slide-up">
      <div className="flex items-start gap-3 border-b border-border bg-warning-soft/60 px-5 py-3.5">
        <span className="mt-0.5 grid size-8 shrink-0 place-items-center rounded-full bg-warning text-white [&_svg]:size-4">
          {icon}
        </span>
        <div className="min-w-0 flex-1">
          <div className="text-headline font-semibold">{heading}</div>
          <div className="truncate text-footnote text-fg-muted">{title}</div>
        </div>
        <Link
          to={`/applications/${prompt.application_id}`}
          className="shrink-0 text-footnote font-medium text-primary hover:underline"
        >
          {t("prompt.open_run")}
        </Link>
      </div>

      {prompt.kind === "questions" && (
        <form
          className="space-y-4 px-5 py-4"
          onSubmit={(e) => {
            e.preventDefault();
            send.mutate({ answers });
          }}
        >
          <p className="text-footnote text-fg-muted">{t("prompt.questions_hint")}</p>
          {(prompt.payload.questions ?? []).map((q) => (
            <div key={q.field_id} className="space-y-1.5">
              <label className="block text-[0.875rem] font-medium" htmlFor={`q-${prompt.id}-${q.field_id}`}>
                {q.question}
              </label>
              {q.why && <p className="text-caption text-fg-subtle">{q.why}</p>}
              {q.options.length > 0 ? (
                <Select
                  id={`q-${prompt.id}-${q.field_id}`}
                  value={answers[q.field_id] ?? ""}
                  onChange={(e) => setAnswers({ ...answers, [q.field_id]: e.target.value })}
                >
                  <option value="">{t("common.choose")}</option>
                  {q.options.map((o) => (
                    <option key={o}>{o}</option>
                  ))}
                </Select>
              ) : (
                <Input
                  id={`q-${prompt.id}-${q.field_id}`}
                  value={answers[q.field_id] ?? ""}
                  onChange={(e) => setAnswers({ ...answers, [q.field_id]: e.target.value })}
                />
              )}
            </div>
          ))}
          <div className="flex flex-wrap justify-end gap-2 pt-1">
            <Button type="button" variant="ghost" onClick={() => send.mutate({ skip: true })} disabled={send.isPending}>
              {t("prompt.skip")}
            </Button>
            <Button
              type="submit"
              variant="primary"
              loading={send.isPending}
              disabled={(prompt.payload.questions ?? []).some((q) => !answers[q.field_id]?.trim())}
            >
              {t("prompt.answer")}
            </Button>
          </div>
        </form>
      )}

      {prompt.kind === "confirm" && (
        <div className="px-5 py-4">
          <div className={cn("grid gap-4", !compact && prompt.payload.screenshot && "md:grid-cols-[minmax(0,1fr)_280px]")}>
            <div className="max-h-72 overflow-y-auto rounded-md border border-border">
              <table className="w-full text-footnote">
                <tbody>
                  {(prompt.payload.rows ?? []).map((r, i) => (
                    <tr key={`${r.label}-${i}`} className="border-b border-border last:border-0">
                      <td className="w-2/5 px-3 py-2 align-top text-fg-muted">{r.label}</td>
                      <td className="px-3 py-2 align-top break-words">
                        {r.value || <span className="text-fg-subtle">–</span>}
                        {r.confidence === "low" && (
                          <Badge tone="warning" className="ml-2">
                            <CircleAlert />
                            {t("prompt.unsure")}
                          </Badge>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {!compact && prompt.payload.screenshot && (
              <button
                type="button"
                onClick={() => setZoom(!zoom)}
                className="overflow-hidden rounded-md border border-border bg-surface-2"
                aria-label={t("prompt.screenshot")}
              >
                <img
                  src={artifactUrl(prompt.application_id, screenshotName(prompt.payload.screenshot))}
                  alt={t("prompt.screenshot")}
                  className={cn("w-full object-cover object-top", zoom ? "max-h-none" : "max-h-72")}
                />
              </button>
            )}
          </div>
          <p className="mt-3 flex items-center gap-2 text-footnote text-fg-muted">
            <MonitorSmartphone className="size-4" />
            {t("prompt.confirm_hint")}
          </p>
          <div className="mt-4 flex flex-wrap justify-end gap-2">
            <Button variant="ghost" onClick={() => send.mutate({ decision: "reject" })} disabled={send.isPending}>
              {t("prompt.reject")}
            </Button>
            <Button variant="outline" onClick={() => send.mutate({ decision: "manual" })} disabled={send.isPending}>
              {t("prompt.manual")}
            </Button>
            <Button variant="primary" onClick={() => send.mutate({ decision: "submit" })} loading={send.isPending}>
              <Send />
              {t("prompt.submit")}
            </Button>
          </div>
        </div>
      )}

      {prompt.kind === "handoff" && (
        <div className="px-5 py-4">
          <p className="text-body leading-relaxed">{prompt.payload.message}</p>
          <div className="mt-4 flex flex-wrap justify-end gap-2">
            <Button variant="ghost" onClick={() => send.mutate({ abort: true })} disabled={send.isPending}>
              {t("prompt.abort")}
            </Button>
            <Button variant="primary" onClick={() => send.mutate({ done: true })} loading={send.isPending}>
              {t("prompt.done")}
            </Button>
          </div>
        </div>
      )}
    </Card>
  );
}
