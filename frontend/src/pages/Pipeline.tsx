import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarClock, Ellipsis, ExternalLink, Handshake, MessagesSquare, Send, ThumbsDown } from "lucide-react";
import { type DragEvent, type ReactNode, useState } from "react";
import { useNavigate } from "react-router";
import { toast } from "sonner";
import { CompanyAvatar, StatusGlyph } from "@/components/domain";
import { Dialog, DialogContent, Menu, MenuContent, MenuItem, MenuLabel, MenuSeparator, MenuTrigger } from "@/components/ui/overlays";
import { Button, EmptyState, Field, Input, Skeleton, Textarea } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import type { MessageKey } from "@/lib/messages";
import type { ApplicationSummary } from "@/lib/types";
import { cn, formatDate, formatRelative, parseDate } from "@/lib/utils";

type Stage = "applied" | "interview" | "offer" | "rejected";
const STAGE_STATUS: Record<Stage, string> = { applied: "submitted", interview: "interview", offer: "offer", rejected: "rejected" };
const STAGES: { id: Stage; icon: ReactNode }[] = [
  { id: "applied", icon: <Send /> },
  { id: "interview", icon: <MessagesSquare /> },
  { id: "offer", icon: <Handshake /> },
  { id: "rejected", icon: <ThumbsDown /> },
];

