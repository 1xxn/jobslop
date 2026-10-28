import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Pencil,
  Plus,
  Trash2,
} from "lucide-react";
import { type ReactNode, useEffect, useState } from "react";
import { useNavigate } from "react-router";
import { toast } from "sonner";
import { LoadError, Pending, StatusGlyph } from "@/components/domain";
import { SwitchRow } from "@/components/ui/controls";
import { Dialog, DialogContent } from "@/components/ui/overlays";
import {
  Badge,
  Button,
  SectionBody,
  SectionHeader,
  EmptyState,
  Field,
  Input,
  Select,
  Textarea,
} from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import type { Answer, ApplyMode, Exclusion, Settings } from "@/lib/types";
import { cn, formatRelative } from "@/lib/utils";
import { SaveBar } from "./SaveBar";

function useSettingsForm() {
  const { t } = useI18n();
  const qc = useQueryClient();
  const data = useQuery({ queryKey: ["settings"], queryFn: api.settings });
  const [s, setS] = useState<Settings | null>(null);
  const [dirty, setDirty] = useState(false);
  useEffect(() => {
    if (data.data && !dirty) setS(data.data);
  }, [data.data, dirty]);
  const save = useMutation({
    mutationFn: () => {
      const { home: _home, ...rest } = s as Settings;
      return api.saveSettings(rest);
    },
    onSuccess: (r) => {
      qc.setQueryData(["settings"], r);
      qc.invalidateQueries({ queryKey: ["status"] });
      setDirty(false);
      toast.success(t("common.saved"));
    },
  });
  const set = <K extends keyof Settings>(k: K, v: Settings[K]) => {
    setS((prev) => (prev ? { ...prev, [k]: v } : prev));
    setDirty(true);
  };
  const bar = <SaveBar dirty={dirty} saving={save.isPending} onSave={() => save.mutate()} onReset={() => setDirty(false)} />;
  const pending = <Pending query={data} className="h-80 rounded-lg" />;
  return { s, set, bar, pending };
}

/* ----------------------------------------------------------------- Bewerben */

export function ApplySettings() {
  const { t } = useI18n();
  const { s, set, bar, pending } = useSettingsForm();
  if (!s) return pending;
  return (
    <div className="space-y-10">
      <section>
        <SectionHeader title={t("applyset.title")} />
        <SectionBody className="space-y-4">
          <Field label={t("applyset.mode")} hint={t("applyset.mode_hint")}>
            <Select value={s.apply_mode} onChange={(e) => set("apply_mode", e.target.value as ApplyMode)} className="max-w-72">
              <option value="review">{t("mode.review")}</option>
              <option value="auto">{t("mode.auto")}</option>
              <option value="dry-run">{t("mode.dry")}</option>
            </Select>
          </Field>
          <div className="divide-y divide-line">
            <SwitchRow
              title={t("applyset.autofill")}
              description={t("applyset.autofill_hint")}
              checked={s.autofill}
              onCheckedChange={(v) => set("autofill", v)}
            />
            <SwitchRow
              title={t("applyset.headless")}
              description={t("applyset.headless_hint")}
              checked={s.headless}
              onCheckedChange={(v) => set("headless", v)}
            />
          </div>
          <Field label={t("applyset.followup")} hint={t("applyset.followup_hint")}>
            <Input type="number" min={1} value={s.follow_up_days} onChange={(e) => set("follow_up_days", Number(e.target.value) || 7)} className="w-28" />
          </Field>
        </SectionBody>
      </section>
      <section>
        <SectionHeader title={t("applyset.ai")} description={t("applyset.ai_hint")} />
        <SectionBody className="grid gap-4 sm:grid-cols-2">
          <Field label={t("applyset.model")} hint={t("applyset.model_hint")}>
            <Select value={s.llm_model} onChange={(e) => set("llm_model", e.target.value)}>
              <option value="sonnet">Sonnet</option>
              <option value="opus">Opus</option>
              <option value="haiku">Haiku</option>
            </Select>
          </Field>
          <Field label={t("applyset.model_fast")} hint={t("applyset.model_fast_hint")}>
            <Select value={s.llm_model_fast} onChange={(e) => set("llm_model_fast", e.target.value)}>
              <option value="haiku">Haiku</option>
              <option value="sonnet">Sonnet</option>
            </Select>
          </Field>
          <Field label={t("applyset.vision")} hint={t("applyset.vision_hint")}>
            <Select value={s.vision} onChange={(e) => set("vision", e.target.value as Settings["vision"])}>
              <option value="auto">{t("applyset.vision_auto")}</option>
              <option value="always">{t("applyset.vision_always")}</option>
              <option value="never">{t("applyset.vision_never")}</option>
            </Select>
          </Field>
          <Field label={t("applyset.parallel")} hint={t("applyset.parallel_hint")}>
            <Input type="number" min={1} max={6} value={s.claude_parallel} onChange={(e) => set("claude_parallel", Number(e.target.value) || 1)} className="w-28" />
          </Field>
        </SectionBody>
      </section>
      {bar}
    </div>
  );
}

