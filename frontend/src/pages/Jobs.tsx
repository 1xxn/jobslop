import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Ban, Bookmark, BookmarkCheck, Clock, Link2, Play, RefreshCw, Search, SlidersHorizontal, X } from "lucide-react";
import { useMemo, useState } from "react";
import { useSearchParams } from "react-router";
import { toast } from "sonner";
import { AddJobDialog, ApplyDialog } from "@/components/actions";
import { CompanyAvatar, FitDots, PageHeader, RoleBadge, ScoreRing, StatusBadge } from "@/components/domain";
import { JobSheet } from "@/components/JobSheet";
import { Checkbox, Segmented, Switch } from "@/components/ui/controls";
import { Tooltip } from "@/components/ui/overlays";
import { Button, Card, EmptyState, Input, Select, Skeleton } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { useDebounced, useRoleNames, useStatus } from "@/lib/hooks";
import { useI18n } from "@/lib/i18n";
import type { JobSummary } from "@/lib/types";
import { cn, formatRelative, roleClass, sourceName } from "@/lib/utils";

type View = "todo" | "starred" | "queued" | "applied" | "all";

export function JobsPage() {
  const { t, lang } = useI18n();
  const qc = useQueryClient();
  const roles = useRoleNames();
  const { data: status } = useStatus();
  const [params, setParams] = useSearchParams();
  const [q, setQ] = useState("");
  const [view, setView] = useState<View>("todo");
  const [category, setCategory] = useState<string[]>([]);
  const [where, setWhere] = useState("");
  const [stretch, setStretch] = useState(false);
  const [sort, setSort] = useState("score");
  const [limit, setLimit] = useState(60);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [addOpen, setAddOpen] = useState(false);
  const [applyIds, setApplyIds] = useState<number[] | null>(null);
  const query = useDebounced(q);

  const jobs = useQuery({
    queryKey: ["jobs", { query, view, category, where, stretch, sort, limit }],
    queryFn: () =>
      api.jobs({
        q: query,
        view,
        category: category.join(","),
        where,
        level: stretch ? "" : "noS",
        status: view === "all" || view === "applied" ? "all" : "open",
        sort,
        limit,
      }),
    placeholderData: keepPreviousData,
  });
  const openJob = params.get("job") ? Number(params.get("job")) : null;
  const setOpenJob = (id: number | null) => {
    const next = new URLSearchParams(params);
    if (id === null) next.delete("job");
    else next.set("job", String(id));
    setParams(next, { replace: true });
  };

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["jobs"] });
    qc.invalidateQueries({ queryKey: ["status"] });
  };
  const patch = useMutation({
    mutationFn: ({ id, body }: { id: number; body: { queued?: boolean; starred?: boolean } }) => api.patchJob(id, body),
    onSuccess: refresh,
    onError: (e: Error) => toast.error(e.message),
  });
  const bulk = useMutation({
    mutationFn: ({ action }: { action: "queue" | "star" | "exclude" | "unqueue" }) => api.bulk([...selected], action),
    onSuccess: (r, { action }) => {
      toast.success(t(`bulk.${action}`, { n: r.changed.length }));
      if (r.skipped.length) toast(t("bulk.skipped", { n: r.skipped.length }), { description: r.skipped.slice(0, 3).join("\n") });
      setSelected(new Set());
      refresh();
    },
  });
  const crawl = useMutation({
    mutationFn: api.crawl,
    onSuccess: (r) => toast(r.started ? t("crawl.started") : t("crawl.running")),
  });

  const facets = jobs.data?.facets.category ?? {};
  const facetNames = useMemo(
    () => [...roles.filter((r) => facets[r] || category.includes(r)), ...(facets.Other ? ["Other"] : [])],
    [roles, facets, category],
  );
  const items = jobs.data?.items ?? [];
  const allSelected = items.length > 0 && items.every((j) => selected.has(j.id));
  const toggle = (id: number) => {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSelected(next);
  };

  return (
    <>
      <PageHeader
        title={t("jobs.title")}
        description={jobs.data ? t("jobs.count", { n: jobs.data.total }) : " "}
        actions={
          <>
            <Button variant="outline" onClick={() => setAddOpen(true)}>
              <Link2 />
              {t("addjob.short")}
            </Button>
            <Button variant="outline" onClick={() => crawl.mutate()} loading={!!status?.crawl.running}>
              {!status?.crawl.running && <RefreshCw />}
              {status?.crawl.running ? t("crawl.running_short") : t("crawl.start")}
            </Button>
          </>
        }
      />

      <div className="sticky top-0 z-20 -mx-4 mb-4 space-y-3 bg-bg/85 px-4 py-3 backdrop-blur-xl sm:-mx-6 sm:px-6 lg:-mx-10 lg:px-10">
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative min-w-56 flex-1">
            <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-fg-subtle" />
            <Input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder={t("jobs.search")}
              className="pl-9"
              aria-label={t("jobs.search")}
            />
          </div>
          <Segmented<View>
            value={view}
            onChange={(v) => {
              setView(v);
              setSelected(new Set());
            }}
            options={[
              { value: "todo", label: t("jobs.view_todo") },
              { value: "starred", label: t("jobs.view_starred") },
              { value: "queued", label: t("jobs.view_queued") },
              { value: "applied", label: t("jobs.view_applied") },
              { value: "all", label: t("jobs.view_all") },
            ]}
            className="max-w-full overflow-x-auto"
          />
          <Button
            variant={filtersOpen ? "soft" : "outline"}
            size="icon"
            onClick={() => setFiltersOpen(!filtersOpen)}
            aria-label={t("jobs.filters")}
            aria-expanded={filtersOpen}
          >
            <SlidersHorizontal />
          </Button>
        </div>
        {filtersOpen && (
          <div className="flex flex-wrap items-center gap-x-5 gap-y-3 animate-fade-in">
            <Segmented
              size="sm"
              value={where || "any"}
              onChange={(v) => setWhere(v === "any" ? "" : v)}
              options={[
                { value: "any", label: t("where.any") },
                { value: "B", label: t("where.onsite") },
                { value: "R", label: t("where.remote") },
              ]}
            />
            <label className="flex items-center gap-2 text-footnote text-fg-muted">
              <Switch checked={stretch} onCheckedChange={setStretch} label={t("jobs.show_stretch")} />
              {t("jobs.show_stretch")}
            </label>
            <label className="flex items-center gap-2 text-footnote text-fg-muted">
              {t("jobs.sort")}
              <Select value={sort} onChange={(e) => setSort(e.target.value)} className="h-8 w-auto text-footnote">
                <option value="score">{t("jobs.sort_score")}</option>
                <option value="new">{t("jobs.sort_new")}</option>
                <option value="company">{t("jobs.sort_company")}</option>
              </Select>
            </label>
          </div>
        )}
        {facetNames.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {facetNames.map((name) => {
              const active = category.includes(name);
              return (
                <button
                  key={name}
                  type="button"
                  onClick={() => setCategory(active ? category.filter((c) => c !== name) : [...category, name])}
                  className={cn(
                    "inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-footnote font-medium transition-colors",
                    roleClass(name, roles),
                    active
                      ? "border-[var(--role)] bg-[color-mix(in_oklch,var(--role)_14%,transparent)] text-fg"
                      : "border-border bg-surface text-fg-muted hover:text-fg",
                  )}
                >
                  <span className="size-1.5 rounded-full bg-[var(--role)]" />
                  {name}
                  <span className="tabular text-fg-subtle">{facets[name] ?? 0}</span>
                </button>
              );
            })}
            {category.length > 0 && (
              <Button variant="ghost" size="sm" onClick={() => setCategory([])}>
                <X />
                {t("common.reset")}
              </Button>
            )}
          </div>
        )}
      </div>

      {selected.size > 0 && (
        <div className="glass fixed inset-x-4 bottom-20 z-30 mx-auto flex max-w-2xl flex-wrap items-center gap-2 rounded-xl border border-border px-4 py-3 shadow-lg animate-slide-up lg:bottom-6 lg:left-[248px]">
          <span className="mr-auto text-[0.875rem] font-medium">{t("bulk.selected", { n: selected.size })}</span>
          <Button size="sm" variant="ghost" onClick={() => bulk.mutate({ action: "star" })}>
            <Bookmark />
            {t("job.star")}
          </Button>
          <Button size="sm" variant="ghost" onClick={() => bulk.mutate({ action: "exclude" })}>
            <Ban />
            {t("bulk.exclude_short")}
          </Button>
          <Button size="sm" variant="outline" onClick={() => bulk.mutate({ action: "queue" })}>
            <Clock />
            {t("job.queue")}
          </Button>
          <Button size="sm" variant="primary" onClick={() => setApplyIds([...selected])}>
            <Play />
            {t("job.apply_now")}
          </Button>
        </div>
      )}

      <Card className="overflow-hidden">
        <div className="hidden items-center gap-4 border-b border-border px-4 py-2.5 text-caption font-medium text-fg-subtle md:flex">
          <Checkbox
            checked={allSelected}
            onCheckedChange={(v) => setSelected(v ? new Set(items.map((j) => j.id)) : new Set())}
            label={t("bulk.select_all")}
          />
          <span className="w-9" />
          <span className="flex-1">{t("jobs.col_job")}</span>
          <span className="w-36">{t("jobs.col_role")}</span>
          <span className="w-16 text-center">{t("job.stack")}</span>
          <span className="w-28">{t("jobs.col_status")}</span>
          <span className="w-20 text-right">{t("jobs.col_score")}</span>
        </div>
        {jobs.isLoading && (
          <div className="divide-y divide-border">
            {Array.from({ length: 8 }, (_, i) => (
              <div key={i} className="px-4 py-3.5">
                <Skeleton className="h-10" />
              </div>
            ))}
          </div>
        )}
        {!jobs.isLoading && items.length === 0 && (
          <EmptyState
            icon={<Search />}
            title={t("jobs.empty")}
            description={t("jobs.empty_hint")}
            action={
              <Button variant="primary" onClick={() => crawl.mutate()}>
                <RefreshCw />
                {t("crawl.start")}
              </Button>
            }
          />
        )}
        <ul className={cn("divide-y divide-border transition-opacity", jobs.isFetching && !jobs.isLoading && "opacity-70")}>
          {items.map((job) => (
            <JobRow
              key={job.id}
              job={job}
              roles={roles}
              lang={lang}
              selected={selected.has(job.id)}
              onSelect={() => toggle(job.id)}
              onOpen={() => setOpenJob(job.id)}
              onStar={() => patch.mutate({ id: job.id, body: { starred: !job.starred } })}
            />
          ))}
        </ul>
        {jobs.data && jobs.data.total > items.length && (
          <div className="border-t border-border p-3 text-center">
            <Button variant="ghost" onClick={() => setLimit(limit + 60)}>
              {t("jobs.more", { n: jobs.data.total - items.length })}
            </Button>
          </div>
        )}
      </Card>

      <JobSheet jobId={openJob} onClose={() => setOpenJob(null)} />
      <AddJobDialog open={addOpen} onOpenChange={setAddOpen} />
      <ApplyDialog open={applyIds !== null} onOpenChange={(v) => !v && setApplyIds(null)} jobIds={applyIds ?? []} />
    </>
  );
}

