import { useEffect, useRef } from "react";

/**
 * Tastenkürzel ohne Zusatzpaket. Schlüssel sind einzelne Tasten („j“, „?“, „/“, „escape“, „arrowdown“) oder Folgen mit
 * Leerzeichen („g h“ = erst G, dann H innerhalb einer Sekunde). Alle Komponenten teilen sich ein Register: Ist eine
 * Folge angefangen („g“), gewinnt sie – „g s“ springt zu Stellen, statt dort „s“ (Merken) auszulösen.
 * Greift nicht, solange ein Eingabefeld den Fokus hat, Strg/Alt/Cmd gedrückt sind oder ein Dialog/Menü offen ist
 * (außer Seitenleisten mit `data-hotkeys`).
 */
export type Hotkeys = Record<string, (e: KeyboardEvent) => void>;

export function isTyping(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  if (!el) return false;
  return el.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName);
}

const registry = new Set<{ current: Hotkeys }>();
let pending = "";
let timer: ReturnType<typeof setTimeout> | undefined;

function onKey(e: KeyboardEvent) {
  if (e.ctrlKey || e.metaKey || e.altKey || e.defaultPrevented || isTyping(e.target)) return;
  if (document.querySelector("[role=dialog][data-state=open]:not([data-hotkeys]), [role=menu][data-state=open]")) {
    return;
  }
  const combo = pending ? `${pending} ${e.key.toLowerCase()}` : e.key.toLowerCase();
  const maps = [...registry].map((r) => r.current);
  const handler = maps.find((m) => m[combo])?.[combo];
  clearTimeout(timer);
  if (handler) {
    e.preventDefault();
    pending = "";
    handler(e);
    return;
  }
  pending = maps.some((m) => Object.keys(m).some((k) => k.startsWith(`${combo} `))) ? combo : "";
  if (pending) timer = setTimeout(() => (pending = ""), 1000);
}

export function useHotkeys(keys: Hotkeys, enabled = true) {
  const ref = useRef(keys);
  ref.current = keys;
  useEffect(() => {
    if (!enabled) return;
    const entry = ref;
    if (registry.size === 0) window.addEventListener("keydown", onKey);
    registry.add(entry);
    return () => {
      registry.delete(entry);
      if (registry.size === 0) {
        window.removeEventListener("keydown", onKey);
        pending = "";
      }
    };
  }, [enabled]);
}
