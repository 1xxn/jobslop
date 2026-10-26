import { Ban, BellRing, Bot, Cpu, MessageSquareText, Play, Search, UserRound } from "lucide-react";
import type { ReactNode } from "react";
import { NavLink, useParams } from "react-router";
import { PageHeader } from "@/components/domain";
import { useI18n } from "@/lib/i18n";
import type { MessageKey } from "@/lib/messages";
import { cn } from "@/lib/utils";
import { ProfileForm } from "./ProfileForm";
import { SearchForm } from "./SearchForm";
import {
  AnswersSettings,
  ApplySettings,
  AutopilotSettings,
  ExclusionSettings,
  NotificationSettings,
  SystemSettings,
} from "./sections";

const TABS: { id: string; label: MessageKey; icon: ReactNode; render: () => ReactNode }[] = [
  { id: "profile", label: "settings.profile", icon: <UserRound />, render: () => <ProfileForm /> },
  { id: "search", label: "settings.search", icon: <Search />, render: () => <SearchForm /> },
  { id: "apply", label: "settings.apply", icon: <Play />, render: () => <ApplySettings /> },
  { id: "autopilot", label: "settings.autopilot", icon: <Bot />, render: () => <AutopilotSettings /> },
  { id: "notifications", label: "settings.notifications", icon: <BellRing />, render: () => <NotificationSettings /> },
  { id: "answers", label: "settings.answers", icon: <MessageSquareText />, render: () => <AnswersSettings /> },
  { id: "exclusions", label: "settings.exclusions", icon: <Ban />, render: () => <ExclusionSettings /> },
  { id: "system", label: "settings.system", icon: <Cpu />, render: () => <SystemSettings /> },
];

export function SettingsPage() {
  const { t } = useI18n();
  const { tab = "profile" } = useParams();
  const current = TABS.find((x) => x.id === tab) ?? TABS[0];
  return (
    <>
      <PageHeader title={t("nav.settings")} />
      <div className="grid gap-6 lg:grid-cols-[200px_minmax(0,1fr)]">
        <nav
          className="-mx-4 flex gap-1 overflow-x-auto px-4 pb-1 [scrollbar-width:none] lg:mx-0 lg:flex-col lg:overflow-visible lg:px-0"
          aria-label={t("nav.settings")}
        >
          {TABS.map((x) => (
            <NavLink
              key={x.id}
              to={`/settings/${x.id}`}
              className={() =>
                cn(
                  "flex shrink-0 items-center gap-2.5 rounded-md px-3 py-2 text-[0.875rem] font-medium transition-colors [&_svg]:size-4",
                  current.id === x.id ? "bg-surface text-fg shadow-sm ring-1 ring-border" : "text-fg-muted hover:bg-surface-2 hover:text-fg",
                )
              }
            >
              {x.icon}
              {t(x.label)}
            </NavLink>
          ))}
        </nav>
        <div key={current.id} className="min-w-0 animate-fade-in">
          {current.render()}
        </div>
      </div>
    </>
  );
}