/* ----------------------------------------------------------------- Browser-Erweiterung */

export function ExtensionSettings() {
  const { s, set, bar, pending } = useSettingsForm();
  if (!s) return pending;
  return (
    <div className="space-y-10">
      <ExtensionSection
        portals={s.extension_portals}
        limit={s.extension_portal_daily_limit}
        onPortals={(v) => set("extension_portals", v)}
        onLimit={(v) => set("extension_portal_daily_limit", v)}
      />
      {bar}
    </div>
  );
}

function ExtensionSection({
  portals,
  limit,
  onPortals,
  onLimit,
}: {
  portals: boolean;
  limit: number;
  onPortals: (v: boolean) => void;
  onLimit: (v: number) => void;
}) {
  const { t } = useI18n();
  const qc = useQueryClient();
  const info = useQuery({ queryKey: ["extension"], queryFn: api.extension });
  const install = useMutation({
    mutationFn: api.installExtension,
    onSuccess: (r) => {
      qc.setQueryData(["extension"], r);
      toast.success(t("ext.installed"));
    },
  });
  const folder = useMutation({ mutationFn: api.openExtensionFolder });
  const x = info.data;
  return (
    <section>
      <p className="max-w-prose text-meta text-ink-2">{t("ext.hint")}</p>
      <SectionBody className="space-y-4">
        {info.isError && <LoadError error={info.error} onRetry={() => info.refetch()} />}
        {x && (
          <StatusLine
            ok={x.installed && !x.outdated}
            title={x.installed ? (x.outdated ? t("ext.outdated") : t("ext.ready")) : t("ext.missing")}
            text={x.installed ? <code className="break-all text-meta">{x.path}</code> : t("ext.missing_hint")}
            action={
              <div className="flex flex-wrap gap-2">
                <Button size="sm" variant={x.installed && !x.outdated ? "secondary" : "primary"} onClick={() => install.mutate()} disabled={install.isPending}>
                  {x.installed ? t("ext.update") : t("ext.install")}
                </Button>
                {x.installed && (
                  <Button size="sm" variant="secondary" onClick={() => folder.mutate()}>
                    {t("ext.open_folder")}
                  </Button>
                )}
              </div>
            }
          />
        )}
        <ol className="list-decimal space-y-1 pl-5 text-body text-ink-2">
          <li>{t("ext.step1")}</li>
          <li>{t("ext.step2")}</li>
          <li>{t("ext.step3")}</li>
          <li>{t("ext.step4")}</li>
        </ol>
        <div className="divide-y divide-line">
          <SwitchRow title={t("ext.portals")} description={t("ext.portals_hint")} checked={portals} onCheckedChange={onPortals} />
        </div>
        {portals && (
          <Field
            label={t("ext.limit")}
            hint={x ? t("ext.limit_hint", { used: x.portal_used, limit: x.portal_limit }) : undefined}
          >
            <Input type="number" min={0} max={100} value={limit} onChange={(e) => onLimit(Number(e.target.value) || 0)} className="w-28" />
          </Field>
        )}
      </SectionBody>
    </section>
  );
}

