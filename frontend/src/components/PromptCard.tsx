import { useMutation, useQueryClient } from "@tanstack/react-query";
import { forwardRef, useState } from "react";
import { Link } from "react-router";
import { toast } from "sonner";
import { api, artifactUrl } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import type { MessageKey } from "@/lib/messages";
import type { Prompt } from "@/lib/types";
import { cn, formatRelative } from "@/lib/utils";
import { Dialog, DialogContent } from "./ui/overlays";
import { Button, Card, Input, Select } from "./ui/primitives";

function screenshotName(path: string | undefined): string {
  return path ? (path.split(/[\\/]/).pop() ?? "") : "";
}

/** Kurzname der Rückfrage-Art für Listen: Freigabe, Rückfrage, Übergabe. */
export const PROMPT_KIND: Record<Prompt["kind"], MessageKey> = {
  confirm: "prompt.kind_confirm",
  questions: "prompt.kind_questions",
  handoff: "prompt.kind_handoff",
};

const HEADING: Record<Prompt["kind"], MessageKey> = {
  confirm: "prompt.confirm",
  questions: "prompt.questions",
  handoff: "prompt.handoff",
};

/**
 * Das eine Objekt, an dem du gerade handelst: Freigabe vor dem Absenden, Rückfrage oder Übergabe – mit genau einer
 * Hauptaktion. „Absenden“ bekommt bewusst kein Tastenkürzel.
 */
export const PromptCard = forwardRef<HTMLDivElement, { prompt: Prompt; showLink?: boolean; className?: string }>(
  function PromptCard({ prompt, showLink = true, className }, ref) {
    const { t, tp, lang } = useI18n();
    const qc = useQueryClient();
    const [answers, setAnswers] = useState<Record<string, string>>({});
    const [shot, setShot] = useState(false);
    const send = useMutation({
      mutationFn: (body: Parameters<typeof api.answerPrompt>[1]) => api.answerPrompt(prompt.id, body),
      onSuccess: () => {
        toast.success(t("prompt.sent"));
        qc.invalidateQueries({ queryKey: ["status"] });
        qc.invalidateQueries({ queryKey: ["application", prompt.application_id] });
      },
      // z. B. „nicht mehr offen“, weil der Lauf vorbei ist: die veraltete Karte verschwinden lassen
      onError: () => qc.invalidateQueries({ queryKey: ["status"] }),
    });
    const questions = prompt.payload.questions ?? [];
    const rows = prompt.payload.rows ?? [];
    const screenshot = screenshotName(prompt.payload.screenshot);
    const headingId = `prompt-${prompt.id}`;

    return (
      <Card ref={ref} tabIndex={-1} aria-labelledby={headingId} className={cn("px-5 py-4 focus:outline-none animate-slide-up", className)}>
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <p className="text-small text-ink-3">
              {t(PROMPT_KIND[prompt.kind])} · {prompt.payload.title}
              {prompt.created_at && <> · {formatRelative(prompt.created_at, lang)}</>}
            </p>
            <h2 id={headingId} className="mt-0.5 text-heading font-semibold">
              {t(HEADING[prompt.kind])}
            </h2>
          </div>
          {showLink && (
            <Link
              to={`/applications/${prompt.application_id}`}
              className="shrink-0 text-meta font-medium text-accent hover:underline"
            >
              {t("prompt.open_run")}
            </Link>
          )}
        </div>

        {prompt.kind === "questions" && (
          <form
            className="mt-3 grid gap-4"
            onSubmit={(e) => {
              e.preventDefault();
              send.mutate({ answers });
            }}
          >
            <p className="text-meta text-ink-2">
              {tp("prompt.questions_count", questions.length)} · {t("prompt.questions_hint")}
            </p>
            {questions.map((q) => (
              <div key={q.field_id} className="grid gap-1">
                <label className="text-body font-medium" htmlFor={`q-${prompt.id}-${q.field_id}`}>
                  {q.question}
                </label>
                {q.why && <p className="text-small text-ink-3">{q.why}</p>}
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
            <div className="flex flex-wrap justify-end gap-2">
              <Button type="button" variant="quiet" onClick={() => send.mutate({ skip: true })} disabled={send.isPending}>
                {t("prompt.skip")}
              </Button>
              <Button
                type="submit"
                variant="primary"
                loading={send.isPending}
                disabled={questions.some((q) => !answers[q.field_id]?.trim())}
              >
                {t("prompt.answer")}
              </Button>
            </div>
          </form>
        )}

        {prompt.kind === "confirm" && (
          <div className="mt-3">
            <dl className="grid grid-cols-[minmax(7rem,2fr)_minmax(0,3fr)] border-t border-line text-meta">
              {rows.map((r, i) => (
                <div key={`${r.label}-${i}`} className="col-span-2 grid grid-cols-subgrid border-b border-line py-1.5">
                  <dt className="pr-3 text-ink-2">{r.label}</dt>
                  <dd className="[overflow-wrap:anywhere]">
                    {r.value || <span className="text-ink-3">–</span>}
                    {r.confidence === "low" && (
                      <span className="ml-2 font-semibold whitespace-nowrap text-amber">? {t("prompt.unsure")}</span>
                    )}
                  </dd>
                </div>
              ))}
            </dl>
            <p className="mt-3 text-meta text-ink-2">
              {t("prompt.confirm_hint")}
              {screenshot && (
                <>
                  {" "}
                  <button type="button" onClick={() => setShot(true)} className="font-medium text-accent hover:underline">
                    {t("prompt.show_screenshot")}
                  </button>
                </>
              )}
            </p>
            <div className="mt-4 flex flex-wrap justify-end gap-2">
              <Button variant="quiet" onClick={() => send.mutate({ decision: "reject" })} disabled={send.isPending}>
                {t("prompt.reject")}
              </Button>
              <Button variant="secondary" onClick={() => send.mutate({ decision: "manual" })} disabled={send.isPending}>
                {t("prompt.manual")}
              </Button>
              <Button variant="primary" onClick={() => send.mutate({ decision: "submit" })} loading={send.isPending}>
                {t("prompt.submit")}
              </Button>
            </div>
            {screenshot && (
              <Dialog open={shot} onOpenChange={setShot}>
                <DialogContent title={t("prompt.screenshot")} description={prompt.payload.title} wide>
                  <img
                    src={artifactUrl(prompt.application_id, screenshot)}
                    alt={t("prompt.screenshot")}
                    className="w-full rounded-md border border-line"
                  />
                </DialogContent>
              </Dialog>
            )}
          </div>
        )}

        {prompt.kind === "handoff" && (
          <div className="mt-3">
            <p className="text-read">{prompt.payload.message}</p>
            <div className="mt-4 flex flex-wrap justify-end gap-2">
              <Button variant="quiet" onClick={() => send.mutate({ abort: true })} disabled={send.isPending}>
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
  },
);
