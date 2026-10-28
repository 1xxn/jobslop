import { Briefcase, Inbox, ListChecks, Settings, SunMoon } from "lucide-react";
import { type ReactNode, Suspense, useState } from "react";
import { Link, NavLink, Outlet, useNavigate } from "react-router";
import { useHotkeys } from "@/lib/hotkeys";
import { useDesktopNotifications, useStatus, useTheme, type Theme } from "@/lib/hooks";
import { type Lang, useI18n } from "@/lib/i18n";
import type { MessageKey } from "@/lib/messages";
import type { Status } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Logo, StatusGlyph } from "../domain";
import { Dialog, DialogContent, Menu, MenuContent, MenuItem, MenuLabel, MenuRadioGroup, MenuRadioItem, MenuSeparator, MenuTrigger } from "../ui/overlays";
import { Count, Kbd, Skeleton } from "../ui/primitives";
import { RunDrawerProvider, RunStatusButton, runSummary } from "./run";
import { useRunDrawer } from "./runContext";

type NavItem = { to: string; label: MessageKey; icon: ReactNode; end?: boolean; key: string };

// Drei Arbeitsbereiche, Einstellungen abgesetzt. Die Buchstaben sind die Ziele für „G dann …“.
const WORK: NavItem[] = [
  { to: "/", label: "nav.today", icon: <Inbox />, end: true, key: "today" },
  { to: "/jobs", label: "nav.jobs", icon: <Briefcase />, key: "jobs" },
  { to: "/applications", label: "nav.applications", icon: <ListChecks />, key: "applications" },
];
const SETTINGS: NavItem = { to: "/settings", label: "nav.settings", icon: <Settings />, key: "settings" };

const GO_KEYS: Record<Lang, Record<string, string>> = {
  de: { today: "h", jobs: "s", applications: "b", settings: "e" },
  en: { today: "t", jobs: "j", applications: "a", settings: "s" },
};

export function AppShell() {
  const { t, lang } = useI18n();
  const { data: status } = useStatus();
  const navigate = useNavigate();
  const [help, setHelp] = useState(false);
  useDesktopNotifications(status, { prompt: t("notify.prompt"), done: t("notify.done") });
  // Heute zählt, was auf dich wartet (Rückfragen, Freigaben, fälliges Nachfassen); Stellen, was zu sichten ist
  const waiting =
    (status?.prompts.length ?? 0) + (status?.counts.replies ?? 0) + (status?.counts.follow_ups_due ?? 0);
  const toReview = status?.counts.to_review ?? 0;

  const go = GO_KEYS[lang];
  useHotkeys({
    [`g ${go.today}`]: () => navigate("/"),
    [`g ${go.jobs}`]: () => navigate("/jobs"),
    [`g ${go.applications}`]: () => navigate("/applications"),
    [`g ${go.settings}`]: () => navigate("/settings"),
    "?": () => setHelp(true),
  });

  return (
    <RunDrawerProvider status={status}>
      <div className="min-h-dvh lg:pl-[208px]">
        <a
          href="#main"
          className="sr-only z-50 rounded-md bg-accent px-3 py-2 text-body font-medium text-on-accent focus:not-sr-only focus:fixed focus:top-3 focus:left-3"
        >
          {t("nav.skip")}
        </a>
        <Sidebar status={status} waiting={waiting} toReview={toReview} onHelp={() => setHelp(true)} />
        <MobileTop status={status} onHelp={() => setHelp(true)} />
        {status?.demo && (
          <div className="border-b border-line bg-sunken px-4 py-1.5 text-small text-ink-2 sm:px-6 lg:px-8">
            {t("shell.demo")}
          </div>
        )}
        <main
          id="main"
          tabIndex={-1}
          className="mx-auto w-full max-w-[1200px] px-4 pt-5 pb-28 focus:outline-none sm:px-6 lg:px-8 lg:pt-7 lg:pb-12"
        >
          <Suspense fallback={<PageSkeleton />}>
            <Outlet />
          </Suspense>
        </main>
        <MobileNav waiting={waiting} />
        <ShortcutsDialog open={help} onOpenChange={setHelp} />
      </div>
    </RunDrawerProvider>
  );
}