/* ----------------------------------------------------------------- Autopilot */

export function AutopilotSettings() {
  const { t } = useI18n();
  const { s, set, bar, pending } = useSettingsForm();
  if (!s) return pending;
  const days = [t("day.mon"), t("day.tue"), t("day.wed"), t("day.thu"), t("day.fri"), t("day.sat"), t("day.sun")];
  return (
    <div className="space-y-10">
      <section>
        <SectionHeader description={t("autopilot.hint")} />
        <SectionBody className="space-y-5">
          <SwitchRow
            title={t("autopilot.enable")}
            description={t("autopilot.enable_hint")}
            checked={s.autopilot_enabled}
            onCheckedChange={(v) => set("autopilot_enabled", v)}
          />
          <div className={cn("space-y-5", !s.autopilot_enabled && "pointer-events-none opacity-50")}>
            <Field label={t("autopilot.days")}>
              <div className="flex flex-wrap gap-1.5">
                {days.map((d, i) => {
                  const on = s.autopilot_days.includes(i);
                  return (
                    <button
                      key={d}
                      type="button"
                      onClick={() =>
                        set("autopilot_days", on ? s.autopilot_days.filter((x) => x !== i) : [...s.autopilot_days, i].sort())
                      }
                      className={cn(
                        "h-9 w-12 rounded-md border text-meta font-medium transition-colors",
                        on ? "border-accent bg-accent text-on-accent" : "border-line-input bg-raised text-ink-2 hover:bg-sunken",
                      )}
                      aria-pressed={on}
                    >
                      {d}
                    </button>
                  );
                })}
              </div>
            </Field>
            <Field label={t("autopilot.time")}>
              <Input type="time" value={s.autopilot_time} onChange={(e) => set("autopilot_time", e.target.value)} className="w-32" />
            </Field>
            <SwitchRow
              title={t("autopilot.apply")}
              description={t("autopilot.apply_hint")}
              checked={s.autopilot_apply}
              onCheckedChange={(v) => set("autopilot_apply", v)}
            />
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label={t("autopilot.max")}>
                <Input
                  type="number"
                  min={1}
                  max={30}
                  value={s.autopilot_apply_max}
                  onChange={(e) => set("autopilot_apply_max", Number(e.target.value) || 1)}
                  className="w-28"
                />
              </Field>
              <Field label={t("autopilot.mode")} hint={t("autopilot.mode_hint")}>
                <Select value={s.autopilot_apply_mode} onChange={(e) => set("autopilot_apply_mode", e.target.value as ApplyMode)}>
                  <option value="review">{t("mode.review")}</option>
                  <option value="auto">{t("mode.auto")}</option>
                  <option value="dry-run">{t("mode.dry")}</option>
                </Select>
              </Field>
            </div>
          </div>
        </SectionBody>
      </section>
      <section>
        <SectionHeader title={t("autopilot.os_title")} description={t("autopilot.os_hint")} />
        <SectionBody>
          <pre className="overflow-x-auto rounded-md bg-sunken px-4 py-3 font-mono text-meta">
            {`schtasks /Create /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST ${s.autopilot_time} /TN jobslop /TR "jobslop autopilot"`}
          </pre>
          <p className="mt-2 text-small text-ink-2">{t("autopilot.os_unix")}</p>
          <pre className="mt-1 overflow-x-auto rounded-md bg-sunken px-4 py-3 font-mono text-meta">{`${Number(s.autopilot_time.split(":")[1] ?? 0)} ${Number(s.autopilot_time.split(":")[0] ?? 8)} * * 1-5  jobslop autopilot`}</pre>
        </SectionBody>
      </section>
      {bar}
    </div>
  );
}

/* ----------------------------------------------------------------- Benachrichtigungen */

