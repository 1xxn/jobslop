import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  ArrowRight,
  Bot,
  Check,
  CircleAlert,
  CircleCheck,
  Download,
  FileText,
  Globe,
  LogIn,
  MapPin,
  Rocket,
  Search,
  ShieldCheck,
  Sparkles,
  TerminalSquare,
  UserRound,
} from "lucide-react";
import { type ReactNode, useEffect, useState } from "react";
import { useNavigate } from "react-router";
import { toast } from "sonner";
import { Logo } from "@/components/domain";
import { ChipsInput, Segmented, SwitchRow } from "@/components/ui/controls";
import { Badge, Button, Card, CardBody, Kbd, Progress } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { type Lang, useI18n } from "@/lib/i18n";
import type { MessageKey } from "@/lib/messages";
import type { SearchConfig } from "@/lib/types";
import { cn } from "@/lib/utils";
import { DocumentsCard, ProfileForm } from "../settings/ProfileForm";
import { RolesEditor } from "../settings/SearchForm";
import { StatusLine } from "../settings/sections";

const STEPS: { id: string; title: MessageKey; icon: ReactNode }[] = [
  { id: "welcome", title: "setup.step_welcome", icon: <Sparkles /> },
  { id: "claude", title: "setup.step_claude", icon: <Bot /> },
  { id: "cv", title: "setup.step_cv", icon: <FileText /> },
  { id: "profile", title: "setup.step_profile", icon: <UserRound /> },
  { id: "search", title: "setup.step_search", icon: <Search /> },
  { id: "finish", title: "setup.step_finish", icon: <Rocket /> },
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
      } catch (e) {
        toast.error((e as Error).message);
        return;
      }
    }
    setStep((s) => Math.min(s + 1, STEPS.length - 1));
    window.scrollTo({ top: 0 });
  };

  return (
    <div className="min-h-dvh bg-bg">
      <div className="mx-auto grid min-h-dvh max-w-6xl lg:grid-cols-[280px_minmax(0,1fr)]">
        <aside className="hidden border-r border-border px-8 py-10 lg:block">
          <Logo />
          <ol className="mt-12 space-y-1">
            {STEPS.map((s, i) => (
              <li
                key={s.id}
                className={cn(
                  "flex items-center gap-3 rounded-md px-3 py-2 text-[0.875rem] font-medium",
                  i === step ? "bg-primary-soft text-primary" : i < step ? "text-fg" : "text-fg-subtle",
                )}
              >
                <span
                  className={cn(
                    "grid size-6 shrink-0 place-items-center rounded-full text-caption [&_svg]:size-3.5",
                    i < step ? "bg-success text-white" : i === step ? "bg-primary text-primary-fg" : "bg-surface-3 text-fg-subtle",
                  )}
                >
                  {i < step ? <Check strokeWidth={3} /> : i + 1}
                </span>
                {t(s.title)}
              </li>
            ))}
          </ol>
          <p className="mt-10 text-caption leading-relaxed text-fg-subtle">{t("setup.privacy")}</p>
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
            <div className="sticky bottom-0 -mx-5 mt-10 flex items-center justify-between gap-3 border-t border-border bg-bg/90 px-5 py-4 backdrop-blur-xl sm:-mx-10 sm:px-10">
              <Button variant="ghost" onClick={() => setStep(step - 1)} disabled={step === 0}>
                <ArrowLeft />
                {t("common.back")}
              </Button>
              <Button variant="primary" size="lg" onClick={next} loading={saveSearch.isPending}>
                {step === 0 ? t("setup.start") : t("common.next")}
                <ArrowRight />
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
      <h1 className="text-title1 font-bold tracking-[-0.025em] text-balance sm:text-large">{title}</h1>
      {text && <p className="mt-3 max-w-2xl text-headline font-normal leading-relaxed text-fg-muted">{text}</p>}
    </div>
  );
}

