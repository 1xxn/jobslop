import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BellRing, CalendarClock, Ellipsis, ExternalLink, Handshake, MessagesSquare, Send, ThumbsDown } from "lucide-react";
import { type DragEvent, type ReactNode, useState } from "react";
import { useNavigate } from "react-router";
import { toast } from "sonner";
import { CompanyAvatar, PageHeader } from "@/components/domain";
import { Dialog, DialogContent, Menu, MenuContent, MenuItem, MenuLabel, MenuSeparator, MenuTrigger } from "@/components/ui/overlays";
import { Button, EmptyState, Field, Input, Skeleton, Textarea } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import type { MessageKey } from "@/lib/messages";
import type { ApplicationSummary } from "@/lib/types";
import { cn, formatDate, formatRelative, parseDate } from "@/lib/utils";

type Stage = "applied" | "interview" | "offer" | "rejected";
const STAGE_STATUS: Record<Stage, string> = { applied: "submitted", interview: "interview", offer: "offer", rejected: "rejected" };
const STAGES: { id: Stage; icon: ReactNode; tone: string }[] = [
  { id: "applied", icon: <Send />, tone: "text-info" },
  { id: "interview", icon: <MessagesSquare />, tone: "text-primary" },
  { id: "offer", icon: <Handshake />, tone: "text-success" },
  { id: "rejected", icon: <ThumbsDown />, tone: "text-fg-subtle" },
];

export function PipelinePage() {
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
      <PageHeader title={t("pipeline.title")} description={t("pipeline.description")} />

      {due.length > 0 && (
        <div className="mb-6 rounded-lg border border-warning/40 bg-warning-soft p-4">
          <h2 className="flex items-center gap-2 text-[0.875rem] font-semibold">
            <BellRing className="size-4 text-warning" />
            {t("pipeline.due", { n: due.length })}
          </h2>
          <div className="mt-3 flex flex-wrap gap-2">
            {due.map((a) => (
              <button
                key={a.id}
                type="button"
                onClick={() => setEditing(a)}
                className="rounded-full border border-warning/40 bg-surface px-3 py-1 text-footnote hover:bg-surface-2"
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
            <Skeleton key={s.id} className="h-80 rounded-xl" />
          ))}
        </div>
      ) : total === 0 ? (
        <EmptyState icon={<Send />} title={t("pipeline.empty")} description={t("pipeline.empty_hint")} />
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
                  "flex min-h-64 flex-col rounded-xl bg-surface-2/60 p-2 transition-colors",
                  dragOver === stage.id && "bg-primary-soft ring-2 ring-primary/40",
                )}
                aria-label={t(`pipeline.${stage.id}` as MessageKey)}
              >
                <header className="flex items-center gap-2 px-2 pt-1.5 pb-3">
                  <span className={cn("[&_svg]:size-4", stage.tone)}>{stage.icon}</span>
                  <h2 className="text-[0.875rem] font-semibold">{t(`pipeline.${stage.id}` as MessageKey)}</h2>
                  <span className="tabular ml-auto rounded-full bg-surface px-2 text-caption text-fg-muted">{cards.length}</span>
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
      className="group cursor-grab rounded-lg border border-border bg-surface p-3 shadow-sm transition-shadow hover:shadow-md active:cursor-grabbing"
    >
      <div className="flex items-start gap-2.5">
        <CompanyAvatar name={app.company} size={30} />
        <div className="min-w-0 flex-1">
          <button type="button" onClick={onEdit} className="block w-full text-left">
            <div className="truncate text-[0.875rem] font-semibold">{app.company}</div>
            <div className="line-clamp-2 text-footnote text-fg-muted">{app.title}</div>
          </button>
        </div>
        <Menu>
          <MenuTrigger asChild>
            <button
              type="button"
              className="grid size-7 place-items-center rounded-md text-fg-subtle opacity-0 hover:bg-surface-2 group-hover:opacity-100 focus-visible:opacity-100"
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
      {app.notes && <p className="mt-2 line-clamp-2 text-caption text-fg-muted">{app.notes}</p>}
      <div className="mt-2.5 flex items-center justify-between text-caption text-fg-subtle">
        <span>{formatDate(app.submitted_at ?? app.started_at, lang)}</span>
        {due && (
          <span className={cn("inline-flex items-center gap-1", overdue ? "font-medium text-warning" : "")}>
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
            <Button variant="ghost" onClick={onClose}>
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