export function NotificationSettings() {
  const { t } = useI18n();
  const { s, set, bar, pending } = useSettingsForm();
  const [permission, setPermission] = useState(typeof Notification !== "undefined" ? Notification.permission : "denied");
  const test = useMutation({
    mutationFn: () => fetch("/api/notify/test", { method: "POST", headers: { "X-Jobslop": "1" } }).then((r) => r.json()),
    onSuccess: (r: { sent: number }) =>
      r.sent ? toast.success(t("notify.test_ok", { n: r.sent })) : toast(t("notify.test_none")),
  });
  if (!s) return pending;
  return (
    <div className="space-y-10">
      <section>
        <SectionHeader title={t("notify.browser")} description={t("notify.browser_hint")} />
        <SectionBody className="space-y-3">
          <SwitchRow title={t("notify.desktop")} checked={s.notify_desktop} onCheckedChange={(v) => set("notify_desktop", v)} />
          {permission !== "granted" && (
            <Button
              variant="secondary"
              size="sm"
              onClick={async () => setPermission(await Notification.requestPermission())}
              disabled={permission === "denied"}
            >
              {permission === "denied" ? t("notify.blocked") : t("notify.allow")}
            </Button>
          )}
        </SectionBody>
      </section>
      <section>
        <SectionHeader title={t("notify.push")} description={t("notify.push_hint")} />
        <SectionBody className="space-y-4">
          <Field label="ntfy" hint={t("notify.ntfy_hint")}>
            <Input
              type="url"
              placeholder="https://ntfy.sh/jobslop-dein-geheimes-thema"
              value={s.notify_ntfy_url}
              onChange={(e) => set("notify_ntfy_url", e.target.value.trim())}
            />
          </Field>
          <Field label="Webhook" hint={t("notify.webhook_hint")}>
            <Input
              type="url"
              placeholder="https://discord.com/api/webhooks/…"
              value={s.notify_webhook_url}
              onChange={(e) => set("notify_webhook_url", e.target.value.trim())}
            />
          </Field>
          <Button variant="secondary" size="sm" onClick={() => test.mutate()} loading={test.isPending}>
            {t("notify.test")}
          </Button>
        </SectionBody>
      </section>
      {bar}
    </div>
  );
}

/* ----------------------------------------------------------------- Antwortbank */

export function AnswersSettings() {
  const { t, lang } = useI18n();
  const qc = useQueryClient();
  const answers = useQuery({ queryKey: ["answers"], queryFn: api.answers });
  const [editing, setEditing] = useState<Partial<Answer> | null>(null);
  const [filter, setFilter] = useState("");
  const save = useMutation({
    mutationFn: (a: Partial<Answer>) =>
      a.id ? api.updateAnswer(a.id, a.question ?? "", a.answer ?? "") : api.createAnswer(a.question ?? "", a.answer ?? ""),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["answers"] });
      setEditing(null);
      toast.success(t("common.saved"));
    },
  });
  const remove = useMutation({
    mutationFn: api.deleteAnswer,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["answers"] }),
  });
  const rows = (answers.data ?? []).filter((a) => `${a.question} ${a.answer}`.toLowerCase().includes(filter.toLowerCase()));
  return (
    <section>
      <SectionHeader
        description={t("answers.hint")}
        action={
          <Button size="sm" variant="secondary" onClick={() => setEditing({ question: "", answer: "" })}>
            <Plus />
            {t("common.add")}
          </Button>
        }
      />
      <SectionBody>
        <Input aria-label={t("answers.search")} placeholder={t("answers.search")} value={filter} onChange={(e) => setFilter(e.target.value)} className="mb-3" />
        {rows.length === 0 ? (
          <EmptyState title={t("answers.empty")} description={t("answers.empty_hint")} />
        ) : (
          <ul className="divide-y divide-line border-y border-line">
            {rows.map((a) => (
              <li key={a.id} className="flex items-start gap-3 py-3">
                <div className="min-w-0 flex-1">
                  <div className="text-body font-medium">{a.question}</div>
                  <div className="mt-0.5 text-meta text-ink-2 whitespace-pre-line">{a.answer}</div>
                  <div className="mt-1 text-small text-ink-3">{formatRelative(a.updated_at, lang)}</div>
                </div>
                <Button size="icon-sm" variant="quiet" onClick={() => setEditing(a)} aria-label={t("common.edit")}>
                  <Pencil />
                </Button>
                <Button size="icon-sm" variant="quiet" onClick={() => remove.mutate(a.id)} aria-label={t("common.delete")}>
                  <Trash2 />
                </Button>
              </li>
            ))}
          </ul>
        )}
      </SectionBody>
      <Dialog open={editing !== null} onOpenChange={(v) => !v && setEditing(null)}>
        {editing && (
          <DialogContent
            title={editing.id ? t("answers.edit") : t("answers.new")}
            footer={
              <>
                <Button variant="quiet" onClick={() => setEditing(null)}>
                  {t("common.cancel")}
                </Button>
                <Button
                  variant="primary"
                  onClick={() => save.mutate(editing)}
                  loading={save.isPending}
                  disabled={!editing.question?.trim() || !editing.answer?.trim()}
                >
                  {t("common.save")}
                </Button>
              </>
            }
          >
            <div className="space-y-4">
              <Field label={t("answers.question")}>
                <Input value={editing.question ?? ""} onChange={(e) => setEditing({ ...editing, question: e.target.value })} />
              </Field>
              <Field label={t("answers.answer")}>
                <Textarea value={editing.answer ?? ""} onChange={(e) => setEditing({ ...editing, answer: e.target.value })} />
              </Field>
            </div>
          </DialogContent>
        )}
      </Dialog>
    </section>
  );
}

