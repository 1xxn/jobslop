import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check } from "lucide-react";
import { type ReactNode, useEffect, useState } from "react";
import { useNavigate } from "react-router";
import { toast } from "sonner";
import { LoadError, Logo, StatusGlyph } from "@/components/domain";
import { ChipsInput, Segmented, SwitchRow } from "@/components/ui/controls";
import { Button, SectionBody, Kbd, Progress } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { type Lang, useI18n } from "@/lib/i18n";
import type { MessageKey } from "@/lib/messages";
import type { SearchConfig } from "@/lib/types";
import { cn } from "@/lib/utils";
import { DocumentsCard, ProfileForm } from "../settings/ProfileForm";
import { RolesEditor } from "../settings/SearchForm";
import { StatusLine } from "../settings/sections";

const STEPS: { id: string; title: MessageKey }[] = [
  { id: "welcome", title: "setup.step_welcome" },
  { id: "claude", title: "setup.step_claude" },
  { id: "cv", title: "setup.step_cv" },
  { id: "profile", title: "setup.step_profile" },
  { id: "search", title: "setup.step_search" },
  { id: "finish", title: "setup.step_finish" },
];

export function SetupWizard() {
  const { t } = useI18n();
  const [step, setStep] = useState(0);
  const current = STEPS[step];
  const [searchDraft, setSearchDraft] = useState<SearchConfig | null>(null);
  const qc = useQueryClient();
  const saveSearch = useMutation({
    mutationFn: (c: SearchConfig) => api.saveSearch(c),
    onSuccess: (r) => qc.setQueryData(["search"], r),
  });

  const next = async () => {
    if (current.id === "search" && searchDraft) {
      try {
        await saveSearch.mutateAsync(searchDraft);
      } catch {
        return; // die Meldung kommt als Toast (main.tsx)
      }
    }
    setStep((s) => Math.min(s + 1, STEPS.length - 1));
    window.scrollTo({ top: 0 });
  };

  return (
    <div className="min-h-dvh bg-paper">
      <div className="mx-auto grid min-h-dvh max-w-6xl lg:grid-cols-[280px_minmax(0,1fr)]">
        <aside className="hidden border-r border-line px-8 py-10 lg:block" aria-label={t("setup.steps")}>
          <Logo />
          <ol className="mt-10 grid gap-0.5">
            {STEPS.map((s, i) => (
              <li
                key={s.id}
                aria-current={i === step ? "step" : undefined}
                className={cn(
                  "flex items-center justify-between gap-2 py-1.5 pl-3 text-body",
                  i === step
                    ? "font-semibold text-ink shadow-[inset_2px_0_0_var(--accent)]"
                    : cn("shadow-[inset_2px_0_0_var(--line)]", i < step ? "text-ink-2" : "text-ink-3"),
                )}
              >
                {t(s.title)}
                {i < step && <Check className="size-3.5 text-ink-3" aria-label={t("setup.step_done")} />}
              </li>
            ))}
          </ol>
          <p className="mt-10 text-small leading-relaxed text-ink-3">{t("setup.privacy")}</p>
        </aside>

        <main className="flex min-w-0 flex-col px-5 py-8 sm:px-10 lg:py-14">
          <div className="mb-8 lg:hidden">
            <Logo />
            <Progress value={((step + 1) / STEPS.length) * 100} className="mt-5" />
          </div>
          <div key={current.id} className="flex-1 animate-slide-up">
            {current.id === "welcome" && <Welcome />}
            {current.id === "claude" && <ClaudeStep />}
            {current.id === "cv" && <CvStep />}
            {current.id === "profile" && <ProfileStep />}
            {current.id === "search" && <SearchStep draft={searchDraft} onDraft={setSearchDraft} />}
            {current.id === "finish" && <FinishStep />}
          </div>
          {current.id !== "finish" && (
            <div className="sticky bottom-0 -mx-5 mt-10 flex items-center justify-between gap-3 border-t border-line bg-paper px-5 py-3 sm:-mx-10 sm:px-10">
              <Button variant="quiet" onClick={() => setStep(step - 1)} disabled={step === 0}>
                {t("common.back")}
              </Button>
              <Button variant="primary" onClick={next} loading={saveSearch.isPending}>
                {step === 0 ? t("setup.start") : t("common.next")}
              </Button>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}

function StepTitle({ title, text }: { title: ReactNode; text?: ReactNode }) {
  return (
    <div className="mb-8">
      <h1 className="text-title font-semibold tracking-[-0.015em] text-balance sm:text-display">{title}</h1>
      {text && <p className="mt-2 max-w-prose text-read text-ink-2">{text}</p>}
    </div>
  );
}

function Welcome() {
  const { t, lang, setLang } = useI18n();
  const features: { title: MessageKey; text: MessageKey }[] = [
    { title: "setup.f_find", text: "setup.f_find_text" },
    { title: "setup.f_rank", text: "setup.f_rank_text" },
    { title: "setup.f_apply", text: "setup.f_apply_text" },
  ];
  return (
    <>
      <Segmented<Lang>
        className="mb-8"
        label={t("appearance.language")}
        value={lang}
        onChange={setLang}
        options={[
          { value: "de", label: "Deutsch" },
          { value: "en", label: "English" },
        ]}
      />
      <StepTitle title={t("setup.welcome_title")} text={t("setup.welcome_text")} />
      <dl className="max-w-2xl border-t border-line">
        {features.map((f) => (
          <div key={f.title} className="grid gap-1 border-b border-line py-3 sm:grid-cols-[12rem_minmax(0,1fr)] sm:gap-4">
            <dt className="font-semibold">{t(f.title)}</dt>
            <dd className="text-meta text-ink-2">{t(f.text)}</dd>
          </div>
        ))}
      </dl>
      <p className="mt-6 text-meta text-ink-2">{t("setup.welcome_time")}</p>
    </>
  );
}

function ClaudeStep() {
  const { t } = useI18n();
  const sys = useQuery({ queryKey: ["system", "setup"], queryFn: () => api.system(true), refetchInterval: 4000 });
  const login = useMutation({
    mutationFn: api.claudeLogin,
    onSuccess: (r) => !r.opened && toast(t("system.claude_missing")),
  });
  const install = useMutation({ mutationFn: api.claudeInstall });
  const c = sys.data?.claude;
  return (
    <>
      <StepTitle title={t("setup.claude_title")} text={t("setup.claude_text")} />
      <section>
        <SectionBody className="pt-5">
          {sys.isError ? (
            <LoadError error={sys.error} onRetry={() => sys.refetch()} />
          ) : !c ? (
            <p className="text-meta text-ink-2">{t("setup.checking")}</p>
          ) : c.ok ? (
            <StatusLine
              ok
              title={t("setup.claude_ok")}
              text={[c.account, c.plan, `Claude Code ${c.version}`].filter(Boolean).join(" · ")}
            />
          ) : !c.installed ? (
            <div className="space-y-4">
              <StatusLine ok={false} title={t("setup.claude_not_installed")} text={t("setup.claude_install_text")} />
              <pre className="overflow-x-auto rounded-md bg-sunken px-4 py-3 font-mono text-meta">
                {navigator.platform.toLowerCase().includes("win")
                  ? "irm https://claude.ai/install.ps1 | iex"
                  : "curl -fsSL https://claude.ai/install.sh | bash"}
              </pre>
              <Button variant="primary" onClick={() => install.mutate()} loading={install.isPending}>
                {t("setup.claude_install_btn")}
              </Button>
            </div>
          ) : (
            <div className="space-y-4">
              <StatusLine ok={false} title={t("setup.claude_login_needed")} text={c.message} />
              <ol className="ml-5 list-decimal space-y-1.5 text-body text-ink-2">
                <li>{t("setup.claude_login_1")}</li>
                <li>{t("setup.claude_login_2")}</li>
                <li>
                  {t("setup.claude_login_3")} <Kbd>/exit</Kbd>
                </li>
              </ol>
              <Button variant="primary" onClick={() => login.mutate()} loading={login.isPending}>
                {t("system.claude_login")}
              </Button>
            </div>
          )}
        </SectionBody>
      </section>
      <p className="mt-4 max-w-prose text-meta text-ink-2">{t("setup.claude_note")}</p>
    </>
  );
}

function CvStep() {
  const { t } = useI18n();
  const profile = useQuery({ queryKey: ["profile"], queryFn: api.profile });
  const name = profile.data?.profile.personal.first_name;
  return (
    <>
      <StepTitle title={t("setup.cv_title")} text={t("setup.cv_text")} />
      <DocumentsCard importOnUpload />
      {name && (
        <p className="mt-4 flex items-center gap-2 text-body">
          <StatusGlyph status="offer" />
          {t("setup.cv_imported", { name })}
        </p>
      )}
    </>
  );
}

function ProfileStep() {
  const { t } = useI18n();
  return (
    <>
      <StepTitle title={t("setup.profile_title")} text={t("setup.profile_text")} />
      <ProfileForm sections={["personal", "work"]} autosave />
    </>
  );
}

function SearchStep({ draft, onDraft }: { draft: SearchConfig | null; onDraft: (c: SearchConfig) => void }) {
  const { t, lang } = useI18n();
  const presets = useQuery({ queryKey: ["presets"], queryFn: api.presets });
  const profile = useQuery({ queryKey: ["profile"], queryFn: api.profile });
  const [chosen, setChosen] = useState<string[]>(["cloud"]);
  const [cities, setCities] = useState<string[]>([]);
  const [remote, setRemote] = useState(true);
  const [leadership, setLeadership] = useState(true);
  useEffect(() => {
    const city = profile.data?.profile.personal.city;
    if (city && cities.length === 0) setCities([city]); // nur beim ersten Laden vorbelegen
  }, [profile.data]);
  const preview = useMutation({ mutationFn: api.presetPreview, onSuccess: onDraft });
  useEffect(() => {
    if (chosen.length) preview.mutate({ presets: chosen, cities: cities.length ? cities : ["berlin"], remote, exclude_leadership: leadership });
  }, [chosen.join(","), cities.join(","), remote, leadership]); // Vorschau neu berechnen, wenn sich die Auswahl ändert
  return (
    <>
      <StepTitle title={t("setup.search_title")} text={t("setup.search_text")} />
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {presets.data?.map((p) => {
          const on = chosen.includes(p.id);
          return (
            <button
              key={p.id}
              type="button"
              onClick={() => setChosen(on ? chosen.filter((x) => x !== p.id) : [...chosen, p.id])}
              aria-pressed={on}
              className={cn(
                "rounded-md border p-3 text-left transition-colors duration-[120ms]",
                on ? "border-accent bg-accent-soft" : "border-line-input hover:bg-sunken",
              )}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-body font-semibold">{p.label[lang]}</span>
                {on && <Check className="size-4 shrink-0 text-accent" aria-hidden />}
              </div>
              <div className="mt-1 line-clamp-2 text-meta text-ink-2">{p.roles.map((r) => r.name).join(" · ")}</div>
            </button>
          );
        })}
      </div>
      <section className="mt-6">
        <SectionBody className="space-y-4 pt-5">
          <div>
            <div className="mb-1.5 text-meta font-medium">{t("setup.cities")}</div>
            <ChipsInput value={cities} onChange={setCities} placeholder="Berlin, Hamburg, …" />
          </div>
          <div className="divide-y divide-line">
            <SwitchRow title={t("search.remote")} description={t("search.remote_hint")} checked={remote} onCheckedChange={setRemote} />
            <SwitchRow title={t("setup.no_leadership")} description={t("setup.no_leadership_hint")} checked={leadership} onCheckedChange={setLeadership} />
          </div>
        </SectionBody>
      </section>
      {draft && (
        <div className="mt-6">
          <RolesEditor config={draft} onChange={onDraft} />
        </div>
      )}
    </>
  );
}

function FinishStep() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const sys = useQuery({
    queryKey: ["system", "finish"],
    queryFn: () => api.system(true),
    refetchInterval: (q) => (q.state.data?.browser_install.running ? 2000 : false),
  });
  const install = useMutation({ mutationFn: api.browserInstall, onSuccess: () => qc.invalidateQueries({ queryKey: ["system", "finish"] }) });
  const done = useMutation({
    mutationFn: () => api.completeSetup(true),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ["status"] });
      toast.success(t("setup.done_toast"));
      navigate("/");
    },
  });
  const s = sys.data;
  return (
    <>
      <StepTitle title={t("setup.finish_title")} text={t("setup.finish_text")} />
      <section>
        <SectionBody className="divide-y divide-line pt-2">
          <StatusLine
            ok={!!s?.claude.ok}
            title="Claude Code"
            text={s?.claude.ok ? t("setup.claude_ok") : t("setup.claude_skip")}
          />
          <StatusLine
            ok={!!s?.profile.cv_ok}
            title={t("profile.cv")}
            text={s?.profile.cv_ok ? s.profile.cv.split(/[\\/]/).pop() : t("setup.cv_missing")}
          />
          <StatusLine
            ok={!!s?.browser.ok}
            title={t("system.browser")}
            text={s?.browser_install.running ? s.browser_install.log.at(-1) ?? t("system.installing") : s?.browser.message ?? "…"}
            action={
              s && !s.browser.ok && (
                <Button size="sm" variant="primary" onClick={() => install.mutate()} loading={s.browser_install.running}>
                  {t("system.browser_install")}
                </Button>
              )
            }
          />
        </SectionBody>
      </section>
      <div className="mt-8 flex flex-wrap gap-3">
        <Button variant="primary" onClick={() => done.mutate()} loading={done.isPending}>
          {t("setup.finish_btn")}
        </Button>
      </div>
      <p className="mt-3 text-meta text-ink-2">{t("setup.finish_hint")}</p>
    </>
  );
}
