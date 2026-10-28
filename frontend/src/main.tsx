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

createRoot(document.getElementById("root") as HTMLElement).render(
  <StrictMode>
    <I18nProvider>
      <QueryProvider>
        <App />
      </QueryProvider>
    </I18nProvider>
  </StrictMode>,
);
