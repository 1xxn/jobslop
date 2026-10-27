import { CircleCheck, CircleX, Clock, Hand, Hourglass, LoaderCircle, MessageCircleQuestion, Pause, Send, Star } from "lucide-react";
import { type ReactNode, useId } from "react";
import { useI18n } from "@/lib/i18n";
import type { MessageKey } from "@/lib/messages";
import type { AppStatus } from "@/lib/types";
import { cn, initials, roleClass } from "@/lib/utils";
import { Badge } from "./ui/primitives";
import { Tooltip } from "./ui/overlays";

export function Logo({ className, withText = true }: { className?: string; withText?: boolean }) {
  // eigene Verlaufs-ID je Instanz: eine ausgeblendete Kopie (z. B. Seitenleiste auf dem Handy) würde sie sonst „verschlucken“
  const gradient = `jl-${useId().replace(/:/g, "")}`;
  return (
    <span className={cn("inline-flex items-center gap-2.5", className)}>
      <svg viewBox="0 0 64 64" className="size-7 shrink-0" aria-hidden>
        <defs>
          <linearGradient id={gradient} x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="#7c6cff" />
            <stop offset="1" stopColor="#3b5bfd" />
          </linearGradient>
        </defs>
        <rect width="64" height="64" rx="16" fill={`url(#${gradient})`} />
        <path
          d="M38 14v23.5c0 6.4-4.6 11.5-11 11.5-3.6 0-6.7-1.6-8.7-4.2"
          fill="none"
          stroke="#fff"
          strokeWidth="6"
          strokeLinecap="round"
        />
        <circle cx="38" cy="14" r="3" fill="#fff" />
        <path d="M46 40c0 2.8-1.9 5-4.2 5s-4.2-2.2-4.2-5c0-3.2 4.2-8.3 4.2-8.3s4.2 5.1 4.2 8.3z" fill="#c7f9e8" />
      </svg>
      {withText && <span className="text-[1.0625rem] font-semibold tracking-[-0.02em]">jobslop</span>}
    </span>
  );
}

const STATUS: Record<string, { tone: "neutral" | "primary" | "success" | "warning" | "danger" | "info"; icon: ReactNode }> = {
  running: { tone: "info", icon: <LoaderCircle className="animate-spin" /> },
  queued: { tone: "primary", icon: <Clock /> },
  needs_input: { tone: "warning", icon: <MessageCircleQuestion /> },
  needs_review: { tone: "warning", icon: <Hand /> },
  ready: { tone: "info", icon: <CircleCheck /> },
  paused: { tone: "neutral", icon: <Pause /> },
  submitted: { tone: "success", icon: <Send /> },
  manual: { tone: "success", icon: <Send /> },
  interview: { tone: "primary", icon: <Star /> },
  offer: { tone: "success", icon: <Star /> },
  rejected: { tone: "neutral", icon: <CircleX /> },
  failed: { tone: "danger", icon: <CircleX /> },
  skipped: { tone: "neutral", icon: <Hourglass /> },
};

export function StatusBadge({ status, className }: { status: AppStatus | string; className?: string }) {
  const { t } = useI18n();
  if (!status) return null;
  const s = STATUS[status] ?? { tone: "neutral" as const, icon: null };
  return (
    <Badge tone={s.tone} className={className}>
      {s.icon}
      {t(`status.${status}` as MessageKey)}
    </Badge>
  );
}

export function RoleBadge({ category, roles }: { category: string; roles: string[] }) {
  return (
    <Badge tone="role" className={roleClass(category, roles)}>
      <span className="size-1.5 rounded-full bg-[var(--role)]" />
      {category}
    </Badge>
  );
}

/** Score als kleiner Ring – auf einen Blick vergleichbar (max. ~20 Punkte). */
/** Höchster möglicher Score (classify.SCORE_MAX): erste Zielrolle, Stack ●●●, große Firma, Level, in der Nähe. */
export const SCORE_MAX = 21;

export function ScoreRing({ score, size = 36 }: { score: number; size?: number }) {
  const { t } = useI18n();
  const pct = Math.max(0, Math.min(1, score / SCORE_MAX));
  const r = (size - 5) / 2;
  const c = 2 * Math.PI * r;
  const tone = pct >= 0.75 ? "var(--success)" : pct >= 0.5 ? "var(--primary)" : pct >= 0.3 ? "var(--warning)" : "var(--fg-subtle)";
  return (
    <Tooltip content={t("job.score_hint", { max: SCORE_MAX })}>
      <span className="relative inline-grid shrink-0 place-items-center" style={{ width: size, height: size }}>
        <svg width={size} height={size} className="-rotate-90">
          <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--surface-3)" strokeWidth="3" />
          <circle
            cx={size / 2}
            cy={size / 2}
            r={r}
            fill="none"
            stroke={tone}
            strokeWidth="3"
            strokeLinecap="round"
            strokeDasharray={`${c * pct} ${c}`}
            className="transition-[stroke-dasharray] duration-500"
          />
        </svg>
        <span className="tabular absolute text-[0.6875rem] font-semibold">{Math.round(score)}</span>
      </span>
    </Tooltip>
  );
}

