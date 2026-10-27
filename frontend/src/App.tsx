import { lazy, type ReactNode, Suspense, useEffect } from "react";
import { createBrowserRouter, Navigate, RouterProvider, useLocation } from "react-router";
import { Toaster } from "sonner";
import { AppShell } from "./components/layout/AppShell";
import { Logo } from "./components/domain";
import { TooltipProvider } from "./components/ui/overlays";
import { Spinner } from "./components/ui/primitives";
import { useStatus } from "./lib/hooks";
import { useI18n } from "./lib/i18n";

// Jede Seite ist ein eigener Chunk – geladen wird nur, was du öffnest.
const ActivityPage = lazy(() => import("./pages/Activity").then((m) => ({ default: m.ActivityPage })));
const ApplicationDetailPage = lazy(() =>
  import("./pages/ApplicationDetail").then((m) => ({ default: m.ApplicationDetailPage })),
);
const ApplicationsPage = lazy(() => import("./pages/Applications").then((m) => ({ default: m.ApplicationsPage })));
const JobsPage = lazy(() => import("./pages/Jobs").then((m) => ({ default: m.JobsPage })));
const OverviewPage = lazy(() => import("./pages/Overview").then((m) => ({ default: m.OverviewPage })));
const PipelinePage = lazy(() => import("./pages/Pipeline").then((m) => ({ default: m.PipelinePage })));
const SettingsPage = lazy(() => import("./pages/settings/Settings").then((m) => ({ default: m.SettingsPage })));
const SetupWizard = lazy(() => import("./pages/setup/SetupWizard").then((m) => ({ default: m.SetupWizard })));

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
  const { data, isLoading, isError } = useStatus();
  const location = useLocation();
  const { t } = useI18n();
  if (isLoading) return <FullPageSpinner />;
  if (isError) {
    return (
      <div className="grid min-h-dvh place-items-center p-6 text-center">
        <div>
          <Logo />
          <p className="mt-4 text-fg-muted">{t("app.offline")}</p>
        </div>
      </div>
    );
  }
  if (data && !data.setup_completed && !location.pathname.startsWith("/setup")) {
    return <Navigate to="/setup" replace />;
  }
  return <>{children}</>;
}

function Gated({ children }: { children: ReactNode }) {
  return <SetupGate>{children}</SetupGate>;
}

const router = createBrowserRouter([
  {
    path: "/setup",
    element: (
      <Suspense fallback={<FullPageSpinner />}>
        <SetupWizard />
      </Suspense>
    ),
  },
  {
    element: (
      <Gated>
        <AppShell />
      </Gated>
    ),
    children: [
      { index: true, element: <OverviewPage /> },
      { path: "jobs", element: <JobsPage /> },
      { path: "pipeline", element: <PipelinePage /> },
      { path: "applications", element: <ApplicationsPage /> },
      { path: "applications/:id", element: <ApplicationDetailPage /> },
      { path: "activity", element: <ActivityPage /> },
      { path: "settings", element: <SettingsPage /> },
      { path: "settings/:tab", element: <SettingsPage /> },
      { path: "*", element: <Navigate to="/" replace /> },
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
            toast: "!rounded-lg !border !border-border !bg-surface !text-fg !shadow-lg !font-sans",
            description: "!text-fg-muted",
          },
        }}
      />
    </TooltipProvider>
  );
}
