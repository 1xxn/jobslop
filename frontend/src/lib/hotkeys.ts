import { useEffect, useRef } from "react";

/**
 * Tastenkürzel ohne Zusatzpaket. Schlüssel sind einzelne Tasten („j“, „?“, „/“, „escape“) oder Folgen mit Leerzeichen
 * („g h“ = erst G, dann H innerhalb einer Sekunde). Greift nicht, solange ein Eingabefeld den Fokus hat oder
 * Strg/Alt/Cmd gedrückt sind – so kollidiert nichts mit Tippen oder Browser-Kürzeln.
 */
export type Hotkeys = Record<string, (e: KeyboardEvent) => void>;

export function isTyping(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  if (!el) return false;
  return el.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName);
}

export function useHotkeys(keys: Hotkeys, enabled = true) {
  const ref = useRef(keys);
  ref.current = keys;
  useEffect(() => {
    if (!enabled) return;
    let pending = "";
    let timer: ReturnType<typeof setTimeout> | undefined;
    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey || e.altKey || e.defaultPrevented || isTyping(e.target)) return;
      // offene Dialoge und Menüs behalten ihre eigene Tastatur
      if (document.querySelector("[role=dialog][data-state=open], [role=menu][data-state=open]")) return;
      const key = e.key.toLowerCase();
      const combo = pending ? `${pending} ${key}` : key;
      const handler = ref.current[combo];
      if (handler) {
        e.preventDefault();
        pending = "";
        handler(e);
        return;
      }
      const isPrefix = Object.keys(ref.current).some((k) => k.startsWith(`${combo} `));
      pending = isPrefix ? combo : "";
      clearTimeout(timer);
      if (pending) timer = setTimeout(() => (pending = ""), 1000);
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      clearTimeout(timer);
    };
  }, [enabled]);
}
