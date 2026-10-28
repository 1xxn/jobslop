import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it } from "vitest";
import { codeOf, useBackendText } from "./backendText";
import { I18nProvider, useI18n } from "./i18n";

const wrapper = ({ children }: { children: ReactNode }) => <I18nProvider>{children}</I18nProvider>;

function setup(lang: "de" | "en") {
  const hook = renderHook(() => ({ text: useBackendText(), i18n: useI18n() }), { wrapper });
  act(() => hook.result.current.i18n.setLang(lang));
  return hook;
}

afterEach(() => localStorage.clear());

describe("useBackendText", () => {
  it("translates codes with parameters", () => {
    const { result } = setup("en");
    expect(result.current.text("crawl.done", { run: 6, new: 18, queued: 5 }, "Crawl #6 …")).toBe(
      "Search #6: 18 new jobs, 5 up next",
    );
  });

  it("translates status, mode and counts parameters", () => {
    const { result } = setup("en");
    expect(result.current.text("run.finished", { counts: { submitted: 3, needs_input: 1 } }, "")).toBe(
      "Application run finished: 3× Sent, 1× Question",
    );
    expect(result.current.text("run.started", { mode: "dry-run" }, "")).toContain("(");
    expect(result.current.text("guard.applied", { id: 4, status: "interview" }, "")).toBe(
      "Already applied (#4, Interview)",
    );
  });

  it("keeps the plain text for unknown or missing codes", () => {
    const { result } = setup("en");
    expect(result.current.text(undefined, {}, "Einrichtung abgeschlossen")).toBe("Einrichtung abgeschlossen");
    expect(result.current.text("does.not.exist", {}, "Klartext")).toBe("Klartext");
  });

  it("speaks German when German is chosen", () => {
    const { result } = setup("de");
    expect(result.current.text("setup.done", {}, "")).toBe("Einrichtung abgeschlossen");
  });
});

describe("codeOf", () => {
  it("reads code and params from activity data", () => {
    expect(codeOf({ code: "setup.done", params: { a: 1 } })).toEqual(["setup.done", { a: 1 }]);
    expect(codeOf({ submitted: 3 })).toEqual([undefined, {}]);
    expect(codeOf(undefined)).toEqual([undefined, {}]);
  });
});
