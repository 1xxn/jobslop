import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, Plus, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { ChipsInput, SwitchRow } from "@/components/ui/controls";
import { Button, SectionBody, SectionHeader, Field, Input, Skeleton } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { type Portal, PORTALS, type SearchConfig } from "@/lib/types";
import { roleClass, sourceName } from "@/lib/utils";
import { SaveBar } from "./SaveBar";

/** Suche in drei Seiten: Zielrollen & Filter, Quellen, Limits – alle speichern dieselbe search.toml. */
export function SearchForm({ part }: { part: "roles" | "sources" | "limits" }) {
  const { t } = useI18n();
  const qc = useQueryClient();
  const data = useQuery({ queryKey: ["search"], queryFn: api.search });
  const [c, setC] = useState<SearchConfig | null>(null);
  const [dirty, setDirty] = useState(false);
  useEffect(() => {
    if (data.data && !dirty) setC(structuredClone(data.data));
  }, [data.data, dirty]);
  const save = useMutation({
    mutationFn: () => api.saveSearch(c as SearchConfig),
    onSuccess: (r) => {
      qc.setQueryData(["search"], r);
      setDirty(false);
      toast.success(t("search.saved"));
    },
    onError: (e: Error) => toast.error(e.message),
  });
  if (!c) return <Skeleton className="h-96 rounded-lg" />;
  const update = (next: SearchConfig) => {
    setC(next);
    setDirty(true);
  };
  return (
    <div className="space-y-10">
      {part === "roles" && <RolesEditor config={c} onChange={update} />}

      {part === "roles" && (
        <section>
          <SectionHeader title={t("search.filters")} description={t("search.filters_hint")} />
          <SectionBody className="space-y-4">
            <Field label={t("search.exclude")} hint={t("search.exclude_hint")}>
              <ChipsInput
                value={c.filters.exclude_titles}
                onChange={(v) => update({ ...c, filters: { ...c.filters, exclude_titles: v } })}
              />
            </Field>
            <Field label={t("search.cities")} hint={t("search.cities_hint")}>
              <ChipsInput
                value={c.filters.onsite_locations}
                onChange={(v) => update({ ...c, filters: { ...c.filters, onsite_locations: v } })}
                placeholder="Berlin, München, …"
              />
            </Field>
            <SwitchRow
              title={t("search.remote")}
              description={t("search.remote_hint")}
              checked={c.filters.allow_remote}
              onCheckedChange={(v) => update({ ...c, filters: { ...c.filters, allow_remote: v } })}
            />
            {c.filters.allow_remote && (
              <Field label={t("search.remote_regions")} hint={t("search.remote_regions_hint")}>
                <ChipsInput
                  value={c.filters.remote_regions}
                  onChange={(v) => update({ ...c, filters: { ...c.filters, remote_regions: v } })}
                />
              </Field>
            )}
            <SwitchRow
              title={t("search.stretch")}
              description={t("search.stretch_hint")}
              checked={c.filters.keep_stretch}
              onCheckedChange={(v) => update({ ...c, filters: { ...c.filters, keep_stretch: v } })}
            />
            <Field label={t("search.skills")} hint={t("search.skills_hint")}>
              <ChipsInput value={c.skills} onChange={(v) => update({ ...c, skills: v })} />
            </Field>
          </SectionBody>
        </section>
      )}

      {part === "sources" && (
        <section>
          <SectionBody className="space-y-4">
            <Field label={t("search.queries")} hint={t("search.queries_hint")}>
              <ChipsInput
                value={c.sources.queries}
                onChange={(v) => update({ ...c, sources: { ...c.sources, queries: v } })}
              />
            </Field>
            <SwitchRow
              title={t("search.arbeitsagentur")}
              description={t("search.arbeitsagentur_hint")}
              checked={c.sources.arbeitsagentur}
              onCheckedChange={(v) => update({ ...c, sources: { ...c.sources, arbeitsagentur: v } })}
            />
            {PORTALS.map((portal) => (
              <SwitchRow
                key={portal}
                title={t(`search.portal_${portal}`)}
                description={t(`search.portal_${portal}_hint`)}
                checked={c.sources.portals.includes(portal)}
                onCheckedChange={(v) => {
                  const portals: Portal[] = v
                    ? [...c.sources.portals, portal]
                    : c.sources.portals.filter((p) => p !== portal);
                  update({ ...c, sources: { ...c.sources, portals } });
                }}
              />
            ))}
            <SwitchRow
              title={t("search.himalayas")}
              description={t("search.himalayas_hint")}
              checked={c.sources.himalayas}
              onCheckedChange={(v) => update({ ...c, sources: { ...c.sources, himalayas: v } })}
            />
            <SwitchRow
              title={sourceName("arbeitnow", t)}
              description={t("search.arbeitnow_hint")}
              checked={c.sources.arbeitnow}
              onCheckedChange={(v) => update({ ...c, sources: { ...c.sources, arbeitnow: v } })}
            />
            <SwitchRow
              title={t("search.discover")}
              description={t("search.discover_hint")}
              checked={c.sources.discover_boards}
              onCheckedChange={(v) => update({ ...c, sources: { ...c.sources, discover_boards: v } })}
            />
            <p className="text-meta text-ink-2">{t("search.portals_terms")}</p>
            <div className="grid gap-4 md:grid-cols-2">
              {(["greenhouse", "ashby", "lever", "smartrecruiters", "personio", "recruitee", "workable"] as const).map((key) => (
                <Field key={key} label={sourceName(key, t)} hint={t(`search.board_${key}`)}>
                  <ChipsInput value={c.sources[key]} onChange={(v) => update({ ...c, sources: { ...c.sources, [key]: v } })} />
                </Field>
              ))}
              <Field label="Amazon" hint={t("search.amazon_hint")}>
                <ChipsInput
                  value={c.sources.amazon_queries}
                  onChange={(v) => update({ ...c, sources: { ...c.sources, amazon_queries: v } })}
                />
              </Field>
            </div>
            <GenericPages config={c} onChange={update} />
          </SectionBody>
        </section>
      )}

      {part === "limits" && (
        <section>
          <SectionBody className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <NumberField
              label={t("search.limit_company")}
              hint={t("search.limit_company_hint", { days: c.limits.company_window_days })}
              value={c.limits.max_per_company_window}
              onChange={(v) => update({ ...c, limits: { ...c.limits, max_per_company_window: v } })}
            />
            <NumberField
              label={t("search.limit_window")}
              value={c.limits.company_window_days}
              onChange={(v) => update({ ...c, limits: { ...c.limits, company_window_days: v } })}
            />
            <NumberField
              label={t("search.limit_run")}
              value={c.limits.max_applications_per_run}
              onChange={(v) => update({ ...c, limits: { ...c.limits, max_applications_per_run: v } })}
            />
            <NumberField
              label={t("search.limit_delay")}
              value={c.limits.min_delay_seconds}
              onChange={(v) => update({ ...c, limits: { ...c.limits, min_delay_seconds: v } })}
            />
            <NumberField
              label={t("search.limit_score")}
              hint={t("search.limit_score_hint")}
              value={c.limits.min_score_for_auto_queue}
              onChange={(v) => update({ ...c, limits: { ...c.limits, min_score_for_auto_queue: v } })}
            />
            <NumberField
              label={t("search.limit_enrich")}
              hint={t("search.limit_enrich_hint")}
              value={c.limits.max_enrich_per_crawl}
              onChange={(v) => update({ ...c, limits: { ...c.limits, max_enrich_per_crawl: v } })}
            />
          </SectionBody>
        </section>
      )}

      <SaveBar dirty={dirty} saving={save.isPending} onSave={() => save.mutate()} onReset={() => setDirty(false)} />
    </div>
  );
}

