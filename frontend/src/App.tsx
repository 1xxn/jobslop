import { type ReactNode, useEffect } from "react";
import { createBrowserRouter, Navigate, RouterProvider, useLocation, useRouteError } from "react-router";
import { Toaster } from "sonner";
import { AppShell } from "./components/layout/AppShell";
import { Logo } from "./components/domain";
import { TooltipProvider } from "./components/ui/overlays";
import { Button, Spinner } from "./components/ui/primitives";
import { ApiError } from "./lib/api";
import { useErrorText } from "./lib/backendText";
import { useStatus } from "./lib/hooks";
import { useI18n } from "./lib/i18n";

// Jede Seite ist ein eigener Chunk – geladen wird nur, was du öffnest. Der Router lädt ihn, bevor er die Seite zeigt
// (route.lazy): Mit React.lazy zeigte Suspense erst einen Platzhalter, und React 19 gibt den Inhalt danach frühestens
// nach 300 ms frei – jeder Start und jedes Neuladen wartete so 300 ms, obwohl der Chunk nach 10 ms da war.
const pages = {
  applicationDetail: async () => ({ Component: (await import("./pages/ApplicationDetail")).ApplicationDetailPage }),
  applications: async () => ({ Component: (await import("./pages/Applications")).ApplicationsPage }),
  jobs: async () => ({ Component: (await import("./pages/Jobs")).JobsPage }),
  today: async () => ({ Component: (await import("./pages/Today")).TodayPage }),
  settings: async () => ({ Component: (await import("./pages/settings/Settings")).SettingsPage }),
  setup: async () => ({ Component: (await import("./pages/setup/SetupWizard")).SetupWizard }),
};

function FullPageSpinner() {
  return (
    <div className="grid min-h-dvh place-items-center">
      <div className="flex flex-col items-center gap-4">
        <Logo />
        <Spinner />
      </div>
    </div>
  );
}

/** Leitet beim ersten Start in die Einrichtung. */
function SetupGate({ children }: { children: ReactNode }) {
  const { data, isLoading, isError, error } = useStatus();
  const location = useLocation();
  const { t } = useI18n();
  if (isLoading) return <FullPageSpinner />;
  if (isError) {
    // 401: Browser ohne Sitzungs-Cookie (neues Profil, Cookies gelöscht) – angemeldet öffnet ihn der Befehl `jobslop`
    const login = error instanceof ApiError && error.status === 401;
    return (
      <div className="grid min-h-dvh place-items-center p-6 text-center">
        <div className="max-w-prose">
          <Logo />
          <p className="mt-4 text-ink-2">{t(login ? "app.login" : "app.offline")}</p>
        </div>
      </div>
    );
  }
  if (data && !data.setup_completed && !location.pathname.startsWith("/setup")) {
    return <Navigate to="/setup" replace />;
  }
  return <>{children}</>;
}

/** Absturz beim Anzeigen einer Seite: statt weißer Fläche eine Meldung mit Ausweg. In der App-Hülle bleibt die
 * Navigation dabei bedienbar. */
function RouteError() {
  const error = useRouteError();
  const { t } = useI18n();
  const errorText = useErrorText();
  // Nach einem Update gibt es die alten Seiten-Dateien nicht mehr – dann hilft genau ein Neuladen
  const stale =
    error instanceof Error && /dynamically imported module|module script|error loading dynamically/i.test(error.message);
  return (
    <div role="alert" className="grid max-w-prose gap-4 py-10">
      <h1 className="text-title font-semibold">{t(stale ? "error.updated_title" : "error.page_title")}</h1>
      <p className="text-ink-2">{t(stale ? "error.updated_text" : "error.page_text")}</p>
      {!stale && (
        <details className="text-meta text-ink-2">
          <summary className="cursor-pointer">{t("error.details")}</summary>
          <pre className="mt-2 overflow-auto rounded-md border border-line bg-sunken px-3 py-2 font-mono text-small whitespace-pre-wrap">
            {errorText(error)}
          </pre>
        </details>
      )}
      <div className="flex flex-wrap gap-3">
        <Button variant="primary" onClick={() => window.location.reload()}>
          {t("error.reload")}
        </Button>
        <Button variant="secondary" onClick={() => window.location.assign("/")}>
          {t("error.home")}
        </Button>
      </div>
    </div>
  );
}

function Gated({ children }: { children: ReactNode }) {
  return <SetupGate>{children}</SetupGate>;
}

const router = createBrowserRouter([
  {
    path: "/setup",
    errorElement: (
      <div className="px-4 sm:px-6">
        <RouteError />
      </div>
    ),
    lazy: pages.setup,
    HydrateFallback: FullPageSpinner,
  },
  {
    element: (
      <Gated>
        <AppShell />
      </Gated>
    ),
    HydrateFallback: FullPageSpinner,
    errorElement: (
      <div className="px-4 sm:px-6">
        <RouteError />
      </div>
    ),
    children: [
      {
        // Abstürze einer Seite landen hier – innerhalb der Hülle, die Navigation bleibt
        errorElement: <RouteError />,
        children: [
          { index: true, lazy: pages.today },
          { path: "jobs", lazy: pages.jobs },
          // alte Adressen: Pipeline ist jetzt die Board-Ansicht der Bewerbungen, Aktivität das Protokoll
          { path: "pipeline", element: <Navigate to="/applications?view=board" replace /> },
          { path: "applications", lazy: pages.applications },
          { path: "applications/:id", lazy: pages.applicationDetail },
          { path: "activity", element: <Navigate to="/settings/log" replace /> },
          { path: "settings", lazy: pages.settings },
          { path: "settings/:tab", lazy: pages.settings },
          { path: "*", element: <Navigate to="/" replace /> },
        ],
      },
    ],
  },
]);

export function App() {
  const { lang } = useI18n();
  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);
  return (
    <TooltipProvider>
      <RouterProvider router={router} />
      <Toaster
        position="bottom-right"
        offset={{ bottom: 88, right: 16 }}
        toastOptions={{
          classNames: {
            toast: "!rounded-lg !border !border-line !bg-raised !text-ink !shadow-lg !font-sans",
            description: "!text-ink-2",
          },
        }}
      />
    </TooltipProvider>
  );
}
