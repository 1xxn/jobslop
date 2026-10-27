import {
  Activity,
  BellRing,
  Briefcase,
  FlaskConical,
  LayoutDashboard,
  ListChecks,
  Monitor,
  Moon,
  Settings,
  SquareKanban,
  Sun,
} from "lucide-react";
import { type ReactNode, Suspense } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router";
import { useDesktopNotifications, useStatus, useTheme, type Theme } from "@/lib/hooks";
import { type Lang, useI18n } from "@/lib/i18n";
import type { MessageKey } from "@/lib/messages";
import { cn } from "@/lib/utils";
import { Logo } from "../domain";
import { Segmented } from "../ui/controls";
import { Skeleton } from "../ui/primitives";

const NAV: { to: string; label: MessageKey; icon: ReactNode; end?: boolean }[] = [
  { to: "/", label: "nav.overview", icon: <LayoutDashboard />, end: true },
  { to: "/jobs", label: "nav.jobs", icon: <Briefcase /> },
  { to: "/pipeline", label: "nav.pipeline", icon: <SquareKanban /> },
  { to: "/applications", label: "nav.applications", icon: <ListChecks /> },
  { to: "/activity", label: "nav.activity", icon: <Activity /> },
  { to: "/settings", label: "nav.settings", icon: <Settings /> },
];

export function AppShell() {
  const { t } = useI18n();
  const { data: status } = useStatus();
  const location = useLocation();
  useDesktopNotifications(status, { prompt: t("notify.prompt"), done: t("notify.done") });
  const waiting = status?.prompts.length ?? 0;

  return (
    <div className="min-h-dvh lg:pl-[248px]">
      <Sidebar badge={waiting} runnerActive={!!status?.runner.active} crawlActive={!!status?.crawl.running} />
      <main className="mx-auto w-full max-w-[1240px] px-4 pt-5 pb-28 sm:px-6 lg:px-10 lg:pt-10 lg:pb-12">
        <div className="mb-5 flex items-center justify-between lg:hidden">
          <Logo />
        </div>
        {status?.demo && (
          <div className="mb-6 flex items-center gap-3 rounded-lg border border-border bg-surface-2 px-4 py-3 text-[0.875rem]">
            <FlaskConical className="size-4 shrink-0 text-fg-muted" />
            <span className="font-medium">{t("shell.demo")}</span>
          </div>
        )}
        {waiting > 0 && location.pathname !== "/" && (
          <Link
            to="/"
            className="mb-6 flex items-center gap-3 rounded-lg border border-warning/40 bg-warning-soft px-4 py-3 text-[0.875rem] animate-slide-up hover:brightness-[0.98]"
          >
            <BellRing className="size-4 shrink-0 text-warning" />
            <span className="font-medium">{t("shell.waiting", { n: waiting })}</span>
            <span className="ml-auto text-footnote font-medium text-primary">{t("shell.open")}</span>
          </Link>
        )}
        <Suspense fallback={<PageSkeleton />}>
          <Outlet />
        </Suspense>
      </main>
      <MobileNav badge={waiting} />
    </div>
  );
}

function PageSkeleton() {
  return (
    <div className="space-y-4" aria-busy="true">
      <Skeleton className="h-9 w-64 rounded-lg" />
      <Skeleton className="h-40 rounded-lg" />
      <Skeleton className="h-64 rounded-lg" />
    </div>
  );
}

function Sidebar({ badge, runnerActive, crawlActive }: { badge: number; runnerActive: boolean; crawlActive: boolean }) {
  const { t, lang, setLang } = useI18n();
  const [theme, setTheme] = useTheme();
  return (
    <aside className="glass fixed inset-y-0 left-0 z-30 hidden w-[248px] flex-col border-r border-border px-3 py-5 lg:flex">
      <Link to="/" className="mb-7 px-3">
        <Logo />
      </Link>
      <nav className="flex flex-col gap-0.5" aria-label={t("nav.main")}>
        {NAV.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) =>
              cn(
                "group flex items-center gap-3 rounded-md px-3 py-2 text-[0.875rem] font-medium transition-colors [&_svg]:size-[18px]",
                isActive ? "bg-primary-soft text-primary" : "text-fg-muted hover:bg-surface-2 hover:text-fg",
              )
            }
          >
            {item.icon}
            <span className="flex-1">{t(item.label)}</span>
            {item.to === "/" && badge > 0 && (
              <span className="tabular grid min-w-5 place-items-center rounded-full bg-warning px-1.5 text-caption font-semibold text-white">
                {badge}
              </span>
            )}
            {item.to === "/activity" && (runnerActive || crawlActive) && (
              <span className="size-2 animate-pulse rounded-full bg-success" aria-label={t("shell.busy")} />
            )}
          </NavLink>
        ))}
      </nav>
      <div className="mt-auto space-y-3 px-1">
        <Segmented<Theme>
          size="sm"
          className="w-full [&>*]:flex-1 [&>*]:justify-center"
          value={theme}
          onChange={setTheme}
          options={[
            { value: "light", label: <span className="sr-only">{t("theme.light")}</span>, icon: <Sun /> },
            { value: "system", label: <span className="sr-only">{t("theme.system")}</span>, icon: <Monitor /> },
            { value: "dark", label: <span className="sr-only">{t("theme.dark")}</span>, icon: <Moon /> },
          ]}
        />
        <Segmented<Lang>
          size="sm"
          className="w-full [&>*]:flex-1 [&>*]:justify-center"
          value={lang}
          onChange={setLang}
          options={[
            { value: "de", label: "Deutsch" },
            { value: "en", label: "English" },
          ]}
        />
      </div>
    </aside>
  );
}

function MobileNav({ badge }: { badge: number }) {
  const { t } = useI18n();
  const items = NAV.filter((i) => i.to !== "/activity");
  return (
    <nav
      className="glass safe-bottom fixed inset-x-0 bottom-0 z-30 flex border-t border-border lg:hidden"
      aria-label={t("nav.main")}
    >
      {items.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.end}
          className={({ isActive }) =>
            cn(
              "relative flex flex-1 flex-col items-center gap-1 pt-2 pb-1.5 text-[0.625rem] font-medium [&_svg]:size-[22px]",
              isActive ? "text-primary" : "text-fg-subtle",
            )
          }
        >
          {item.icon}
          {t(item.label)}
          {item.to === "/" && badge > 0 && (
            <span className="absolute top-1 left-1/2 ml-2 size-2 rounded-full bg-warning" aria-hidden />
          )}
        </NavLink>
      ))}
    </nav>
  );
}