function JobRow({
  job,
  roles,
  lang,
  selected,
  onSelect,
  onOpen,
  onStar,
}: {
  job: JobSummary;
  roles: string[];
  lang: string;
  selected: boolean;
  onSelect: () => void;
  onOpen: () => void;
  onStar: () => void;
}) {
  const { t } = useI18n();
  return (
    <li
      className={cn(
        "group flex cursor-pointer items-center gap-4 px-4 py-3 transition-colors hover:bg-surface-2/70",
        selected && "bg-primary-soft hover:bg-primary-soft",
      )}
      onClick={onOpen}
      onKeyDown={(e) => e.key === "Enter" && onOpen()}
      tabIndex={0}
    >
      <Checkbox checked={selected} onCheckedChange={onSelect} label={job.title} />
      <CompanyAvatar name={job.company} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="truncate text-[0.9375rem] font-semibold">{job.title}</span>
          {job.level === "S" && <span className="text-caption text-fg-subtle">· {t("level.S")}</span>}
        </div>
        <div className="flex items-center gap-1.5 truncate text-footnote text-fg-muted">
          <span className="truncate">{job.company}</span>
          <span className="text-fg-subtle">·</span>
          <span className="truncate">{job.location.split(";")[0] || t(job.where === "R" ? "where.remote" : "where.onsite")}</span>
          {job.first_seen && (
            <span className="hidden text-fg-subtle sm:inline">· {formatRelative(job.first_seen, lang)}</span>
          )}
          <span className="hidden text-fg-subtle lg:inline">· {sourceName(job.source, t)}</span>
        </div>
      </div>
      <div className="hidden w-36 md:block">
        <RoleBadge category={job.category} roles={roles} />
      </div>
      <div className="hidden w-16 justify-center md:flex">
        <FitDots fit={job.fit} />
      </div>
      <div className="hidden w-28 md:block">
        <StatusBadge status={job.app_status} />
      </div>
      <div className="flex w-20 items-center justify-end gap-1">
        <Tooltip content={job.starred ? t("job.unstar") : t("job.star")}>
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onStar();
            }}
            className={cn(
              "grid size-8 place-items-center rounded-full text-fg-subtle transition-opacity hover:bg-surface-3 hover:text-fg",
              !job.starred && "opacity-0 group-hover:opacity-100 focus-visible:opacity-100",
            )}
            aria-label={job.starred ? t("job.unstar") : t("job.star")}
          >
            {job.starred ? <BookmarkCheck className="size-4 text-primary" /> : <Bookmark className="size-4" />}
          </button>
        </Tooltip>
        <ScoreRing score={job.score} />
      </div>
    </li>
  );
}
