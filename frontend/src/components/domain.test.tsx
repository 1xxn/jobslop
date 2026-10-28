import { fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api";
import { I18nProvider } from "@/lib/i18n";
import { LoadError, Pending, Score, StatusLabel } from "./domain";
import { TooltipProvider } from "./ui/overlays";

const wrap = (node: ReactNode) =>
  render(
    <I18nProvider>
      <TooltipProvider>{node}</TooltipProvider>
    </I18nProvider>,
  );

describe("Score", () => {
  it("shows the rounded score", () => {
    wrap(<Score score={18.6} />);
    expect(screen.getByText("19")).toBeTruthy();
  });
});

describe("StatusLabel", () => {
  it("renders a translated status and nothing for an empty one", () => {
    const { container } = wrap(
      <>
        <StatusLabel status="submitted" />
        <StatusLabel status="" />
      </>,
    );
    expect(container.textContent).toMatch(/Sent|Gesendet/);
  });
});

describe("LoadError", () => {
  it("says why loading failed and offers a retry", () => {
    const retry = vi.fn();
    wrap(<LoadError error={new ApiError(0, "x", "api.offline")} onRetry={retry} />);
    expect(screen.getByRole("alert").textContent).toMatch(/jobslop/);
    fireEvent.click(screen.getByRole("button"));
    expect(retry).toHaveBeenCalledOnce();
  });

  it("shows a placeholder while loading and the error once it fails", () => {
    const loading = { isError: false, error: null, refetch: vi.fn() };
    const { container, rerender } = wrap(<Pending query={loading} className="h-10" />);
    expect(container.querySelector("[role=alert]")).toBeNull();
    expect(container.querySelector(".h-10")).toBeTruthy();
    rerender(
      <I18nProvider>
        <Pending query={{ ...loading, isError: true, error: new Error("kaputt") }} />
      </I18nProvider>,
    );
    expect(container.querySelector("[role=alert]")?.textContent).toContain("kaputt");
  });
});
