import { describe, expect, it } from "vitest";
import { messages } from "./messages";

const placeholders = (text: string) => [...text.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();

describe("messages", () => {
  it("has the same keys in German and English", () => {
    expect(Object.keys(messages.en).sort()).toEqual(Object.keys(messages.de).sort());
  });

  it("uses the same placeholders in both languages", () => {
    const mismatches = Object.keys(messages.de).filter(
      (key) =>
        placeholders(messages.de[key as keyof typeof messages.de]).join() !==
        placeholders(messages.en[key as keyof typeof messages.en]).join(),
    );
    expect(mismatches).toEqual([]);
  });

  it("has no empty texts", () => {
    for (const lang of ["de", "en"] as const) {
      const empty = Object.entries(messages[lang]).filter(([, text]) => !text.trim());
      expect(empty, lang).toEqual([]);
    }
  });
});
