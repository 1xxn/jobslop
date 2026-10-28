import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Ellipsis } from "lucide-react";
import { type DragEvent, type KeyboardEvent, useState } from "react";
import { useNavigate } from "react-router";
import { toast } from "sonner";
import { StatusGlyph } from "@/components/domain";
import { Menu, MenuContent, MenuItem, MenuLabel, MenuSeparator, MenuTrigger } from "@/components/ui/overlays";
import { EmptyState, Kbd, Skeleton } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { canFollowUp, followUpDue } from "@/lib/applications";
import { useI18n } from "@/lib/i18n";
import type { MessageKey } from "@/lib/messages";
import type { ApplicationSummary } from "@/lib/types";
import { cn, formatDate, formatRelative } from "@/lib/utils";

type Stage = "applied" | "interview" | "offer" | "rejected";
const STAGES: Stage[] = ["applied", "interview", "offer", "rejected"];
const STAGE_STATUS: Record<Stage, string> = {
  applied: "submitted",
  interview: "interview",
  offer: "offer",
  rejected: "rejected",
};

/**
 * Bewerbungen ab „gesendet“ als Board – zweite Ansicht der Seite Bewerbungen. Verschieben per Ziehen, per Menü oder
 * mit Alt+Pfeil auf einer fokussierten Karte; Enter öffnet die Bewerbung.
 */
export function PipelineBoard() {
  const { t } = useI18n();
  const qc = useQueryClient();
  const pipeline = useQuery({ queryKey: ["pipeline"], queryFn: api.pipeline });
  const [dragOver, setDragOver] = useState<Stage | null>(null);
  const move = useMutation({
    mutationFn: ({ app, stage }: { app: ApplicationSummary; stage: Stage }) =>
      api.patchApplication(app.id, { status: STAGE_STATUS[stage] }),
    onSuccess: (_r, { app, stage }) => {
      // Rückgängig: genau der vorige Stand (auch „selbst gesendet“) und der Termin, den Angebot/Absage löschen
      const before = { status: app.status, ...(app.follow_up_at ? { follow_up_at: app.follow_up_at } : {}) };
      toast(t("pipeline.moved", { stage: t(`pipeline.${stage}` as MessageKey) }), {
        action: { label: t("common.undo"), onClick: () => api.patchApplication(app.id, before).then(refresh) },
      });
      const id = app.id;
      refresh();
      // Fokus folgt der Karte in die neue Spalte
      requestAnimationFrame(() => document.getElementById(`card-${id}`)?.focus());
    },
    onError: (e: Error) => toast.error(e.message),
  });
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["pipeline"] });
    qc.invalidateQueries({ queryKey: ["applications"] });
    qc.invalidateQueries({ queryKey: ["stats"] });
  };
  const moveTo = (id: number, stage: Stage) => {
    const from = STAGES.find((s) => pipeline.data?.stages[s].some((a) => a.id === id));
    const app = from && pipeline.data?.stages[from].find((a) => a.id === id);
    if (app && from !== stage) move.mutate({ app, stage });
  };
  const onDrop = (e: DragEvent, stage: Stage) => {
    e.preventDefault();
    setDragOver(null);
    const id = Number(e.dataTransfer.getData("text/plain"));
    if (id) moveTo(id, stage);
  };

  if (pipeline.isLoading) {
    return (
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {STAGES.map((s) => (
          <Skeleton key={s} className="h-64 rounded-lg" />
        ))}
      </div>
    );
  }
  const total = pipeline.data ? STAGES.reduce((n, s) => n + pipeline.data.stages[s].length, 0) : 0;
  if (!total) return <EmptyState title={t("pipeline.empty")} description={t("pipeline.empty_hint")} />;

  return (
    <>
      <p className="mb-3 text-meta text-ink-3">
        {t("pipeline.keyboard_hint")} <Kbd>Alt</Kbd> + <Kbd>←</Kbd> <Kbd>→</Kbd>
      </p>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {STAGES.map((stage, i) => {
          const cards = pipeline.data?.stages[stage] ?? [];
          const id = `stage-${stage}`;
          return (
            <section
              key={stage}
              aria-labelledby={id}
              onDragOver={(e) => {
                e.preventDefault();
                setDragOver(stage);
              }}
              onDragLeave={() => setDragOver(null)}
              onDrop={(e) => onDrop(e, stage)}
              className={cn("flex min-h-48 flex-col rounded-lg p-1 transition-colors", dragOver === stage && "bg-accent-soft")}
            >
              <header className="mb-2 flex items-center gap-2 border-b border-line px-1 pt-1 pb-2">
                <StatusGlyph status={STAGE_STATUS[stage]} />
                <h2 id={id} className="text-body font-semibold">
                  {t(`pipeline.${stage}` as MessageKey)}
                </h2>
                <span className="tabular ml-auto text-small text-ink-3">{cards.length}</span>
              </header>
              <ul className="flex flex-col gap-2">
                {cards.map((a) => (
                  <li key={a.id}>
                    <BoardCard
                      app={a}
                      stage={stage}
                      onMove={(s) => moveTo(a.id, s)}
                      prev={STAGES[i - 1]}
                      next={STAGES[i + 1]}
                    />
                  </li>
                ))}
              </ul>
            </section>
          );
        })}
      </div>
    </>
  );
}

