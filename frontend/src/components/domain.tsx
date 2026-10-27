import type { ReactNode } from "react";
import { useI18n } from "@/lib/i18n";
import type { MessageKey } from "@/lib/messages";
import type { AppStatus } from "@/lib/types";
import { cn, initials } from "@/lib/utils";
import { Tooltip } from "./ui/overlays";

/** Wortmarke: einfarbiges Zeichen in Petrol – der Tropfen im Logo ist die Herkunft der Akzentfarbe. */
export function Logo({ className, withText = true }: { className?: string; withText?: boolean }) {
  return (
    <span className={cn("inline-flex items-center gap-2", className)}>
      <svg viewBox="0 0 64 64" className="size-6 shrink-0" aria-hidden>
        <rect width="64" height="64" rx="14" className="fill-accent" />
        <path
          d="M38 14v23.5c0 6.4-4.6 11.5-11 11.5-3.6 0-6.7-1.6-8.7-4.2"
          fill="none"
          className="stroke-on-accent"
          strokeWidth="6"
          strokeLinecap="round"
        />
        <circle cx="38" cy="14" r="3" className="fill-on-accent" />
        <path
          d="M46 40c0 2.8-1.9 5-4.2 5s-4.2-2.2-4.2-5c0-3.2 4.2-8.3 4.2-8.3s4.2 5.1 4.2 8.3z"
          className="fill-on-accent"
          opacity="0.7"
        />
      </svg>
      {withText && <span className="text-heading font-semibold tracking-[-0.01em]">jobslop</span>}
    </span>
  );
}

/* ----------------------------------------------------------------- Status: Glyphe + Wort statt farbiger Pill */

type Glyph = "ring" | "pie" | "you" | "pause" | "dot" | "good" | "slash" | "fail" | "dash";

const GLYPH: Record<string, Glyph> = {
  queued: "ring",
  running: "pie",
  needs_input: "you",
  needs_review: "you",
  ready: "you",
  paused: "pause",
  submitted: "dot",
  manual: "dot",
  interview: "good",
  offer: "good",
  rejected: "slash",
  failed: "fail",
  skipped: "dash",
};

/** Statuszeichen (12 px). Nie allein verwenden – immer mit Wort daneben oder als Gruppentitel. */
export function StatusGlyph({ status, className }: { status: string; className?: string }) {
  const g = GLYPH[status] ?? "ring";
  return (
    <svg viewBox="0 0 12 12" className={cn("size-3 shrink-0", className)} aria-hidden>
      {g === "ring" && <circle cx="6" cy="6" r="4.25" fill="none" strokeWidth="1.5" className="stroke-ink-3" />}
      {g === "pie" && (
        <>
          <circle cx="6" cy="6" r="4.25" fill="none" strokeWidth="1.5" className="stroke-accent" />
          <path d="M6 6V2.5A3.5 3.5 0 0 1 9.5 6Z" className="fill-accent" />
        </>
      )}
      {g === "you" && (
        <>
          <circle cx="6" cy="6" r="6" className="fill-accent-soft" />
          <circle cx="6" cy="6" r="3.5" className="fill-accent" />
        </>
      )}
      {g === "pause" && (
        <>
          <circle cx="6" cy="6" r="4.25" fill="none" strokeWidth="1.5" className="stroke-ink-3" />
          <path d="M4.75 4.25v3.5M7.25 4.25v3.5" strokeWidth="1.25" className="stroke-ink-3" />
        </>
      )}
      {g === "dot" && <circle cx="6" cy="6" r="4" className="fill-ink-3" />}
      {g === "good" && <circle cx="6" cy="6" r="4" className="fill-positive" />}
      {g === "fail" && <circle cx="6" cy="6" r="4" className="fill-danger" />}
      {g === "slash" && (
        <>
          <circle cx="6" cy="6" r="4.25" fill="none" strokeWidth="1.5" className="stroke-ink-3" />
          <path d="M3.25 8.75l5.5-5.5" strokeWidth="1.25" className="stroke-ink-3" />
        </>
      )}
      {g === "dash" && (
        <>
          <circle cx="6" cy="6" r="4.25" fill="none" strokeWidth="1.5" className="stroke-ink-3" />
          <path d="M4 6h4" strokeWidth="1.25" className="stroke-ink-3" />
        </>
      )}
    </svg>
  );
}

/** Wartet der Status auf dich? (Rückfrage, Freigabe, ausgefüllt) */
export function waitsForYou(status: string): boolean {
  return GLYPH[status] === "you";
}

