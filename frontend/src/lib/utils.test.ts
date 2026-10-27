import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { messages } from "./messages";
import { formatWhen, hostOf, initials, sourceName } from "./utils";

const t = (key: keyof typeof messages.en) => messages.en[key];

describe("sourceName", () => {
  it("names portals and boards readably", () => {
    expect(sourceName("portal:linkedin", t)).toBe("LinkedIn");
    expect(sourceName("portal:indeed", t)).toBe("Indeed");
    expect(sourceName("greenhouse:gitlab", t)).toBe("Greenhouse");
    expect(sourceName("arbeitsagentur", t)).toBe("Arbeitsagentur");
    expect(sourceName("workday:tenant/Careers", t)).toBe("Workday");
  });

  it("falls back to the raw source", () => {
    expect(sourceName("seed:linkedin", t)).toBe("Import");
    expect(sourceName("generic:zalando:ab12", t)).toBe("Careers page");
    expect(sourceName("something-new", t)).toBe("something-new");
  });
});

describe("hostOf / initials", () => {
  it("strips www and survives garbage", () => {
    expect(hostOf("https://www.example.com/jobs/1")).toBe("example.com");
    expect(hostOf("not a url")).toBe("");
  });

  it("builds avatar initials", () => {
    expect(initials("Brandenburg Data AG")).toBe("BD");
  });
});

describe("formatWhen", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2026, 9, 27, 14, 0));
  });
  afterEach(() => vi.useRealTimers());

  it("says today and tomorrow in words", () => {
    expect(formatWhen(new Date(2026, 9, 27, 18, 0).toISOString(), "de")).toBe("heute 18:00");
    expect(formatWhen(new Date(2026, 9, 28, 8, 0).toISOString(), "de")).toBe("morgen 08:00");
    expect(formatWhen(new Date(2026, 9, 28, 8, 0).toISOString(), "en")).toMatch(/^tomorrow 0?8:00/);
  });

  it("uses the weekday within a week and is empty without a date", () => {
    expect(formatWhen(new Date(2026, 9, 30, 8, 0).toISOString(), "de")).toMatch(/^Fr\.? 08:00$/);
    expect(formatWhen(null, "de")).toBe("");
  });
});
