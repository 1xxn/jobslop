import { type ClassValue, clsx } from "clsx";
import { extendTailwindMerge } from "tailwind-merge";
import { hasMessage, type MessageKey } from "./messages";

// Eigene Schriftstufen (styles.css → --text-*) bekannt machen: sonst hält tailwind-merge z. B. `text-body`
// für eine Textfarbe und verwirft dafür `text-on-accent`.
const twMerge = extendTailwindMerge({
  extend: {
    theme: { text: ["small", "meta", "body", "read", "heading", "title", "display"] },
  },
});

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function parseDate(value: string | null | undefined): Date | null {
  if (!value) return null;
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? null : d;
}

export function formatRelative(value: string | null | undefined, lang: string): string {
  const d = parseDate(value);
  if (!d) return "";
  const diff = (d.getTime() - Date.now()) / 1000;
  const rtf = new Intl.RelativeTimeFormat(lang, { numeric: "auto" });
  const abs = Math.abs(diff);
  if (abs < 60) return rtf.format(Math.round(diff), "second");
  if (abs < 3600) return rtf.format(Math.round(diff / 60), "minute");
  if (abs < 86400) return rtf.format(Math.round(diff / 3600), "hour");
  if (abs < 86400 * 30) return rtf.format(Math.round(diff / 86400), "day");
  return d.toLocaleDateString(lang, { day: "numeric", month: "short", year: "numeric" });
}

export function formatDateTime(value: string | null | undefined, lang: string): string {
  const d = parseDate(value);
  if (!d) return "";
  return d.toLocaleString(lang, { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}

/** Zeitpunkt in der nahen Zukunft oder Vergangenheit: „heute 08:00“, „morgen 08:00“, „Mi. 08:00“, sonst Datum. */
export function formatWhen(value: string | null | undefined, lang: string): string {
  const d = parseDate(value);
  if (!d) return "";
  const time = d.toLocaleTimeString(lang, { hour: "2-digit", minute: "2-digit" });
  const startOf = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const days = Math.round((startOf(d) - startOf(new Date())) / 86_400_000);
  if (Math.abs(days) <= 1) {
    return `${new Intl.RelativeTimeFormat(lang, { numeric: "auto" }).format(days, "day")} ${time}`;
  }
  if (Math.abs(days) < 7) return `${d.toLocaleDateString(lang, { weekday: "short" })} ${time}`;
  return formatDateTime(value, lang);
}

export function formatDate(value: string | null | undefined, lang: string): string {
  const d = parseDate(value);
  return d ? d.toLocaleDateString(lang, { day: "numeric", month: "short", year: "numeric" }) : "";
}

/** Einträge nach Kalendertag gruppieren (Tagesname in der Sprache der Oberfläche), optional neueste zuerst. */
export function groupByDay<T>(
  items: T[],
  ts: (item: T) => string | null | undefined,
  lang: string,
  newestFirst = false,
): [string, T[]][] {
  const time = (item: T) => parseDate(ts(item))?.getTime() ?? 0;
  const sorted = newestFirst ? [...items].sort((a, b) => time(b) - time(a)) : items;
  const days = new Map<string, T[]>();
  for (const item of sorted) {
    const day = parseDate(ts(item))?.toLocaleDateString(lang, { weekday: "long", day: "numeric", month: "long" }) ?? "";
    days.set(day, [...(days.get(day) ?? []), item]);
  }
  return [...days];
}

export function percent(value: number, lang: string): string {
  return new Intl.NumberFormat(lang, { style: "percent", maximumFractionDigits: 0 }).format(value);
}

/** Stabile Farbklasse pro Zielrolle (Reihenfolge = Priorität aus der Suchkonfiguration). */
export function roleClass(category: string, roles: string[]): string {
  const idx = roles.indexOf(category);
  return `role-${idx < 0 ? 7 : idx % 7}`;
}

// Adressen aus Job-Quellen und von Bewerbungsseiten sind fremde Daten: als Link oder Fenster nur http(s) – kein
// javascript:, data: oder file:
export function webUrl(url: string | null | undefined): string | undefined {
  if (!url) return undefined;
  try {
    const parsed = new URL(url);
    return parsed.protocol === "https:" || parsed.protocol === "http:" ? parsed.href : undefined;
  } catch {
    return undefined;
  }
}

export function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return "";
  }
}

// Markennamen sind in allen Sprachen gleich; alles andere steht übersetzt in messages.ts (source.*)
const SOURCE_BRANDS: Record<string, string> = {
  arbeitsagentur: "Arbeitsagentur",
  arbeitnow: "Arbeitnow",
  himalayas: "Himalayas",
  greenhouse: "Greenhouse",
  ashby: "Ashby",
  lever: "Lever",
  smartrecruiters: "SmartRecruiters",
  personio: "Personio",
  recruitee: "Recruitee",
  workable: "Workable",
  workday: "Workday",
  amazon: "amazon.jobs",
  linkedin: "LinkedIn",
  indeed: "Indeed",
  glassdoor: "Glassdoor",
};

/** Lesbarer Name der Quelle: „portal:linkedin“ → LinkedIn, „greenhouse:gitlab“ → Greenhouse. */
export function sourceName(source: string, t: (key: MessageKey) => string): string {
  const [kind, rest] = source.split(":", 2);
  const key = kind === "portal" ? rest : kind === "seed" ? "import" : kind;
  // hasOwn: „constructor“ oder „toString“ als Quellname träfen sonst Object.prototype (fast-check hat es gefunden)
  if (key && Object.hasOwn(SOURCE_BRANDS, key)) return SOURCE_BRANDS[key];
  const label = `source.${key}`;
  return hasMessage(label) ? t(label) : source;
}
