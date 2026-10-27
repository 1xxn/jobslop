import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";
import { I18nProvider } from "@/lib/i18n";
import { Score, StatusLabel } from "./domain";
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
