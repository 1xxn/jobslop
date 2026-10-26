import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Eye, Link2, Play, Rocket, ShieldCheck, Square, TerminalSquare } from "lucide-react";
import { type ReactNode, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import type { ApplyMode } from "@/lib/types";
import { cn, formatRelative } from "@/lib/utils";
import { Dialog, DialogContent } from "./ui/overlays";
import { Badge, Button, Field, Input } from "./ui/primitives";

/* ----------------------------------------------------------------- Bewerben */

export function ApplyDialog({
  open,
  onOpenChange,
  jobIds,
  queuedCount,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  jobIds?: number[];
  queuedCount?: number;
}) {
  const { t } = useI18n();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const settings = useQuery({ queryKey: ["settings"], queryFn: api.settings, enabled: open });
  const [mode, setMode] = useState<ApplyMode>("review");
  const [max, setMax] = useState(5);
  useEffect(() => {
    if (settings.data) setMode(settings.data.apply_mode);
  }, [settings.data]);
  const start = useMutation({
    mutationFn: () => api.apply({ job_ids: jobIds, mode, max: jobIds?.length ? undefined : max, force: !!jobIds?.length }),
    onSuccess: () => {
      toast.success(t("apply.started"));
      qc.invalidateQueries({ queryKey: ["status"] });
      onOpenChange(false);
      navigate("/activity");
    },
    onError: (e: Error) => toast.error(e.message),
  });
  const modes: { value: ApplyMode; icon: ReactNode; title: string; text: string }[] = [
    { value: "review", icon: <ShieldCheck />, title: t("mode.review"), text: t("mode.review_text") },
    { value: "auto", icon: <Rocket />, title: t("mode.auto"), text: t("mode.auto_text") },
    { value: "dry-run", icon: <Eye />, title: t("mode.dry"), text: t("mode.dry_text") },
  ];
  const count = jobIds?.length ?? queuedCount ?? 0;
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        title={jobIds?.length ? t("apply.title_selected", { n: count }) : t("apply.title_queue", { n: count })}
        description={t("apply.description")}
        footer={
          <>
            <Button variant="ghost" onClick={() => onOpenChange(false)}>
              {t("common.cancel")}
            </Button>
            <Button variant="primary" onClick={() => start.mutate()} loading={start.isPending} disabled={!count}>
              <Play />
              {t("apply.start")}
            </Button>
          </>
        }
      >
        <div role="radiogroup" className="space-y-2">
          {modes.map((m) => (
            <button
              key={m.value}
              type="button"
              role="radio"
              aria-checked={mode === m.value}
              onClick={() => setMode(m.value)}
              className={cn(
                "flex w-full items-start gap-3 rounded-lg border p-3.5 text-left transition-colors",
                mode === m.value ? "border-primary bg-primary-soft" : "border-border hover:bg-surface-2",
              )}
            >
              <span
                className={cn(
                  "mt-0.5 grid size-8 shrink-0 place-items-center rounded-md [&_svg]:size-4",
                  mode === m.value ? "bg-primary text-primary-fg" : "bg-surface-2 text-fg-muted",
                )}
              >
                {m.icon}
              </span>
              <span>
                <span className="flex items-center gap-2 text-[0.875rem] font-semibold">
                  {m.title}
                  {m.value === "review" && <Badge tone="primary">{t("common.recommended")}</Badge>}
                </span>
                <span className="mt-0.5 block text-footnote text-fg-muted">{m.text}</span>
              </span>
            </button>
          ))}
        </div>
        {!jobIds?.length && (
          <Field label={t("apply.max")} hint={t("apply.max_hint")} className="mt-4">
            <Input
              type="number"
              min={1}
              max={50}
              value={max}
              onChange={(e) => setMax(Number(e.target.value) || 1)}
              className="w-28"
            />
          </Field>
        )}
      </DialogContent>
    </Dialog>
  );
}

/* ----------------------------------------------------------------- Stelle per Link */

export function AddJobDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const { t } = useI18n();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [url, setUrl] = useState("");
  const add = useMutation({
    mutationFn: () => api.addJob(url),
    onSuccess: (r) => {
      toast.success(r.created ? t("addjob.added") : t("addjob.exists"));
      qc.invalidateQueries({ queryKey: ["jobs"] });
      onOpenChange(false);
      setUrl("");
      navigate(`/jobs?job=${r.id}`);
    },
    onError: (e: Error) => toast.error(e.message),
  });
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        title={t("addjob.title")}
        description={t("addjob.description")}
        footer={
          <>
            <Button variant="ghost" onClick={() => onOpenChange(false)}>
              {t("common.cancel")}
            </Button>
            <Button variant="primary" onClick={() => add.mutate()} loading={add.isPending} disabled={!/^https?:\/\//.test(url)}>
              <Link2 />
              {t("addjob.submit")}
            </Button>
          </>
        }
      >
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (/^https?:\/\//.test(url)) add.mutate();
          }}
        >
          <Field label={t("addjob.url")} hint={t("addjob.hint")}>
            <Input
              autoFocus
              type="url"
              placeholder="https://…"
              value={url}
              onChange={(e) => setUrl(e.target.value.trim())}
            />
          </Field>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/* ----------------------------------------------------------------- Laufender Bewerbungslauf */

export function RunnerPanel({ className }: { className?: string }) {
  const { t, lang } = useI18n();
  const qc = useQueryClient();
  const runner = useQuery({ queryKey: ["runner"], queryFn: () => api.runner(400), refetchInterval: 1500 });
  const stop = useMutation({
    mutationFn: api.stopRunner,
    onSuccess: () => {
      toast(t("runner.stopped"));
      qc.invalidateQueries({ queryKey: ["status"] });
    },
  });
  const pre = useRef<HTMLPreElement>(null);
  const log = runner.data?.log ?? "";
  useEffect(() => {
    const el = pre.current;
    if (el && el.scrollHeight - el.scrollTop - el.clientHeight < 80) el.scrollTop = el.scrollHeight;
  }, [log]);
  const r = runner.data;
  return (
    <div className={cn("overflow-hidden rounded-lg border border-border bg-surface shadow-sm", className)}>
      <div className="flex items-center justify-between gap-3 border-b border-border px-4 py-3">
        <div className="flex min-w-0 items-center gap-2.5">
          <span className={cn("size-2 rounded-full", r?.active ? "bg-success animate-pulse" : "bg-fg-subtle")} />
          <span className="truncate text-[0.875rem] font-semibold">
            {r?.active ? t("runner.active", { label: r.label }) : t("runner.idle")}
          </span>
          {r?.started_at && (
            <span className="truncate text-caption text-fg-subtle">
              {r.active ? formatRelative(r.started_at, lang) : formatRelative(r.finished_at ?? r.started_at, lang)}
            </span>
          )}
        </div>
        {r?.active && (
          <Button size="sm" variant="danger-soft" onClick={() => stop.mutate()} loading={stop.isPending}>
            <Square />
            {t("runner.stop")}
          </Button>
        )}
      </div>
      {log ? (
        <pre
          ref={pre}
          className="max-h-[420px] overflow-auto bg-[#0d0d12] px-4 py-3 font-mono text-[0.75rem] leading-relaxed text-[#d6d6e0]"
        >
          {log}
        </pre>
      ) : (
        <div className="flex items-center gap-2 px-4 py-6 text-footnote text-fg-muted">
          <TerminalSquare className="size-4" />
          {t("runner.empty")}
        </div>
      )}
    </div>
  );
}