export function RolesEditor({ config, onChange }: { config: SearchConfig; onChange: (c: SearchConfig) => void }) {
  const { t } = useI18n();
  const names = config.roles.map((r) => r.name);
  const setRoles = (roles: SearchConfig["roles"]) => onChange({ ...config, roles, filters: { ...config.filters, include_titles: [] } });
  const move = (i: number, d: number) => {
    const next = [...config.roles];
    const [r] = next.splice(i, 1);
    next.splice(i + d, 0, r);
    setRoles(next);
  };
  return (
    <section>
      <SectionHeader
        title={t("search.roles")}
        description={t("search.roles_hint")}
        action={
          <Button size="sm" variant="secondary" onClick={() => setRoles([...config.roles, { name: t("search.new_role"), keywords: [] }])}>
            {t("search.add_role")}
          </Button>
        }
      />
      <SectionBody className="space-y-3 pt-3">
        {config.filters.include_titles.length > 0 && (
          <p className="rounded-md bg-sunken px-3 py-2 text-meta">{t("search.legacy_include")}</p>
        )}
        {config.roles.map((role, i) => (
          <div key={i} className={`border-b border-line pb-3 last:border-b-0 ${roleClass(role.name, names)}`}>
            <div className="mb-2 flex items-center gap-2">
              <span className="size-2.5 shrink-0 rounded-full bg-[var(--role)]" />
              <Input
                value={role.name}
                onChange={(e) => setRoles(config.roles.map((r, j) => (j === i ? { ...r, name: e.target.value } : r)))}
                className="h-8 max-w-56 font-semibold"
                aria-label={t("search.role_name")}
              />
              <span className="ml-auto text-small text-ink-3">{t("search.priority", { n: i + 1 })}</span>
              <Button size="icon-sm" variant="quiet" disabled={i === 0} onClick={() => move(i, -1)} aria-label={t("common.up")}>
                <ArrowUp />
              </Button>
              <Button
                size="icon-sm"
                variant="quiet"
                disabled={i === config.roles.length - 1}
                onClick={() => move(i, 1)}
                aria-label={t("common.down")}
              >
                <ArrowDown />
              </Button>
              <Button
                size="icon-sm"
                variant="quiet"
                onClick={() => setRoles(config.roles.filter((_, j) => j !== i))}
                aria-label={t("common.delete")}
              >
                <Trash2 />
              </Button>
            </div>
            <ChipsInput
              value={role.keywords}
              onChange={(v) => setRoles(config.roles.map((r, j) => (j === i ? { ...r, keywords: v } : r)))}
              placeholder={t("search.keywords_placeholder")}
            />
          </div>
        ))}
      </SectionBody>
    </section>
  );
}

