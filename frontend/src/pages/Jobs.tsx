import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Search } from "lucide-react";
import { type KeyboardEvent, type MouseEvent, type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router";
import { toast } from "sonner";
import { AddJobDialog, ApplyDialog } from "@/components/actions";
import { PageHeader, Score, StatusLabel } from "@/components/domain";
import { type Decisions, DecisionButtons, JobDetail } from "@/components/JobDetail";
import { QueueBar } from "@/components/QueueBar";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/controls";
import {
  Menu,
  MenuCheckboxItem,
  MenuContent,
  MenuLabel,
  MenuRadioGroup,
  MenuRadioItem,
  MenuSeparator,
  MenuTrigger,
  Sheet,
} from "@/components/ui/overlays";
import { Button, EmptyState, Input, Kbd, Skeleton } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { useHotkeys } from "@/lib/hotkeys";
import { useDebounced, useMediaQuery, useRoleNames, useStatus } from "@/lib/hooks";
import { useI18n } from "@/lib/i18n";
import type { MessageKey } from "@/lib/messages";
import type { JobDetail as JobFull, JobSummary, JobView } from "@/lib/types";
import { cn, formatRelative, formatWhen } from "@/lib/utils";

const VIEWS: { id: JobView; label: MessageKey }[] = [
  { id: "triage", label: "jobs.view_triage" },
  { id: "starred", label: "jobs.view_starred" },
  { id: "queued", label: "jobs.view_queued" },
  { id: "all", label: "jobs.view_all" },
  { id: "dismissed", label: "jobs.view_dismissed" },
];
const SPLIT = "(min-width: 1180px)";

type Action = "queue" | "unqueue" | "star" | "unstar" | "exclude";
const INVERSE: Partial<Record<Action, Action>> = { queue: "unqueue", unqueue: "queue", star: "unstar", unstar: "star" };

/**
 * Stellen sichten wie Post: Liste links, Stelle rechts (schmal: Seitenleiste), drei Entscheidungen mit A/S/X,
 * danach springt die Auswahl zur nächsten Stelle. Rückgängig statt Rückfrage (Z).
 */
export function JobsPage() {
  const { t, tp, lang } = useI18n();
  const qc = useQueryClient();
  const roles = useRoleNames();
  const { data: status } = useStatus();
  const split = useMediaQuery(SPLIT);
  const [params, setParams] = useSearchParams();
  const view = (VIEWS.some((v) => v.id === params.get("view")) ? params.get("view") : "triage") as JobView;
  const activeId = params.get("job") ? Number(params.get("job")) : null;

  const [q, setQ] = useState("");
  const [category, setCategory] = useState<string[]>([]);
  const [where, setWhere] = useState("");
  const [stretch, setStretch] = useState(false);
  const [sort, setSort] = useState("score");
  const [limit, setLimit] = useState(60);
  const [selection, setSelection] = useState<Set<number>>(new Set());
  const [anchor, setAnchor] = useState<number | null>(null);
  const [addOpen, setAddOpen] = useState(false);
  const [applyIds, setApplyIds] = useState<number[] | null>(null);
  const query = useDebounced(q);
  const searchRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLUListElement>(null);

  const jobs = useQuery({
    queryKey: ["jobs", { query, view, category, where, stretch, sort, limit }],
    queryFn: () =>
      api.jobs({
        q: query,
        view,
        category: category.join(","),
        where,
        level: stretch ? "" : "noS",
        status: view === "all" || view === "dismissed" ? "all" : "open",
        sort,
        limit,
      }),
    placeholderData: keepPreviousData,
  });
  const crawls = useQuery({ queryKey: ["crawls"], queryFn: api.crawls, staleTime: 60_000 });
  const items = useMemo(() => jobs.data?.items ?? [], [jobs.data]);
  const activeIndex = items.findIndex((j) => j.id === activeId);

  const setParam = (changes: Record<string, string | null>) => {
    const next = new URLSearchParams(params);
    for (const [k, v] of Object.entries(changes)) {
      if (v === null) next.delete(k);
      else next.set(k, v);
    }
    setParams(next, { replace: true });
  };
  const setActive = (id: number | null) => setParam({ job: id === null ? null : String(id) });
  const setView = (v: JobView) => {
    setSelection(new Set());
    setParam({ view: v === "triage" ? null : v, job: null });
  };

  // Verschwindet die offene Stelle aus der Liste (entschieden), rückt die nächste an ihren Platz.
  const lastIndex = useRef(0);
  const wasListed = useRef(false);
  useEffect(() => {
    if (activeIndex >= 0) {
      lastIndex.current = activeIndex;
      wasListed.current = true;
    }
  }, [activeIndex]);
  useEffect(() => {
    if (!jobs.data || jobs.isFetching) return;
    if (activeId !== null && activeIndex < 0 && wasListed.current) {
      wasListed.current = false;
      setActive(items[Math.min(lastIndex.current, items.length - 1)]?.id ?? null);
    } else if (activeId === null && split && items[0]) {
      setActive(items[0].id);
    }
  }, [jobs.data, jobs.isFetching, activeId, activeIndex, split]);

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["jobs"] });
    qc.invalidateQueries({ queryKey: ["job"] });
    qc.invalidateQueries({ queryKey: ["status"] });
  };

  /* ------------------------------------------------------------- Entscheiden, mit Rückgängig */

  const lastAction = useRef<{ action: Action; ids: number[]; exclusions: number[] } | null>(null);
  const undo = async () => {
    const last = lastAction.current;
    if (!last) return;
    lastAction.current = null;
    if (last.action === "exclude") await Promise.all(last.exclusions.map((id) => api.deleteExclusion(id)));
    else if (INVERSE[last.action]) await api.bulk(last.ids, INVERSE[last.action] as Action);
    toast(t("decide.undone"));
    refresh();
  };
  const act = useMutation({
    mutationFn: ({ action, ids }: { action: Action; ids: number[]; title?: string }) => api.bulk(ids, action),
    onSuccess: (r, { action, ids, title }) => {
      refresh();
      if (r.skipped.length) {
        toast(tp("bulk.skipped", r.skipped.length), { description: r.skipped.slice(0, 3).join("\n") });
        if (!r.changed.length) return;
      }
      lastAction.current = { action, ids: r.changed.length ? r.changed : ids, exclusions: r.exclusions ?? [] };
      const n = r.changed.length;
      const message =
        n === 1 && title ? t(`decide.done_${action}`, { title }) : tp(`bulk.${action}` as MessageKey, n);
      toast(message, { action: { label: t("common.undo"), onClick: undo } });
      setSelection(new Set());
    },
    onError: (e: Error) => toast.error(e.message),
  });

  /** Ziel einer Entscheidung: die Mehrfachauswahl, sonst die offene Stelle. */
  const targets = (): JobSummary[] => {
    if (selection.size > 1) return items.filter((j) => selection.has(j.id));
    const active = items.find((j) => j.id === activeId) ?? (activeId ? qc.getQueryData<JobFull>(["job", activeId]) : undefined);
    return active ? [active] : [];
  };
  const decide = async (kind: "queue" | "star" | "dismiss") => {
    const list = targets();
    if (!list.length) return;
    const ids = list.map((j) => j.id);
    const title = list.length === 1 ? `${list[0].company} · ${list[0].title}` : undefined;
    if (kind === "dismiss" && list.length === 1 && list[0].excluded) return restore(list[0]);
    // Umschalter: Ist alles schon vorgemerkt bzw. gemerkt, nimmt derselbe Knopf es zurück
    const action: Action =
      kind === "queue"
        ? list.every((j) => j.queued)
          ? "unqueue"
          : "queue"
        : kind === "star"
          ? list.every((j) => j.starred)
            ? "unstar"
            : "star"
          : "exclude";
    act.mutate({ action, ids, title });
  };
  const restore = async (job: JobSummary) => {
    const ex = (await api.exclusions()).find((e) => e.kind === "job" && e.value === String(job.id));
    if (!ex) return;
    await api.deleteExclusion(ex.id);
    toast(t("decide.restored", { title: job.title }));
    refresh();
  };
  const decisions: Decisions = {
    queue: () => decide("queue"),
    star: () => decide("star"),
    dismiss: () => decide("dismiss"),
    busy: act.isPending,
  };

  /* ------------------------------------------------------------- Auswahl und Tastatur */

  const focusRow = (id: number) =>
    requestAnimationFrame(() => document.getElementById(`job-row-${id}`)?.focus({ preventScroll: false }));
  const move = (delta: number, extend = false) => {
    if (!items.length) return;
    const from = activeIndex < 0 ? (delta > 0 ? -1 : items.length) : activeIndex;
    const next = items[Math.max(0, Math.min(items.length - 1, from + delta))];
    if (!next) return;
    if (extend && activeId !== null) setSelection(new Set([...selection, activeId, next.id]));
    else setSelection(new Set());
    setActive(next.id);
    document.getElementById(`job-row-${next.id}`)?.scrollIntoView({ block: "nearest" });
    return next.id;
  };
  const onRowClick = (e: MouseEvent, id: number) => {
    if (e.shiftKey && anchor !== null) {
      const [a, b] = [items.findIndex((j) => j.id === anchor), items.findIndex((j) => j.id === id)].sort((x, y) => x - y);
      setSelection(new Set(items.slice(a, b + 1).map((j) => j.id)));
    } else if (e.ctrlKey || e.metaKey) {
      const next = new Set(selection.size ? selection : activeId !== null ? [activeId] : []);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      setSelection(next);
      setAnchor(id);
    } else {
      setSelection(new Set());
      setAnchor(id);
    }
    setActive(id);
  };
  /** Zeile mit dem Tastaturfokus (schmal bewegen die Pfeile nur den Fokus, Enter öffnet). */
  const focusedId = () => {
    const id = (document.activeElement as HTMLElement | null)?.id ?? "";
    return id.startsWith("job-row-") ? Number(id.slice(8)) : activeId;
  };
  const onListKey = (e: KeyboardEvent<HTMLUListElement>) => {
    const delta = ({ ArrowDown: 1, ArrowUp: -1, Home: -Infinity, End: Infinity } as Record<string, number>)[e.key];
    if (delta !== undefined) {
      e.preventDefault();
      if (split) {
        const id = move(delta, e.shiftKey);
        if (typeof id === "number") focusRow(id);
      } else {
        const rows = [...(listRef.current?.querySelectorAll<HTMLElement>("[role=option]") ?? [])];
        const from = rows.indexOf(document.activeElement as HTMLElement);
        rows[Math.max(0, Math.min(rows.length - 1, (from < 0 ? 0 : from) + delta))]?.focus();
      }
    } else if (e.key === " ") {
      const id = focusedId();
      if (id === null) return;
      e.preventDefault();
      const next = new Set(selection.size ? selection : activeId !== null ? [activeId] : []);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      setSelection(next);
    } else if (e.key === "Enter" && !split) {
      const id = focusedId();
      if (id !== null) {
        e.preventDefault();
        setActive(id);
      }
    }
  };
  useHotkeys({
    j: () => move(1),
    k: () => move(-1),
    a: () => decide("queue"),
    s: () => decide("star"),
    x: () => decide("dismiss"),
    z: () => void undo(),
    o: () => {
      const job = items.find((j) => j.id === activeId);
      if (job) window.open(job.url, "_blank", "noopener");
    },
    "/": () => searchRef.current?.focus(),
    escape: () => setSelection(new Set()),
  });

  /* ------------------------------------------------------------- Kopf: Suche, Link, beste 10 */

  const crawl = useMutation({
    mutationFn: api.crawl,
    onSuccess: (r) => {
      toast(r.started ? t("crawl.started") : t("crawl.running"));
      qc.invalidateQueries({ queryKey: ["status"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });
  const queueTop = useMutation({
    mutationFn: () => api.queueTop(10),
    onSuccess: (r) => {
      toast.success(tp("queue.added", r.changed.length));
      refresh();
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const counts = jobs.data?.counts;
  const facets = jobs.data?.facets.category ?? {};
  const roleNames = [...roles.filter((r) => facets[r] || category.includes(r)), ...(facets.Other ? ["Other"] : [])];
  const lastCrawl = crawls.data?.[0]?.started_at;
  const filtered = !!(query || category.length || where || stretch);
  const multi = selection.size > 1;

  return (
    <>
      <PageHeader
        title={t("jobs.title")}
        actions={
          <>
            {lastCrawl && (
              <span className="mr-1 hidden text-meta text-ink-3 sm:inline">
                {t("jobs.last_search", { when: formatRelative(lastCrawl, lang) })}
              </span>
            )}
            <Button variant="quiet" size="sm" onClick={() => crawl.mutate()} loading={!!status?.crawl.running}>
              {status?.crawl.running ? t("crawl.running_short") : t("jobs.search_now")}
            </Button>
            <Button variant="quiet" size="sm" onClick={() => setAddOpen(true)}>
              {t("addjob.short")}
            </Button>
            <Button variant="quiet" size="sm" onClick={() => queueTop.mutate()} loading={queueTop.isPending}>
              {t("queue.top10")}
            </Button>
          </>
        }
      />

      <Tabs value={view} onValueChange={(v) => setView(v as JobView)}>
        <TabsList>
          {VIEWS.map((v) => (
            <TabsTrigger key={v.id} value={v.id} count={counts?.[v.id]}>
              {t(v.label)}
            </TabsTrigger>
          ))}
        </TabsList>

        <div className="flex flex-wrap items-center gap-1 py-3">
          <div className="relative min-w-48 flex-1">
            <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-ink-3" aria-hidden />
            <Input
              ref={searchRef}
              value={q}
              onChange={(e) => setQ(e.target.value)}
              onKeyDown={(e) => e.key === "Escape" && (e.currentTarget.blur(), setQ(""))}
              placeholder={t("jobs.search")}
              aria-label={t("jobs.search")}
              className="pr-8 pl-8"
            />
            <Kbd className="pointer-events-none absolute top-1/2 right-2 -translate-y-1/2">/</Kbd>
          </div>
          <Picker label={t("jobs.role")} value={category.length ? category.join(", ") : t("common.all")}>
            <MenuLabel>{t("jobs.role")}</MenuLabel>
            {roleNames.map((r) => (
              <MenuCheckboxItem
                key={r}
                checked={category.includes(r)}
                onCheckedChange={(on) => setCategory(on ? [...category, r] : category.filter((c) => c !== r))}
                onSelect={(e) => e.preventDefault()}
              >
                <span className="flex-1">{r}</span>
                <span className="tabular text-small text-ink-3">{facets[r] ?? 0}</span>
              </MenuCheckboxItem>
            ))}
            <MenuSeparator />
            <MenuCheckboxItem checked={stretch} onCheckedChange={setStretch} onSelect={(e) => e.preventDefault()}>
              {t("jobs.show_stretch")}
            </MenuCheckboxItem>
          </Picker>
          <Picker label={t("jobs.place")} value={t(where === "R" ? "where.remote" : where === "B" ? "where.onsite" : "common.all")}>
            <MenuRadioGroup value={where || "any"} onValueChange={(v) => setWhere(v === "any" ? "" : v)}>
              <MenuRadioItem value="any">{t("common.all")}</MenuRadioItem>
              <MenuRadioItem value="B">{t("where.onsite")}</MenuRadioItem>
              <MenuRadioItem value="R">{t("where.remote")}</MenuRadioItem>
            </MenuRadioGroup>
          </Picker>
          <Picker label={t("jobs.sort")} value={t(`jobs.sort_${sort}` as MessageKey)}>
            <MenuRadioGroup value={sort} onValueChange={setSort}>
              <MenuRadioItem value="score">{t("jobs.sort_score")}</MenuRadioItem>
              <MenuRadioItem value="new">{t("jobs.sort_new")}</MenuRadioItem>
              <MenuRadioItem value="company">{t("jobs.sort_company")}</MenuRadioItem>
            </MenuRadioGroup>
          </Picker>
        </div>

        <TabsContent value={view} tabIndex={-1} className="focus:outline-none">
          <div className={cn("grid min-[1180px]:grid-cols-[minmax(0,0.85fr)_minmax(0,1.15fr)]", split && "border-t border-line")}>
            <div className={cn("min-w-0", split && "border-r border-line pr-4")}>
              {jobs.isLoading && <ListSkeleton />}
              {jobs.isError && (
                <EmptyState
                  title={t("jobs.load_error")}
                  description={t("jobs.load_error_hint")}
                  action={<Button size="sm" onClick={() => jobs.refetch()}>{t("common.retry")}</Button>}
                />
              )}
              {jobs.data && items.length === 0 && (
                <ViewEmpty view={view} filtered={filtered} onReset={() => (setQ(""), setCategory([]), setWhere(""), setStretch(false))} />
              )}
              {items.length > 0 && (
                <ul
                  ref={listRef}
                  role="listbox"
                  aria-label={t(VIEWS.find((v) => v.id === view)?.label ?? "jobs.title")}
                  aria-multiselectable="true"
                  onKeyDown={onListKey}
                  className={cn("transition-opacity", jobs.isFetching && !jobs.isLoading && "opacity-70")}
                >
                  {items.map((job, i) => (
                    <JobRow
                      key={job.id}
                      job={job}
                      view={view}
                      lang={lang}
                      active={job.id === activeId}
                      selected={multi && selection.has(job.id)}
                      focusable={activeIndex < 0 ? i === 0 : job.id === activeId}
                      onClick={(e) => onRowClick(e, job.id)}
                    />
                  ))}
                </ul>
              )}
              {jobs.data && jobs.data.total > items.length && (
                <div className="py-3 text-center">
                  <Button variant="quiet" onClick={() => setLimit(limit + 60)}>
                    {t("jobs.more", { n: jobs.data.total - items.length })}
                  </Button>
                </div>
              )}
            </div>
            {split && (
              <div className="sticky top-4 max-h-[calc(100dvh-6rem)] min-w-0 self-start overflow-y-auto pt-4 pb-6 pl-6">
                {activeId !== null ? (
                  <JobDetail
                    key={activeId}
                    jobId={activeId}
                    decisions={decisions}
                    position={
                      activeIndex >= 0
                        ? { index: activeIndex, total: jobs.data?.total ?? items.length, prev: () => move(-1), next: () => move(1) }
                        : undefined
                    }
                  />
                ) : (
                  items.length > 0 && <p className="py-8 text-meta text-ink-3">{t("jobs.pick")}</p>
                )}
              </div>
            )}
          </div>
        </TabsContent>
      </Tabs>

      {multi ? (
        <div className="sticky bottom-[calc(3.25rem+env(safe-area-inset-bottom))] z-20 -mx-4 mt-4 flex flex-wrap items-center gap-2 border-t border-line bg-paper px-4 py-3 sm:-mx-6 sm:px-6 lg:bottom-0 lg:-mx-8 lg:px-8">
          <span className="mr-auto text-meta font-semibold" aria-live="polite">
            {t("bulk.selected", { n: selection.size })}
          </span>
          <Button size="sm" onClick={decisions.queue} disabled={act.isPending}>
            {t("decide.queue")} <Kbd>A</Kbd>
          </Button>
          <Button size="sm" onClick={decisions.star} disabled={act.isPending}>
            {t("decide.star")} <Kbd>S</Kbd>
          </Button>
          <Button size="sm" onClick={decisions.dismiss} disabled={act.isPending}>
            {t("decide.dismiss")} <Kbd>X</Kbd>
          </Button>
          <Button size="sm" variant="quiet" onClick={() => setApplyIds([...selection])}>
            {t("decide.apply_now")}
          </Button>
          <Button size="sm" variant="quiet" onClick={() => setSelection(new Set())}>
            {t("bulk.clear")}
          </Button>
        </div>
      ) : (
        <QueueBar />
      )}

      {!split && activeId !== null && (
        <Sheet
          open
          hotkeys
          onOpenChange={(open) => !open && setActive(null)}
          title={items[activeIndex]?.company ?? t("jobs.title")}
          className="max-w-[640px]"
          actions={
            activeIndex >= 0 && (
              <span className="tabular mr-1 text-small text-ink-3">
                {activeIndex + 1} / {jobs.data?.total ?? items.length}
              </span>
            )
          }
        >
          <div className="px-5 pt-4 pb-6">
            <JobDetail key={activeId} jobId={activeId} decisions={decisions} showDecisions={false} />
          </div>
          <SheetDecisions jobId={activeId} decisions={decisions} />
        </Sheet>
      )}

      <AddJobDialog open={addOpen} onOpenChange={setAddOpen} />
      <ApplyDialog open={applyIds !== null} onOpenChange={(v) => !v && setApplyIds(null)} jobIds={applyIds ?? []} />
    </>
  );
}

/** Entscheidungsleiste am unteren Rand der Seitenleiste (schmale Bildschirme): drei gleich breite Knöpfe. */
function SheetDecisions({ jobId, decisions }: { jobId: number; decisions: Decisions }) {
  const { data: job } = useQuery({ queryKey: ["job", jobId], queryFn: () => api.job(jobId) });
  if (!job) return null;
  return (
    <div className="safe-bottom sticky bottom-0 flex gap-2 border-t border-line bg-raised px-4 py-3">
      <DecisionButtons job={job} decisions={decisions} fill />
    </div>
  );
}

function Picker({ label, value, children }: { label: string; value: string; children: ReactNode }) {
  return (
    <Menu>
      <MenuTrigger className="flex h-8 max-w-56 items-center gap-1 rounded-md px-2 text-meta text-ink-2 hover:bg-sunken data-[state=open]:bg-sunken">
        {label}
        <span className="truncate font-medium text-ink">{value}</span>
        <span aria-hidden className="text-ink-3">▾</span>
      </MenuTrigger>
      <MenuContent align="start">{children}</MenuContent>
    </Menu>
  );
}

function JobRow({
  job,
  view,
  lang,
  active,
  selected,
  focusable,
  onClick,
}: {
  job: JobSummary;
  view: JobView;
  lang: string;
  active: boolean;
  selected: boolean;
  focusable: boolean;
  onClick: (e: MouseEvent) => void;
}) {
  const { t } = useI18n();
  const meta = [
    job.company,
    job.location.split(";")[0] || t(job.where === "R" ? "where.remote" : "where.onsite"),
    job.category,
    job.level === "S" ? t("level.S") : null,
    job.first_seen ? formatRelative(job.first_seen, lang) : null,
  ].filter(Boolean);
  // Stand nur dort zeigen, wo er nicht schon aus der Ansicht folgt
  const showStatus = job.app_status && !(view === "queued" && job.app_status === "queued");
  return (
    <li
      id={`job-row-${job.id}`}
      role="option"
      aria-selected={selected || active}
      tabIndex={focusable ? 0 : -1}
      onClick={onClick}
      className={cn(
        "relative grid cursor-pointer grid-cols-[minmax(0,1fr)_auto] items-center gap-3 border-b border-line px-3 py-2.5 transition-colors duration-[120ms] hover:bg-sunken focus-visible:-outline-offset-2",
        selected && "bg-accent-soft hover:bg-accent-soft",
        active && "bg-accent-soft shadow-[inset_2px_0_0_var(--accent)] hover:bg-accent-soft",
      )}
    >
      <span className="min-w-0">
        <span className="flex items-center gap-1.5">
          {selected && <Check className="size-3.5 shrink-0 text-accent" aria-hidden />}
          <span className="truncate font-semibold">{job.title}</span>
        </span>
        <span className="flex min-w-0 items-center gap-2 text-meta text-ink-2">
          <span className="truncate">{meta.join(" · ")}</span>
          {job.excluded && view !== "dismissed" && <span className="shrink-0 text-ink-3">{t("jobs.view_dismissed")}</span>}
          {job.starred && view !== "starred" && <span className="shrink-0 text-ink-3">{t("decide.starred_state")}</span>}
          {showStatus && <StatusLabel status={job.app_status} className="shrink-0" />}
        </span>
      </span>
      <Score score={job.score} />
    </li>
  );
}

function ListSkeleton() {
  return (
    <div className="grid gap-4 py-4" aria-busy="true">
      {Array.from({ length: 6 }, (_, i) => (
        <div key={i} className="grid gap-1.5 px-3">
          <Skeleton className="h-3.5 w-2/3" />
          <Skeleton className="h-3 w-1/3" />
        </div>
      ))}
    </div>
  );
}

function ViewEmpty({ view, filtered, onReset }: { view: JobView; filtered: boolean; onReset: () => void }) {
  const { t, lang } = useI18n();
  const { data: status } = useStatus();
  if (filtered) {
    return (
      <EmptyState
        title={t("jobs.empty_filtered")}
        action={
          <Button size="sm" onClick={onReset}>
            {t("common.reset")}
          </Button>
        }
      />
    );
  }
  const next = status?.autopilot.enabled
    ? t("today.next_search", { when: formatWhen(status.autopilot.next_run, lang) })
    : t("today.autopilot_off");
  const text: Record<JobView, [MessageKey, string]> = {
    triage: ["today.all_reviewed", next],
    starred: ["jobs.empty_starred", t("jobs.empty_starred_hint")],
    queued: ["jobs.empty_queued", t("jobs.empty_queued_hint")],
    all: ["jobs.empty", next],
    dismissed: ["jobs.empty_dismissed", t("jobs.empty_dismissed_hint")],
  };
  const [title, description] = text[view];
  return <EmptyState title={t(title)} description={description} />;
}
