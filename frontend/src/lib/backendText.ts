import { useCallback } from "react";
import { useI18n } from "./i18n";
import { type MessageKey, messages } from "./messages";

/**
 * Meldungen aus dem Backend in der gewählten Sprache.
 *
 * Das Backend speichert neben dem deutschen Klartext einen Code mit Parametern (z. B. `crawl.done` mit
 * `{ new: 3 }`). Übersetzt wird über `be.<code>` in messages.ts; fehlt Code oder Übersetzung (ältere Einträge,
 * freie Fehlermeldungen), bleibt der Klartext. Parameter `status`, `mode` und `counts` werden mitübersetzt.
 */
export function useBackendText() {
  const { t } = useI18n();
  return useCallback(
    (code: string | undefined, params: Record<string, unknown> | undefined, fallback: string): string => {
      const key = `be.${code}` as MessageKey;
      if (!code || !(key in messages.de)) return fallback;
      const vars: Record<string, string | number> = {};
      for (const [name, value] of Object.entries(params ?? {})) {
        if (name === "status" && typeof value === "string") vars[name] = t(`status.${value}` as MessageKey);
        else if (name === "mode" && typeof value === "string") vars[name] = t(`mode.${value}` as MessageKey);
        else if (name === "counts" && value && typeof value === "object") {
          vars[name] =
            Object.entries(value as Record<string, number>)
              .map(([status, n]) => `${n}× ${t(`status.${status}` as MessageKey)}`)
              .join(", ") || "–";
        } else vars[name] = typeof value === "number" ? value : String(value ?? "");
      }
      return t(key, vars);
    },
    [t],
  );
}

/** Code und Parameter, die das Backend in `data` eines Aktivitätseintrags ablegt. */
export function codeOf(data: Record<string, unknown> | undefined): [string | undefined, Record<string, unknown>] {
  const code = typeof data?.code === "string" ? data.code : undefined;
  const params = data?.params && typeof data.params === "object" ? (data.params as Record<string, unknown>) : {};
  return [code, params];
}