/** Bewerbungen ab „gesendet“ als Board – zweite Ansicht der Seite Bewerbungen. */
export function PipelineBoard() {
  const { t, lang } = useI18n();
  const qc = useQueryClient();
  const pipeline = useQuery({ queryKey: ["pipeline"], queryFn: api.pipeline });
  const [dragOver, setDragOver] = useState<Stage | null>(null);
  const [editing, setEditing] = useState<ApplicationSummary | null>(null);
  const move = useMutation({
    mutationFn: ({ id, stage }: { id: number; stage: Stage }) => api.patchApplication(id, { status: STAGE_STATUS[stage] }),
    onSuccess: (_r, { stage }) => {
      toast.success(t("pipeline.moved", { stage: t(`pipeline.${stage}` as MessageKey) }));
      qc.invalidateQueries({ queryKey: ["pipeline"] });
      qc.invalidateQueries({ queryKey: ["stats"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const onDrop = (e: DragEvent, stage: Stage) => {
    e.preventDefault();
    setDragOver(null);
    const id = Number(e.dataTransfer.getData("text/plain"));
    if (id) move.mutate({ id, stage });
  };
  const due = pipeline.data?.follow_ups_due ?? [];
  const total = pipeline.data ? Object.values(pipeline.data.stages).reduce((n, list) => n + list.length, 0) : 0;

  return (
    <>
      {due.length > 0 && (
        <div className="mb-6">
          <h2 className="text-body font-semibold text-accent">{t("pipeline.due", { n: due.length })}</h2>
          <div className="mt-3 flex flex-wrap gap-2">
            {due.map((a) => (
              <button
                key={a.id}
                type="button"
                onClick={() => setEditing(a)}
                className="rounded-md border border-line-input px-2.5 py-1 text-meta hover:bg-sunken"
              >
                {a.company} · {formatRelative(a.follow_up_at, lang)}
              </button>
            ))}
          </div>
        </div>
      )}

      {pipeline.isLoading ? (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          {STAGES.map((s) => (
            <Skeleton key={s.id} className="h-80 rounded-lg" />
          ))}
        </div>
      ) : total === 0 ? (
        <EmptyState title={t("pipeline.empty")} description={t("pipeline.empty_hint")} />
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          {STAGES.map((stage) => {
            const cards = pipeline.data?.stages[stage.id] ?? [];
            return (
              <section
                key={stage.id}
                onDragOver={(e) => {
                  e.preventDefault();
                  setDragOver(stage.id);
                }}
                onDragLeave={() => setDragOver(null)}
                onDrop={(e) => onDrop(e, stage.id)}
                className={cn(
                  "flex min-h-64 flex-col rounded-lg p-1 transition-colors",
                  dragOver === stage.id && "bg-accent-soft",
                )}
                aria-label={t(`pipeline.${stage.id}` as MessageKey)}
              >
                <header className="mb-2 flex items-center gap-2 border-b border-line px-1 pt-1 pb-2">
                  <StatusGlyph status={STAGE_STATUS[stage.id]} />
                  <h2 className="text-body font-semibold">{t(`pipeline.${stage.id}` as MessageKey)}</h2>
                  <span className="tabular ml-auto text-small text-ink-3">{cards.length}</span>
                </header>
                <div className="flex flex-col gap-2">
                  {cards.map((a) => (
                    <PipelineCard key={a.id} app={a} onEdit={() => setEditing(a)} onMove={(s) => move.mutate({ id: a.id, stage: s })} />
                  ))}
                </div>
              </section>
            );
          })}
        </div>
      )}
      {editing && <EditDialog app={editing} onClose={() => setEditing(null)} />}
    </>
  );
}

function PipelineCard({
  app,
  onEdit,
  onMove,
}: {
  app: ApplicationSummary;
  onEdit: () => void;
  onMove: (s: Stage) => void;
}) {
  const { t, lang } = useI18n();
  const navigate = useNavigate();
  const due = parseDate(app.follow_up_at);
  const overdue = due && due.getTime() < Date.now();
  return (
    <article
      draggable
      onDragStart={(e) => e.dataTransfer.setData("text/plain", String(app.id))}
      className="group cursor-grab rounded-md border border-line bg-raised p-3 transition-colors hover:border-line-input active:cursor-grabbing"
    >
      <div className="flex items-start gap-2.5">
        <CompanyAvatar name={app.company} size={30} />
        <div className="min-w-0 flex-1">
          <button type="button" onClick={onEdit} className="block w-full text-left">
            <div className="truncate text-body font-semibold">{app.company}</div>
            <div className="line-clamp-2 text-meta text-ink-2">{app.title}</div>
          </button>
        </div>
        <Menu>
          <MenuTrigger asChild>
            <button
              type="button"
              className="grid size-7 place-items-center rounded-md text-ink-3 opacity-0 hover:bg-sunken group-hover:opacity-100 focus-visible:opacity-100"
              aria-label={t("common.more")}
            >
              <Ellipsis className="size-4" />
            </button>
          </MenuTrigger>
          <MenuContent>
            <MenuLabel>{t("pipeline.move_to")}</MenuLabel>
            {STAGES.map((s) => (
              <MenuItem key={s.id} icon={s.icon} onSelect={() => onMove(s.id)}>
                {t(`pipeline.${s.id}` as MessageKey)}
              </MenuItem>
            ))}
            <MenuSeparator />
            <MenuItem icon={<CalendarClock />} onSelect={onEdit}>
              {t("pipeline.edit")}
            </MenuItem>
            <MenuItem icon={<ExternalLink />} onSelect={() => navigate(`/applications/${app.id}`)}>
              {t("pipeline.open")}
            </MenuItem>
          </MenuContent>
        </Menu>
      </div>
      {app.notes && <p className="mt-2 line-clamp-2 text-small text-ink-2">{app.notes}</p>}
      <div className="mt-2.5 flex items-center justify-between text-small text-ink-3">
        <span>{formatDate(app.submitted_at ?? app.started_at, lang)}</span>
        {due && (
          <span className={cn("inline-flex items-center gap-1", overdue ? "font-medium text-accent" : "")}>
            <CalendarClock className="size-3" />
            {formatRelative(app.follow_up_at, lang)}
          </span>
        )}
      </div>
    </article>
  );
}

function EditDialog({ app, onClose }: { app: ApplicationSummary; onClose: () => void }) {
  const { t } = useI18n();
  const qc = useQueryClient();
  const [notes, setNotes] = useState(app.notes);
  const [date, setDate] = useState(app.follow_up_at ? app.follow_up_at.slice(0, 10) : "");
  const save = useMutation({
    mutationFn: () =>
      api.patchApplication(app.id, {
        notes,
        ...(date ? { follow_up_at: `${date}T09:00:00` } : { clear_follow_up: true }),
      }),
    onSuccess: () => {
      toast.success(t("common.saved"));
      qc.invalidateQueries({ queryKey: ["pipeline"] });
      onClose();
    },
  });
  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent
        title={app.company}
        description={app.title}
        footer={
          <>
            <Button variant="quiet" onClick={onClose}>
              {t("common.cancel")}
            </Button>
            <Button variant="primary" onClick={() => save.mutate()} loading={save.isPending}>
              {t("common.save")}
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <Field label={t("pipeline.followup")} hint={t("pipeline.followup_hint")}>
            <Input type="date" value={date} onChange={(e) => setDate(e.target.value)} className="w-48" />
          </Field>
          <Field label={t("job.notes")}>
            <Textarea value={notes} onChange={(e) => setNotes(e.target.value)} placeholder={t("pipeline.notes_placeholder")} />
          </Field>
        </div>
      </DialogContent>
    </Dialog>
  );
}