/* ----------------------------------------------------------------- Ausschlüsse */

export function ExclusionSettings() {
  const { t, lang } = useI18n();
  const qc = useQueryClient();
  const rows = useQuery({ queryKey: ["exclusions"], queryFn: api.exclusions });
  const [kind, setKind] = useState<Exclusion["kind"]>("company");
  const [value, setValue] = useState("");
  const add = useMutation({
    mutationFn: () => api.createExclusion(kind, value),
    onSuccess: () => {
      setValue("");
      qc.invalidateQueries({ queryKey: ["exclusions"] });
    },
  });
  const remove = useMutation({
    mutationFn: api.deleteExclusion,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["exclusions"] }),
  });
  return (
    <section>
      <SectionHeader description={t("excl.hint")} />
      <SectionBody>
        <form
          className="mb-4 flex flex-wrap gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (value.trim()) add.mutate();
          }}
        >
          <Select aria-label={t("excl.kind")} value={kind} onChange={(e) => setKind(e.target.value as Exclusion["kind"])} className="w-40">
            <option value="company">{t("excl.company")}</option>
            <option value="title">{t("excl.title_rx")}</option>
            <option value="url">{t("excl.url")}</option>
            <option value="job">{t("excl.job")}</option>
          </Select>
          <Input aria-label={t("excl.value")} value={value} onChange={(e) => setValue(e.target.value)} placeholder={t("excl.value")} className="min-w-48 flex-1" />
          <Button type="submit" variant="primary" disabled={!value.trim()} loading={add.isPending}>
            {t("common.add")}
          </Button>
        </form>
        {rows.isError ? (
          <LoadError error={rows.error} onRetry={() => rows.refetch()} />
        ) : rows.data?.length === 0 ? (
          <EmptyState title={t("excl.empty")} />
        ) : (
          <ul className="divide-y divide-line border-y border-line">
            {rows.data?.map((e) => (
              <li key={e.id} className="flex items-center gap-3 py-2.5">
                <Badge tone="outline">{t(`excl.${e.kind === "title" ? "title_rx" : e.kind}`)}</Badge>
                <span className="min-w-0 flex-1 truncate text-body">{e.value}</span>
                <span className="hidden text-small text-ink-3 sm:inline">{formatRelative(e.created_at, lang)}</span>
                <Button size="icon-sm" variant="quiet" onClick={() => remove.mutate(e.id)} aria-label={t("common.delete")}>
                  <Trash2 />
                </Button>
              </li>
            ))}
          </ul>
        )}
      </SectionBody>
    </section>
  );
}

