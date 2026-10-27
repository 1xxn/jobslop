import { type ClassValue, clsx } from "clsx";
import { extendTailwindMerge } from "tailwind-merge";
import { hasMessage, type MessageKey } from "./messages";

// Eigene Schriftstufen (styles.css → --text-*) bekannt machen: sonst hält tailwind-merge z. B. `text-body`
// für eine Textfarbe und verwirft dafür `text-primary-fg`.
const twMerge = extendTailwindMerge({
  extend: {
    theme: { text: ["caption", "footnote", "body", "headline", "title3", "title2", "title1", "large"] },
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

export function formatDate(value: string | null | undefined, lang: string): string {
  const d = parseDate(value);
  return d ? d.toLocaleDateString(lang, { day: "numeric", month: "short", year: "numeric" }) : "";
}

export function percent(value: number, lang: string): string {
  return new Intl.NumberFormat(lang, { style: "percent", maximumFractionDigits: 0 }).format(value);
}

/** Stabile Farbklasse pro Zielrolle (Reihenfolge = Priorität aus der Suchkonfiguration). */
export function roleClass(category: string, roles: string[]): string {
  const idx = roles.indexOf(category);
  return `role-${idx < 0 ? 7 : idx % 7}`;
}

export function initials(name: string): string {
  return name
    .split(/[\s&,.-]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase() ?? "")
    .join("");
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
  if (key && SOURCE_BRANDS[key]) return SOURCE_BRANDS[key];
  const label = `source.${key}`;
  return hasMessage(label) ? t(label) : source;
}
