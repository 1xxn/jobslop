import { type ReactNode, useEffect } from "react";
import { createBrowserRouter, Navigate, RouterProvider, useLocation } from "react-router";
import { Toaster } from "sonner";
import { AppShell } from "./components/layout/AppShell";
import { Logo } from "./components/domain";
import { TooltipProvider } from "./components/ui/overlays";
import { Spinner } from "./components/ui/primitives";
import { useStatus } from "./lib/hooks";
import { useI18n } from "./lib/i18n";
import { ActivityPage } from "./pages/Activity";
import { ApplicationDetailPage } from "./pages/ApplicationDetail";
import { ApplicationsPage } from "./pages/Applications";
import { JobsPage } from "./pages/Jobs";
import { OverviewPage } from "./pages/Overview";
import { PipelinePage } from "./pages/Pipeline";
import { SettingsPage } from "./pages/settings/Settings";
import { SetupWizard } from "./pages/setup/SetupWizard";

/** Leitet beim ersten Start in die Einrichtung. */
function SetupGate({ children }: { children: ReactNode }) {
  const { data, isLoading, isError } = useStatus();
  const location = useLocation();
  const { t } = useI18n();
  if (isLoading) {
    return (
      <div className="grid min-h-dvh place-items-center">
        <div className="flex flex-col items-center gap-4">
          <Logo />
          <Spinner />
        </div>
      </div>
    );
  }
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
  { path: "/setup", element: <SetupWizard /> },
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
