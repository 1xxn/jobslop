import "./styles.css";
import { MutationCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { type ReactNode, StrictMode, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { toast } from "sonner";
import { App } from "./App";
import { useErrorText } from "./lib/backendText";
import { I18nProvider } from "./lib/i18n";

/** Jede fehlgeschlagene Aktion meldet sich als Toast in der gewählten Sprache – einzelne Mutationen schalten das
 * mit `meta: { silent: true }` ab, wenn sie den Fehler selbst zeigen. */
function QueryProvider({ children }: { children: ReactNode }) {
  const errorText = useErrorText();
  const describe = useRef(errorText);
  describe.current = errorText;
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false, staleTime: 5_000 } },
        mutationCache: new MutationCache({
          onError: (error, _vars, _ctx, mutation) => {
            if (!mutation.meta?.silent) toast.error(describe.current(error));
          },
        }),
      }),
  );
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

/** Anmelde-Link aus dem Terminal (`/#login=<token>`): einmal gegen das Sitzungs-Cookie tauschen (HttpOnly) und das
 * Token sofort aus Adresse und Verlauf entfernen. Ohne Link startet die Oberfläche ohne Umweg. */
async function login(): Promise<void> {
  const token = /^#login=([\w-]{20,200})$/.exec(window.location.hash)?.[1];
  if (!token) return;
  window.history.replaceState(null, "", window.location.pathname + window.location.search);
  await fetch("/api/session", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Jobslop": "1" },
    body: JSON.stringify({ token }),
  }).catch(() => undefined);
}

// Derselbe Tab mit einem neuen Anmelde-Link: nur das Fragment ändert sich, die Seite lädt nicht neu
window.addEventListener("hashchange", () => {
  if (window.location.hash.startsWith("#login=")) void login().finally(() => window.location.reload());
});

void login().finally(() =>
  createRoot(document.getElementById("root") as HTMLElement).render(
    <StrictMode>
      <I18nProvider>
        <QueryProvider>
          <App />
        </QueryProvider>
      </I18nProvider>
    </StrictMode>,
  ),
);