function PageSkeleton() {
  return (
    <div className="space-y-5" aria-busy="true">
      <Skeleton className="h-6 w-48" />
      <div className="space-y-3">
        {Array.from({ length: 5 }, (_, i) => (
          <div key={i} className="space-y-1.5">
            <Skeleton className="h-3.5 w-2/3" />
            <Skeleton className="h-3 w-1/3" />
          </div>
        ))}
      </div>
    </div>
  );
}

function NavRow({ item, count }: { item: NavItem; count?: ReactNode }) {
  const { t } = useI18n();
  return (
    <NavLink
      to={item.to}
      end={item.end}
      className={({ isActive }) =>
        cn(
          "flex items-center justify-between gap-2 rounded-md px-2.5 py-1.5 text-body font-medium transition-colors duration-[120ms]",
          isActive ? "bg-sunken text-ink" : "text-ink-2 hover:bg-sunken hover:text-ink",
        )
      }
    >
      {t(item.label)}
      {count}
    </NavLink>
  );
}

function Sidebar({
  status,
  waiting,
  toReview,
  onHelp,
}: {
  status: Status | undefined;
  waiting: number;
  toReview: number;
  onHelp: () => void;
}) {
  const { t } = useI18n();
  return (
    <aside className="fixed inset-y-0 left-0 z-30 hidden w-[208px] flex-col border-r border-line bg-paper px-2 py-4 lg:flex">
      <Link to="/" className="mb-5 self-start rounded-md px-2.5 py-1">
        <Logo />
      </Link>
      <nav className="flex flex-1 flex-col gap-0.5" aria-label={t("nav.main")}>
        {WORK.map((item) => (
          <NavRow
            key={item.to}
            item={item}
            count={
              item.key === "today" ? <Count n={waiting} you /> : item.key === "jobs" ? <Count n={toReview} /> : null
            }
          />
        ))}
        <div className="flex-1" />
        <NavRow item={SETTINGS} />
      </nav>
      <div className="mt-2 border-t border-line pt-2">
        <RunStatusButton status={status} />
        <AppearanceMenu onHelp={onHelp} />
      </div>
    </aside>
  );
}

/** Sprache und Farbschema – einmal einstellen, selten ändern. */
function AppearanceMenu({ onHelp, compact }: { onHelp: () => void; compact?: boolean }) {
  const { t, lang, setLang } = useI18n();
  const [theme, setTheme] = useTheme();
  return (
    <Menu>
      <MenuTrigger
        aria-label={t("appearance.title")}
        className={cn(
          "flex items-center gap-2 rounded-md text-small text-ink-3 transition-colors hover:bg-sunken hover:text-ink",
          compact ? "size-9 justify-center [&_svg]:size-[18px]" : "w-full px-2.5 py-1.5",
        )}
      >
        <SunMoon className="size-3.5 shrink-0" aria-hidden />
        {!compact && (
          <span>
            {lang === "de" ? "Deutsch" : "English"} · {t(`theme.${theme}`)}
          </span>
        )}
      </MenuTrigger>
      <MenuContent align={compact ? "end" : "start"} side={compact ? "bottom" : "top"}>
        <MenuLabel>{t("appearance.language")}</MenuLabel>
        <MenuRadioGroup value={lang} onValueChange={(v) => setLang(v as Lang)}>
          <MenuRadioItem value="de">Deutsch</MenuRadioItem>
          <MenuRadioItem value="en">English</MenuRadioItem>
        </MenuRadioGroup>
        <MenuSeparator />
        <MenuLabel>{t("appearance.theme")}</MenuLabel>
        <MenuRadioGroup value={theme} onValueChange={(v) => setTheme(v as Theme)}>
          <MenuRadioItem value="system">{t("theme.system")}</MenuRadioItem>
          <MenuRadioItem value="light">{t("theme.light")}</MenuRadioItem>
          <MenuRadioItem value="dark">{t("theme.dark")}</MenuRadioItem>
        </MenuRadioGroup>
        <MenuSeparator />
        <MenuItem onSelect={onHelp}>
          {t("shortcuts.title")}
          <Kbd className="ml-auto">?</Kbd>
        </MenuItem>
      </MenuContent>
    </Menu>
  );
}

