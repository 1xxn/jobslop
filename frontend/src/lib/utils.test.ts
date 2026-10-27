import { describe, expect, it } from "vitest";
import { messages } from "./messages";
import { hostOf, initials, sourceName } from "./utils";

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