export function FitDots({ fit }: { fit: number }) {
  const { t } = useI18n();
  return (
    <Tooltip content={t("job.fit_hint", { n: fit })}>
      <span className="inline-flex gap-0.5" aria-label={t("job.fit_hint", { n: fit })}>
        {[1, 2, 3].map((i) => (
          <span key={i} className={cn("h-3 w-1 rounded-full", i <= fit ? "bg-primary" : "bg-surface-3")} />
        ))}
      </span>
    </Tooltip>
  );
}

function hue(text: string): number {
  let h = 0;
  for (const ch of text) h = (h * 31 + ch.charCodeAt(0)) % 360;
  return h;
}

export function CompanyAvatar({ name, size = 36 }: { name: string; size?: number }) {
  const h = hue(name || "?");
  return (
    <span
      className="avatar grid shrink-0 place-items-center rounded-[10px] text-[0.75rem] font-semibold"
      style={{ width: size, height: size, ["--h" as string]: h }}
      aria-hidden
    >
      {initials(name) || "?"}
    </span>
  );
}

export function WhereLabel({ where, workplace, location }: { where: string; workplace?: string; location?: string }) {
  const { t } = useI18n();
  const label = where === "R" ? t("where.remote") : where === "BR" ? t("where.both") : t("where.onsite");
  return (
    <span className="truncate text-footnote text-fg-muted">
      {location ? location.split(";")[0] : label}
      {workplace && <span className="text-fg-subtle"> · {workplace}</span>}
    </span>
  );
}

export function PageHeader({
  title,
  description,
  actions,
  children,
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <header className="mb-6 animate-slide-up">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-title1 font-bold tracking-[-0.025em]">{title}</h1>
          {description && <p className="mt-1 text-body text-fg-muted">{description}</p>}
        </div>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </div>
      {children}
    </header>
  );
}

export function Stat({
  label,
  value,
  hint,
  icon,
  tone = "neutral",
}: {
  label: ReactNode;
  value: ReactNode;
  hint?: ReactNode;
  icon?: ReactNode;
  tone?: "neutral" | "primary" | "success" | "warning";
}) {
  const tones = {
    neutral: "bg-surface-2 text-fg-muted",
    primary: "bg-primary-soft text-primary",
    success: "bg-success-soft text-success",
    warning: "bg-warning-soft text-warning",
  };
  return (
    <div className="rounded-lg border border-border bg-surface p-4 shadow-sm">
      <div className="flex items-center justify-between">
        <span className="text-footnote font-medium text-fg-muted">{label}</span>
        {icon && <span className={cn("grid size-7 place-items-center rounded-md [&_svg]:size-4", tones[tone])}>{icon}</span>}
      </div>
      <div className="tabular mt-2 text-title1 font-bold tracking-[-0.02em]">{value}</div>
      {hint && <div className="mt-0.5 text-caption text-fg-subtle">{hint}</div>}
    </div>
  );
}

/** Gesendete Bewerbungen pro Woche (letzte 12 Wochen). */
export function WeeklyChart({ weeks }: { weeks: { week: string; sent: number }[] }) {
  const { t, lang } = useI18n();
  const max = Math.max(1, ...weeks.map((w) => w.sent));
  return (
    <>
      <div className="flex h-28 items-end gap-1.5" role="img" aria-label={t("overview.weekly")}>
        {weeks.map((w) => (
          <div key={w.week} className="group flex flex-1 flex-col items-center gap-1.5">
            <span className="tabular text-caption text-fg-subtle opacity-0 transition-opacity group-hover:opacity-100">
              {w.sent}
            </span>
            <div
              className="w-full rounded-t-[5px] bg-primary/80 transition-[height] duration-500 group-hover:bg-primary"
              style={{ height: `${Math.max(3, (w.sent / max) * 80)}px`, opacity: w.sent ? 1 : 0.25 }}
            />
          </div>
        ))}
      </div>
      <div className="mt-2 flex justify-between text-caption text-fg-subtle">
        <span>{weeks[0] && new Date(weeks[0].week).toLocaleDateString(lang, { day: "numeric", month: "short" })}</span>
        <span>{t("overview.this_week")}</span>
      </div>
    </>
  );
}
