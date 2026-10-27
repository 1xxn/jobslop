import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { api } from "./api";
import type { Status } from "./types";

/** Live-Zustand (Rückfragen, laufende Prozesse) – alle 3 Sekunden. */
export function useStatus() {
  return useQuery({ queryKey: ["status"], queryFn: api.status, refetchInterval: 3000, refetchOnWindowFocus: true });
}

export function useSearchConfig() {
  return useQuery({ queryKey: ["search"], queryFn: api.search, staleTime: 60_000 });
}

export function useRoleNames(): string[] {
  const { data } = useSearchConfig();
  return data?.roles.map((r) => r.name) ?? [];
}

export type Theme = "light" | "dark" | "system";

export function useTheme(): [Theme, (t: Theme) => void] {
  const [theme, setTheme] = useState<Theme>(() => {
    try {
      return (localStorage.getItem("jobslop.theme") as Theme) || "system";
    } catch {
      return "system";
    }
  });
  useEffect(() => {
    const media = matchMedia("(prefers-color-scheme: dark)");
    const apply = () => {
      const dark = theme === "dark" || (theme === "system" && media.matches);
      document.documentElement.classList.toggle("dark", dark);
    };
    apply();
    try {
      localStorage.setItem("jobslop.theme", theme);
    } catch {
      /* egal */
    }
    media.addEventListener("change", apply);
    return () => media.removeEventListener("change", apply);
  }, [theme]);
  return [theme, setTheme];
}

/** Browser-Benachrichtigung, sobald eine neue Rückfrage auftaucht oder ein Lauf endet. */
export function useDesktopNotifications(status: Status | undefined, text: { prompt: string; done: string }) {
  const seen = useRef<Set<number> | null>(null);
  const wasActive = useRef(false);
  useEffect(() => {
    if (!status) return;
    const enabled = status.notify_desktop && "Notification" in window && Notification.permission === "granted";
    const ids = new Set(status.prompts.map((p) => p.id));
    if (seen.current && enabled && document.visibilityState !== "visible") {
      for (const p of status.prompts) {
        if (!seen.current.has(p.id)) {
          new Notification("jobslop", { body: `${p.payload.title ?? ""} – ${text.prompt}`, tag: `prompt-${p.id}` });
        }
      }
    }
    if (wasActive.current && !status.runner.active && enabled && document.visibilityState !== "visible") {
      new Notification("jobslop", { body: text.done, tag: "runner" });
    }
    seen.current = ids;
    wasActive.current = status.runner.active;
  }, [status, text.prompt, text.done]);
}

export function useDebounced<T>(value: T, ms = 250): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const id = setTimeout(() => setV(value), ms);
    return () => clearTimeout(id);
  }, [value, ms]);
  return v;
}

/** Trifft die Media Query gerade zu? (z. B. breit genug für Liste und Stelle nebeneinander) */
export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (notify) => {
      const m = matchMedia(query);
      m.addEventListener("change", notify);
      return () => m.removeEventListener("change", notify);
    },
    () => matchMedia(query).matches,
    () => false,
  );
}