export function StatusLabel({ status, className }: { status: AppStatus | string; className?: string }) {
  const { t } = useI18n();
  if (!status) return null;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 whitespace-nowrap text-meta",
        waitsForYou(status) ? "font-medium text-accent" : status === "failed" ? "text-danger" : "text-ink-2",
        className,
      )}
    >
      <StatusGlyph status={status} />
      {t(`status.${status}` as MessageKey)}
    </span>
  );
}

/* ----------------------------------------------------------------- Score: Zahl mit schmalem Balken darunter, ohne Ampelfarben */

/** Höchster möglicher Score (classify.SCORE_MAX): erste Zielrolle, Stack ●●●, große Firma, Level, in der Nähe. */
export const SCORE_MAX = 21;

export function Score({ score, className }: { score: number; className?: string }) {
  const { t } = useI18n();
  const pct = Math.max(0, Math.min(1, score / SCORE_MAX));
  const label = t("job.score_label", { score: Math.round(score), max: SCORE_MAX });
  return (
    <Tooltip content={t("job.score_hint", { max: SCORE_MAX })}>
      <span
        className={cn("inline-grid w-7 shrink-0 justify-items-end gap-1", className)}
        aria-label={label}
        role="img"
      >
        <span className="tabular text-body leading-none font-semibold" aria-hidden>
          {Math.round(score)}
        </span>
        <span className="relative h-[3px] w-full overflow-hidden rounded-full bg-line" aria-hidden>
          <span className="absolute inset-y-0 left-0 rounded-full bg-ink-2" style={{ width: `${pct * 100}%` }} />
        </span>
      </span>
    </Tooltip>
  );
}

export function FitDots({ fit }: { fit: number }) {
  const { t } = useI18n();
  return (
    <Tooltip content={t("job.fit_hint", { n: fit })}>
      <span className="inline-flex gap-0.5" aria-label={t("job.fit_hint", { n: fit })} role="img">
        {[1, 2, 3].map((i) => (
          <span key={i} className={cn("h-3 w-1 rounded-full", i <= fit ? "bg-ink-2" : "bg-sunken")} />
        ))}
      </span>
    </Tooltip>
  );
}

export function CompanyAvatar({ name, size = 36 }: { name: string; size?: number }) {
  return (
    <span
      className="avatar grid shrink-0 place-items-center rounded-md text-small font-semibold"
      style={{ width: size, height: size }}
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
    <span className="truncate text-meta text-ink-2">
      {location ? location.split(";")[0] : label}
      {workplace && <span className="text-ink-3"> · {workplace}</span>}
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
    <header className="mb-5">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <div className="min-w-0">
          <h1 className="text-title font-semibold tracking-[-0.01em] text-balance">{title}</h1>
          {description && <p className="mt-0.5 text-meta text-ink-2">{description}</p>}
        </div>
        {actions && <div className="flex flex-wrap items-center gap-1">{actions}</div>}
      </div>
      {children}
    </header>
  );
}

export function Stat({ label, value, hint }: { label: ReactNode; value: ReactNode; hint?: ReactNode }) {
  return (
    <div className="border-t border-line pt-3">
      <div className="text-meta text-ink-2">{label}</div>
      <div className="tabular mt-1 text-title font-semibold">{value}</div>
      {hint && <div className="text-small text-ink-3">{hint}</div>}
    </div>
  );
}

/** Gesendete Bewerbungen pro Woche (letzte 12 Wochen). */
export function WeeklyChart({ weeks }: { weeks: { week: string; sent: number }[] }) {
  const { t, lang } = useI18n();
  const max = Math.max(1, ...weeks.map((w) => w.sent));
  return (
    <>
      <div className="flex h-24 items-end gap-1" role="img" aria-label={t("overview.weekly")}>
        {weeks.map((w, i) => (
          <div key={w.week} className="group flex flex-1 flex-col items-center gap-1">
            <span className="tabular text-small text-ink-3 opacity-0 transition-opacity group-hover:opacity-100">
              {w.sent}
            </span>
            <div
              className={cn("w-full rounded-t-sm", i === weeks.length - 1 ? "bg-accent" : "bg-ink-3/50")}
              style={{ height: `${Math.max(2, (w.sent / max) * 72)}px` }}
            />
          </div>
        ))}
      </div>
      <div className="mt-2 flex justify-between text-small text-ink-3">
        <span>{weeks[0] && new Date(weeks[0].week).toLocaleDateString(lang, { day: "numeric", month: "short" })}</span>
        <span>{t("overview.this_week")}</span>
      </div>
    </>
  );
}
