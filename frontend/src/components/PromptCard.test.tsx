import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";
import { I18nProvider } from "@/lib/i18n";
import type { Prompt } from "@/lib/types";
import { PromptCard } from "./PromptCard";
import { TooltipProvider } from "./ui/overlays";

const wrap = (node: ReactNode) =>
  render(
    <QueryClientProvider client={new QueryClient()}>
      <I18nProvider>
        <TooltipProvider>
          <MemoryRouter>{node}</MemoryRouter>
        </TooltipProvider>
      </I18nProvider>
    </QueryClientProvider>,
  );

describe("PromptCard", () => {
  it("names each answer field by its question for screen readers", () => {
    const prompt: Prompt = {
      id: 7,
      kind: "questions",
      application_id: 11,
      created_at: "2026-10-28T12:28:02Z",
      payload: {
        title: "Flix – Infrastructure Engineer",
        questions: [
          { field_id: "0-6", question: "3+ Jahre Erfahrung mit Entra ID?", why: "", options: ["Yes", "No"] },
          { field_id: "0-9", question: "Gehaltswunsch?", why: "", options: [] },
        ],
      },
    };
    wrap(<PromptCard prompt={prompt} />);
    expect(screen.getByRole("combobox", { name: "3+ Jahre Erfahrung mit Entra ID?" })).toBeTruthy();
    expect(screen.getByRole("textbox", { name: "Gehaltswunsch?" })).toBeTruthy();
  });
});