function GenericPages({ config, onChange }: { config: SearchConfig; onChange: (c: SearchConfig) => void }) {
  const { t } = useI18n();
  const pages = config.sources.generic;
  const set = (next: typeof pages) => onChange({ ...config, sources: { ...config.sources, generic: next } });
  return (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <div>
          <div className="text-meta font-medium">{t("search.generic")}</div>
          <div className="text-small text-ink-2">{t("search.generic_hint")}</div>
        </div>
        <Button size="sm" variant="quiet" onClick={() => set([...pages, { company: "", url: "" }])}>
          <Plus />
          {t("common.add")}
        </Button>
      </div>
      <div className="space-y-2">
        {pages.map((p, i) => (
          <div key={i} className="grid gap-2 sm:grid-cols-[180px_1fr_auto]">
            <Input
              placeholder={t("search.company")}
              value={p.company}
              onChange={(e) => set(pages.map((x, j) => (j === i ? { ...x, company: e.target.value } : x)))}
            />
            <Input
              placeholder="https://…/jobs"
              value={p.url}
              onChange={(e) => set(pages.map((x, j) => (j === i ? { ...x, url: e.target.value } : x)))}
            />
            <Button size="icon" variant="quiet" onClick={() => set(pages.filter((_, j) => j !== i))} aria-label={t("common.delete")}>
              <Trash2 />
            </Button>
          </div>
        ))}
      </div>
    </div>
  );
}

function NumberField({ label, hint, value, onChange }: { label: string; hint?: string; value: number; onChange: (v: number) => void }) {
  return (
    <Field label={label} hint={hint}>
      <Input type="number" value={value} min={0} onChange={(e) => onChange(Number(e.target.value) || 0)} className="w-32" />
    </Field>
  );
}