function Welcome() {
  const { t, lang, setLang } = useI18n();
  const features: { icon: ReactNode; title: MessageKey; text: MessageKey }[] = [
    { icon: <Search />, title: "setup.f_find", text: "setup.f_find_text" },
    { icon: <Sparkles />, title: "setup.f_rank", text: "setup.f_rank_text" },
    { icon: <ShieldCheck />, title: "setup.f_apply", text: "setup.f_apply_text" },
  ];
  return (
    <>
      <Segmented<Lang>
        size="sm"
        className="mb-8"
        value={lang}
        onChange={setLang}
        options={[
          { value: "de", label: "Deutsch", icon: <Globe /> },
          { value: "en", label: "English" },
        ]}
      />
      <StepTitle title={t("setup.welcome_title")} text={t("setup.welcome_text")} />
      <div className="grid gap-3 md:grid-cols-3">
        {features.map((f) => (
          <Card key={f.title} className="p-5">
            <span className="grid size-10 place-items-center rounded-lg bg-primary-soft text-primary [&_svg]:size-5">{f.icon}</span>
            <h3 className="mt-4 text-headline font-semibold">{t(f.title)}</h3>
            <p className="mt-1 text-footnote leading-relaxed text-fg-muted">{t(f.text)}</p>
          </Card>
        ))}
      </div>
      <p className="mt-6 text-footnote text-fg-muted">{t("setup.welcome_time")}</p>
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
      <Card>
        <CardBody className="pt-5">
          {!c ? (
            <p className="text-footnote text-fg-muted">{t("setup.checking")}</p>
          ) : c.ok ? (
            <div className="flex items-center gap-4">
              <span className="grid size-12 place-items-center rounded-full bg-success-soft text-success">
                <CircleCheck className="size-6" />
              </span>
              <div>
                <div className="text-headline font-semibold">{t("setup.claude_ok")}</div>
                <div className="text-footnote text-fg-muted">
                  {c.account} {c.plan && <Badge tone="primary">{c.plan}</Badge>} · Claude Code {c.version}
                </div>
              </div>
            </div>
          ) : !c.installed ? (
            <div className="space-y-4">
              <StatusLine ok={false} title={t("setup.claude_not_installed")} text={t("setup.claude_install_text")} />
              <pre className="overflow-x-auto rounded-md bg-surface-2 px-4 py-3 font-mono text-footnote">
                {navigator.platform.toLowerCase().includes("win")
                  ? "irm https://claude.ai/install.ps1 | iex"
                  : "curl -fsSL https://claude.ai/install.sh | bash"}
              </pre>
              <Button variant="primary" onClick={() => install.mutate()} loading={install.isPending}>
                <TerminalSquare />
                {t("setup.claude_install_btn")}
              </Button>
            </div>
          ) : (
            <div className="space-y-4">
              <StatusLine ok={false} title={t("setup.claude_login_needed")} text={c.message} />
              <ol className="ml-5 list-decimal space-y-1.5 text-[0.875rem] text-fg-muted">
                <li>{t("setup.claude_login_1")}</li>
                <li>{t("setup.claude_login_2")}</li>
                <li>
                  {t("setup.claude_login_3")} <Kbd>/exit</Kbd>
                </li>
              </ol>
              <Button variant="primary" onClick={() => login.mutate()} loading={login.isPending}>
                <LogIn />
                {t("system.claude_login")}
              </Button>
            </div>
          )}
        </CardBody>
      </Card>
      <p className="mt-4 flex items-start gap-2 text-footnote text-fg-muted">
        <CircleAlert className="mt-0.5 size-4 shrink-0" />
        {t("setup.claude_note")}
      </p>
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
        <p className="mt-4 flex items-center gap-2 text-[0.875rem] text-success">
          <CircleCheck className="size-4" />
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
                "rounded-lg border p-4 text-left transition-all",
                on ? "border-primary bg-primary-soft ring-1 ring-primary" : "border-border bg-surface hover:bg-surface-2",
              )}
            >
              <div className="flex items-center justify-between">
                <span className="text-[0.9375rem] font-semibold">{p.label[lang]}</span>
                {on && <CircleCheck className="size-5 text-primary" />}
              </div>
              <div className="mt-1 line-clamp-2 text-footnote text-fg-muted">{p.roles.map((r) => r.name).join(" · ")}</div>
            </button>
          );
        })}
      </div>
      <Card className="mt-6">
        <CardBody className="space-y-4 pt-5">
          <div>
            <div className="mb-1.5 flex items-center gap-2 text-footnote font-medium">
              <MapPin className="size-4 text-fg-muted" />
              {t("setup.cities")}
            </div>
            <ChipsInput value={cities} onChange={setCities} placeholder="Berlin, Hamburg, …" />
          </div>
          <div className="divide-y divide-border">
            <SwitchRow title={t("search.remote")} description={t("search.remote_hint")} checked={remote} onCheckedChange={setRemote} />
            <SwitchRow title={t("setup.no_leadership")} description={t("setup.no_leadership_hint")} checked={leadership} onCheckedChange={setLeadership} />
          </div>
        </CardBody>
      </Card>
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
    onError: (e: Error) => toast.error(e.message),
  });
  const s = sys.data;
  return (
    <>
      <StepTitle title={t("setup.finish_title")} text={t("setup.finish_text")} />
      <Card>
        <CardBody className="divide-y divide-border pt-2">
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
                  <Download />
                  {t("system.browser_install")}
                </Button>
              )
            }
          />
        </CardBody>
      </Card>
      <div className="mt-8 flex flex-wrap gap-3">
        <Button variant="primary" size="lg" onClick={() => done.mutate()} loading={done.isPending}>
          <Rocket />
          {t("setup.finish_btn")}
        </Button>
      </div>
      <p className="mt-3 text-footnote text-fg-muted">{t("setup.finish_hint")}</p>
    </>
  );
}
