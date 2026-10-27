import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";
import { I18nProvider } from "@/lib/i18n";
import { ScoreRing, StatusBadge } from "./domain";
import { TooltipProvider } from "./ui/overlays";

const wrap = (node: ReactNode) =>
  render(
    <I18nProvider>
      <TooltipProvider>{node}</TooltipProvider>
    </I18nProvider>,
  );

describe("ScoreRing", () => {
  it("shows the rounded score", () => {
    wrap(<ScoreRing score={18.6} />);
    expect(screen.getByText("19")).toBeTruthy();
  });
});

describe("StatusBadge", () => {
  it("renders a translated status and nothing for an empty one", () => {
    const { container } = wrap(
      <>
        <StatusBadge status="submitted" />
        <StatusBadge status="" />
      </>,
    );
    expect(container.textContent).toMatch(/Sent|Gesendet/);
  });
});