/* ----------------------------------------------------------------- System */

export function SystemSettings() {
  const { t } = useI18n();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const sys = useQuery({ queryKey: ["system"], queryFn: () => api.system(), refetchInterval: (q) => (q.state.data?.browser_install.running ? 2000 : false) });
  const login = useMutation({
    mutationFn: api.claudeLogin,
    onSuccess: (r) => (r.opened ? toast(t("system.terminal_opened")) : toast(t("system.claude_missing"))),
  });
  const install = useMutation({ mutationFn: api.browserInstall, onSuccess: () => qc.invalidateQueries({ queryKey: ["system"] }) });
  const folder = useMutation({ mutationFn: api.openFolder });
  const refresh = useMutation({
    mutationFn: () => api.system(true),
    onSuccess: (r) => qc.setQueryData(["system"], r),
  });
  const rerun = useMutation({
    mutationFn: () => api.saveSettings({ setup_completed: false }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["status"] });
      navigate("/setup");
    },
  });
  if (!sys.data) return <Pending query={sys} className="h-80 rounded-lg" />;
  const s = sys.data;
  return (
    <div className="space-y-6">
      <section>
        <SectionHeader
          title={t("system.status")}
          action={
            <Button size="sm" variant="quiet" onClick={() => refresh.mutate()} loading={refresh.isPending}>
                            {t("system.recheck")}
            </Button>
          }
        />
        <SectionBody className="divide-y divide-line">
          <StatusLine
            ok={s.claude.ok}
            title="Claude Code"
            text={s.claude.ok ? `${s.claude.version} · ${s.claude.plan} · ${s.claude.account}` : s.claude.message}
            action={
              !s.claude.ok && (
                <Button size="sm" variant="primary" onClick={() => login.mutate()} loading={login.isPending}>
                  {t("system.claude_login")}
                </Button>
              )
            }
          />
          <StatusLine
            ok={s.browser.ok}
            title={t("system.browser")}
            text={s.browser_install.running ? s.browser_install.log.at(-1) ?? t("system.installing") : s.browser.message}
            action={
              !s.browser.ok && (
                <Button size="sm" variant="primary" onClick={() => install.mutate()} loading={s.browser_install.running}>
                  {t("system.browser_install")}
                </Button>
              )
            }
          />
          <StatusLine
            ok={s.profile.cv_ok && s.profile.missing.length === 0}
            title={t("system.profile")}
            text={
              s.profile.missing.length
                ? t("system.profile_missing", { fields: s.profile.missing.length })
                : t("system.profile_ok", { name: s.profile.name })
            }
          />
        </SectionBody>
      </section>
      <section>
        <SectionHeader title={t("system.data")} description={t("system.data_hint")} />
        <SectionBody className="flex flex-wrap items-center gap-2">
          <code className="rounded-sm bg-sunken px-1.5 py-0.5 font-mono text-small [overflow-wrap:anywhere]">{s.home}</code>
          <Button size="sm" variant="secondary" onClick={() => folder.mutate()}>
            {t("system.open_folder")}
          </Button>
          <Button size="sm" variant="secondary" asChild>
            <a href="/api/export.csv">
              {t("system.export")}
            </a>
          </Button>
          <Button size="sm" variant="quiet" onClick={() => rerun.mutate()}>
            {t("system.rerun_setup")}
          </Button>
        </SectionBody>
        <SectionBody className="text-small text-ink-3">jobslop {s.version}</SectionBody>
      </section>
    </div>
  );
}

/** Zeile für einen Prüfpunkt: grünes Zeichen = in Ordnung, Petrol = du bist dran. */
export function StatusLine({ ok, title, text, action }: { ok: boolean; title: ReactNode; text: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center gap-3 py-3">
      <StatusGlyph status={ok ? "offer" : "needs_input"} />
      <div className="min-w-0 flex-1">
        <div className="text-body font-medium">{title}</div>
        <div className="text-meta text-ink-2 [overflow-wrap:anywhere]">{text}</div>
      </div>
      {action}
    </div>
  );
}
