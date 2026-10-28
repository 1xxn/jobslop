import { ArrowLeft, ChevronRight } from "lucide-react";
import type { ReactNode } from "react";
import { Link, NavLink, Navigate, useParams } from "react-router";
import { PageHeader } from "@/components/domain";
import { useMediaQuery } from "@/lib/hooks";
import { useI18n } from "@/lib/i18n";
import type { MessageKey } from "@/lib/messages";
import { cn } from "@/lib/utils";
import { LogSettings } from "./Log";
import { ProfileForm } from "./ProfileForm";
import { SearchForm } from "./SearchForm";
import {
  AnswersSettings,
  ApplySettings,
  AutopilotSettings,
  ExclusionSettings,
  ExtensionSettings,
  InboxSettings,
  NotificationSettings,
  SystemSettings,
} from "./sections";

type Tab = { id: string; label: MessageKey; render: () => ReactNode };

// Gruppen statt acht gleichrangiger Reiter: das bin ich · das suche ich · so bewirbt es sich · Technik
const GROUPS: { label: MessageKey; tabs: Tab[] }[] = [
  {
    label: "settings.group_you",
    tabs: [
      { id: "profile", label: "settings.profile", render: () => <ProfileForm /> },
      { id: "answers", label: "settings.answers", render: () => <AnswersSettings /> },
    ],
  },
  {
    label: "settings.group_search",
    tabs: [
      { id: "search", label: "settings.search", render: () => <SearchForm part="roles" /> },
      { id: "sources", label: "settings.sources", render: () => <SearchForm part="sources" /> },
      { id: "exclusions", label: "settings.exclusions", render: () => <ExclusionSettings /> },
    ],
  },
  {
    label: "settings.group_apply",
    tabs: [
      { id: "apply", label: "settings.apply", render: () => <ApplySettings /> },
      { id: "limits", label: "settings.limits", render: () => <SearchForm part="limits" /> },
      { id: "autopilot", label: "settings.autopilot", render: () => <AutopilotSettings /> },
      { id: "extension", label: "settings.extension", render: () => <ExtensionSettings /> },
      { id: "inbox", label: "settings.inbox", render: () => <InboxSettings /> },
      { id: "notifications", label: "settings.notifications", render: () => <NotificationSettings /> },
    ],
  },
  {
    label: "settings.group_system",
    tabs: [
      { id: "system", label: "settings.system", render: () => <SystemSettings /> },
      { id: "log", label: "settings.log", render: () => <LogSettings /> },
    ],
  },
];
const TABS = GROUPS.flatMap((g) => g.tabs);

/** Einstellungen: breit Navigation links und Inhalt rechts, schmal erst die Liste, dann die Seite mit Zurück-Link. */
export function SettingsPage() {
  const { t } = useI18n();
  const { tab } = useParams();
  const wide = useMediaQuery("(min-width: 1024px)");
  const current = TABS.find((x) => x.id === tab);
  if (tab && !current) return <Navigate to="/settings" replace />;

  if (!wide && !current) {
    return (
      <>
        <PageHeader title={t("nav.settings")} />
        <SettingsNav list />
      </>
    );
  }
  const shown = current ?? TABS[0];
  // Die Seite trägt ihren eigenen Namen als Überschrift („Profil“), „Einstellungen“ steht als Weg darüber
  return (
    <div className="grid gap-10 lg:grid-cols-[12rem_minmax(0,1fr)]">
      {wide && <SettingsNav current={shown.id} />}
      <div key={shown.id} className="min-w-0 max-w-3xl animate-fade-in">
        {wide ? (
          <p className="text-small text-ink-3">{t("nav.settings")}</p>
        ) : (
          <Link to="/settings" className="mb-2 inline-flex items-center gap-1 text-meta font-medium text-ink-2 hover:text-ink">
            <ArrowLeft className="size-4" aria-hidden />
            {t("nav.settings")}
          </Link>
        )}
        <PageHeader title={t(shown.label)} />
        {shown.render()}
      </div>
    </div>
  );
}

function SettingsNav({ current, list }: { current?: string; list?: boolean }) {
  const { t } = useI18n();
  return (
    <nav aria-label={t("nav.settings")} className={cn("grid content-start gap-5", !list && "sticky top-6 pt-5")}>
      {GROUPS.map((g) => (
        <div key={g.label} className="grid gap-0.5">
          <h3 className={cn("px-2.5 pb-1 text-small font-medium text-ink-3", list && "border-b border-line px-0")}>{t(g.label)}</h3>
          {g.tabs.map((x) =>
            list ? (
              <Link
                key={x.id}
                to={`/settings/${x.id}`}
                className="flex items-center justify-between border-b border-line py-3 text-body font-medium"
              >
                {t(x.label)}
                <ChevronRight className="size-4 text-ink-3" aria-hidden />
              </Link>
            ) : (
              <NavLink
                key={x.id}
                to={`/settings/${x.id}`}
                aria-current={current === x.id ? "page" : undefined}
                className={cn(
                  "rounded-md px-2.5 py-1.5 text-body transition-colors duration-[120ms]",
                  current === x.id ? "bg-sunken font-medium text-ink" : "text-ink-2 hover:bg-sunken hover:text-ink",
                )}
              >
                {t(x.label)}
              </NavLink>
            ),
          )}
        </div>
      ))}
    </nav>
  );
}
