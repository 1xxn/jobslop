import { createContext, type ReactNode, useCallback, useContext, useMemo, useState } from "react";
import { hasMessage, messages, type MessageKey } from "./messages";

export type Lang = "de" | "en";

function initialLang(): Lang {
  try {
    const stored = localStorage.getItem("jobslop.lang");
    if (stored === "de" || stored === "en") return stored;
  } catch {
    /* privates Fenster */
  }
  return navigator.language.toLowerCase().startsWith("de") ? "de" : "en";
}

interface I18n {
  lang: Lang;
  setLang: (lang: Lang) => void;
  t: (key: MessageKey, vars?: Record<string, string | number>) => string;
  /** Mit Zahl: nimmt `<key>_one` für genau 1, sonst `<key>` – {n} wird ersetzt. */
  tp: (key: MessageKey, n: number, vars?: Record<string, string | number>) => string;
}

const Ctx = createContext<I18n | null>(null);

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(initialLang);
  const setLang = useCallback((next: Lang) => {
    setLangState(next);
    document.documentElement.lang = next;
    try {
      localStorage.setItem("jobslop.lang", next);
    } catch {
      /* egal */
    }
  }, []);
  const t = useCallback(
    (key: MessageKey, vars?: Record<string, string | number>) => {
      let text: string = messages[lang][key] ?? messages.de[key] ?? key;
      if (vars) for (const [k, v] of Object.entries(vars)) text = text.replaceAll(`{${k}}`, String(v));
      return text;
    },
    [lang],
  );
  const tp = useCallback(
    (key: MessageKey, n: number, vars?: Record<string, string | number>) => {
      const one = `${key}_one`;
      return t(n === 1 && hasMessage(one) ? one : key, { n, ...vars });
    },
    [t],
  );
  const value = useMemo(() => ({ lang, setLang, t, tp }), [lang, setLang, t, tp]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useI18n(): I18n {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("I18nProvider fehlt");
  return ctx;
}