function MobileTop({ status, onHelp }: { status: Status | undefined; onHelp: () => void }) {
  const { t, lang } = useI18n();
  const { open } = useRunDrawer();
  const s = runSummary(status, t, lang);
  return (
    <header className="sticky top-0 z-30 flex items-center justify-between gap-2 border-b border-line bg-paper px-4 py-1.5 lg:hidden">
      <Link to="/" className="rounded-md py-1">
        <Logo />
      </Link>
      <div className="flex items-center gap-1">
        <button
          type="button"
          onClick={open}
          aria-label={`${t("run.open")}: ${s.now ?? s.autopilot}`}
          className="flex h-9 items-center gap-2 rounded-md px-2.5 text-small text-ink-2 hover:bg-sunken"
        >
          <StatusGlyph
            status={s.busy ? "running" : status?.autopilot.enabled ? "queued" : "skipped"}
            className={cn(s.busy && "animate-pulse-slow")}
          />
          <span className="max-w-[40vw] truncate">{s.now ?? s.autopilot}</span>
        </button>
        <AppearanceMenu onHelp={onHelp} compact />
      </div>
    </header>
  );
}

function MobileNav({ waiting }: { waiting: number }) {
  const { t } = useI18n();
  return (
    <nav
      className="safe-bottom fixed inset-x-0 bottom-0 z-30 grid grid-cols-4 border-t border-line bg-paper lg:hidden"
      aria-label={t("nav.main")}
    >
      {[...WORK, SETTINGS].map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.end}
          className={({ isActive }) =>
            cn(
              "relative flex min-h-12 flex-col items-center justify-center gap-0.5 pt-1.5 pb-1 text-[0.6875rem] leading-3.5 [&_svg]:size-5",
              isActive ? "font-semibold text-ink" : "text-ink-3",
            )
          }
        >
          {item.icon}
          {t(item.label)}
          {item.key === "today" && waiting > 0 && (
            <span className="tabular absolute top-1 left-1/2 ml-2 grid h-4 min-w-4 place-items-center rounded-full bg-accent px-1 text-[0.625rem] font-bold text-on-accent">
              {waiting}
            </span>
          )}
        </NavLink>
      ))}
    </nav>
  );
}

function ShortcutsDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const { t, lang } = useI18n();
  const go = GO_KEYS[lang];
  const rows: [ReactNode, string][] = [
    ...[...WORK, SETTINGS].map(
      (item) =>
        [
          <>
            <Kbd>G</Kbd> <span className="text-ink-3">{t("shortcuts.then")}</span> <Kbd>{go[item.key].toUpperCase()}</Kbd>
          </>,
          t(item.label),
        ] as [ReactNode, string],
    ),
    [<Kbd key="q">?</Kbd>, t("shortcuts.help")],
    [<Kbd key="esc">Esc</Kbd>, t("shortcuts.close")],
  ];
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title={t("shortcuts.title")}>
        <h3 className="mb-1 text-small font-medium text-ink-3">{t("shortcuts.global")}</h3>
        <dl className="divide-y divide-line border-y border-line">
          {rows.map(([keys, label], i) => (
            <div key={i} className="flex items-center justify-between gap-4 py-2">
              <dt className="text-body">{label}</dt>
              <dd className="flex items-center gap-1">{keys}</dd>
            </div>
          ))}
        </dl>
      </DialogContent>
    </Dialog>
  );
}
