import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useMemo, useState } from "react";
import { Link } from "react-router";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import type { Status } from "@/lib/types";
import { cn, formatRelative, formatWhen } from "@/lib/utils";
import { RunnerPanel } from "../actions";
import { StatusGlyph } from "../domain";
import { Sheet } from "../ui/overlays";
import { Button, Section } from "../ui/primitives";
import { RunDrawerContext, useRunDrawer } from "./runContext";

/* Der laufende Bewerbungslauf, die Suche und der Autopilot – keine eigene Seite, sondern eine Seitenleiste, die sich
 * von überall öffnen lässt (Statuszeile in der Navigation, mobil oben rechts, nach „Bewerben“). */

export function RunDrawerProvider({ status, children }: { status: Status | undefined; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const value = useMemo(() => ({ open: () => setOpen(true) }), []);
  return (
    <RunDrawerContext.Provider value={value}>
      {children}
      <RunDrawer open={open} onOpenChange={setOpen} status={status} />
    </RunDrawerContext.Provider>
  );
}

/** Was gerade läuft – eine Zeile für die Statusanzeige (Navigation, Handy-Kopfzeile). */
export function runSummary(status: Status | undefined, t: ReturnType<typeof useI18n>["t"], lang: string) {
  const busy = !!(status?.runner.active || status?.crawl.running || status?.autopilot.running);
  const now = status?.runner.active
    ? t("run.applying")
    : status?.crawl.running
      ? t("run.searching")
      : status?.autopilot.running
        ? t("run.autopilot_running")
        : null;
  const detail = status?.runner.active ? status.runner.label : null;
  const autopilot = status?.autopilot.enabled
    ? t("run.autopilot_at", { when: formatWhen(status.autopilot.next_run, lang) })
    : t("run.autopilot_off");
  return { busy, now, detail, autopilot };
}

/** Statuszeile unten in der Navigation: öffnet die Lauf-Seitenleiste. */
export function RunStatusButton({ status, className }: { status: Status | undefined; className?: string }) {
  const { t, lang } = useI18n();
  const { open } = useRunDrawer();
  const s = runSummary(status, t, lang);
  return (
    <button
      type="button"
      onClick={open}
      aria-label={t("run.open")}
      className={cn(
        "grid w-full gap-1.5 rounded-md px-2.5 py-2 text-left text-small text-ink-2 transition-colors hover:bg-sunken",
        className,
      )}
    >
      {s.now && (
        <span className="flex min-w-0 items-start gap-2">
          <StatusGlyph status="running" className="mt-0.5 animate-pulse-slow" />
          <span className="min-w-0">
            <span className="block font-medium text-ink">{s.now}</span>
            {s.detail && <span className="block truncate text-ink-3">{s.detail}</span>}
          </span>
        </span>
      )}
      <span className="flex items-center gap-2">
        <StatusGlyph status={status?.autopilot.enabled ? "queued" : "skipped"} />
        <span className="truncate">{s.autopilot}</span>
      </span>
    </button>
  );
}

function RunDrawer({
  open,
  onOpenChange,
  status,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  status: Status | undefined;
}) {
  const { t, lang } = useI18n();
  const qc = useQueryClient();
  const crawls = useQuery({ queryKey: ["crawls"], queryFn: api.crawls, enabled: open });
  const crawl = useMutation({
    mutationFn: api.crawl,
    onSuccess: (r) => {
      toast(r.started ? t("crawl.started") : t("crawl.running"));
      qc.invalidateQueries({ queryKey: ["status"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });
  const autopilot = useMutation({
    mutationFn: api.autopilotRun,
    onSuccess: () => toast(t("autopilot.started")),
    onError: (e: Error) => toast.error(e.message),
  });
  const last = crawls.data?.[0];
  const s = runSummary(status, t, lang);

  return (
    <Sheet open={open} onOpenChange={onOpenChange} title={t("run.title")} className="max-w-[460px]">
      <div className="grid gap-8 px-5 py-5">
        <RunnerPanel />

        <Section title={t("run.search")}>
          <div className="flex flex-wrap items-center justify-between gap-3 pt-3">
            <p className="text-meta text-ink-2">
              {status?.crawl.running
                ? t("run.searching")
                : last
                  ? t("run.last_search", { when: formatRelative(last.started_at, lang), n: last.stats.new ?? 0 })
                  : t("run.no_search")}
            </p>
            <Button size="sm" onClick={() => crawl.mutate()} loading={!!status?.crawl.running}>
              {t("crawl.start")}
            </Button>
          </div>
        </Section>

        <Section title={t("autopilot.title")}>
          <div className="flex flex-wrap items-center justify-between gap-3 pt-3">
            <p className="text-meta text-ink-2">{s.autopilot}</p>
            <Button
              size="sm"
              onClick={() => autopilot.mutate()}
              loading={!!status?.autopilot.running}
              disabled={!!status?.demo}
            >
              {t("autopilot.run_now")}
            </Button>
          </div>
        </Section>

        <Link
          to="/settings/log"
          onClick={() => onOpenChange(false)}
          className="justify-self-start text-meta font-medium text-accent hover:underline"
        >
          {t("run.log")}
        </Link>
      </div>
    </Sheet>
  );
}