function BoardCard({
  app,
  stage,
  onMove,
  prev,
  next,
}: {
  app: ApplicationSummary;
  stage: Stage;
  onMove: (s: Stage) => void;
  prev?: Stage;
  next?: Stage;
}) {
  const { t, lang } = useI18n();
  const navigate = useNavigate();
  const due = followUpDue(app);
  const open = () => navigate(`/applications/${app.id}`);
  const onKey = (e: KeyboardEvent) => {
    if (e.target !== e.currentTarget) return;
    if (e.key === "Enter") open();
    else if (e.altKey && e.key === "ArrowLeft" && prev) {
      e.preventDefault();
      onMove(prev);
    } else if (e.altKey && e.key === "ArrowRight" && next) {
      e.preventDefault();
      onMove(next);
    }
  };
  return (
    <article
      id={`card-${app.id}`}
      tabIndex={0}
      draggable
      aria-label={`${app.company}, ${app.title}`}
      onDragStart={(e) => e.dataTransfer.setData("text/plain", String(app.id))}
      onClick={open}
      onKeyDown={onKey}
      className="group cursor-pointer rounded-md border border-line bg-raised p-3 transition-colors hover:border-line-input active:cursor-grabbing"
    >
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <div className="truncate font-semibold">{app.company}</div>
          <div className="line-clamp-2 text-meta text-ink-2">{app.title}</div>
        </div>
        <Menu>
          <MenuTrigger asChild>
            <button
              type="button"
              onClick={(e) => e.stopPropagation()}
              className="grid size-7 place-items-center rounded-md text-ink-3 opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 hover:bg-sunken focus-visible:opacity-100"
              aria-label={t("common.more")}
            >
              <Ellipsis className="size-4" />
            </button>
          </MenuTrigger>
          <MenuContent onClick={(e) => e.stopPropagation()}>
            <MenuLabel>{t("pipeline.move_to")}</MenuLabel>
            {STAGES.filter((s) => s !== stage).map((s) => (
              <MenuItem key={s} onSelect={() => onMove(s)}>
                {t(`pipeline.${s}` as MessageKey)}
              </MenuItem>
            ))}
            <MenuSeparator />
            <MenuItem onSelect={open}>{t("pipeline.open")}</MenuItem>
          </MenuContent>
        </Menu>
      </div>
      {app.notes && <p className="mt-2 line-clamp-2 text-small text-ink-2">{app.notes}</p>}
      <div className="mt-2 flex items-center justify-between gap-2 text-small text-ink-3">
        <span className="tabular">{formatDate(app.submitted_at ?? app.started_at, lang)}</span>
        {app.follow_up_at && canFollowUp(app.status) && (
          <span className={cn(due && "font-medium text-accent")}>
            {t(due ? "apps.followup_due" : "apps.followup_at", { when: formatRelative(app.follow_up_at, lang) })}
          </span>
        )}
      </div>
    </article>
  );
}
