// Eigenschaftsbasierte Tests (fast-check): Links, Daten und Quellnamen stammen aus fremden Job-Quellen – für jede
// Eingabe muss das Ergebnis sicher und vom erwarteten Typ sein, nicht nur für die Beispiele in utils.test.ts.
import fc from "fast-check";
import { describe, expect, it } from "vitest";
import { codeOf } from "./backendText";
import { messages } from "./messages";
import { formatDate, formatRelative, formatWhen, hostOf, parseDate, sourceName, webUrl } from "./utils";

const t = (key: keyof typeof messages.en) => messages.en[key];

const hostile = fc.constantFrom(
  "javascript:alert(1)",
  " JaVaScRiPt:alert(1)",
  "java\tscript:alert(1)",
  "data:text/html,<script>alert(1)</script>",
  "file:///etc/passwd",
  "vbscript:msgbox",
  "blob:https://example.com/x",
  "//evil.example/x",
  "https://ex ample.com",
);
const anyLink = fc.oneof(fc.string(), fc.string({ unit: "binary" }), fc.webUrl({ withQueryParameters: true }), hostile);

describe("webUrl", () => {
  it("only ever returns http(s) addresses", () => {
    fc.assert(
      fc.property(anyLink, (raw) => {
        const url = webUrl(raw);
        if (url !== undefined) expect(["http:", "https:"]).toContain(new URL(url).protocol);
      }),
    );
  });

  it("keeps every web address", () => {
    fc.assert(
      fc.property(fc.webUrl({ validSchemes: ["http", "https"] }), (raw) => {
        expect(webUrl(raw)).toBeDefined();
      }),
    );
  });
});

describe("hostOf", () => {
  it("returns a string for any input", () => {
    fc.assert(
      fc.property(anyLink, (raw) => {
        expect(typeof hostOf(raw)).toBe("string");
      }),
    );
  });
});

describe("dates from job sources", () => {
  it("never throw and always give text", () => {
    const value = fc.oneof(fc.string(), fc.date({ noInvalidDate: false }).map((d) => String(d)), fc.constant(null));
    fc.assert(
      fc.property(value, fc.constantFrom("de", "en"), (raw, lang) => {
        const d = parseDate(raw);
        expect(d === null || !Number.isNaN(d.getTime())).toBe(true);
        for (const format of [formatDate, formatRelative, formatWhen]) expect(typeof format(raw, lang)).toBe("string");
      }),
    );
  });
});

describe("sourceName", () => {
  it("is always text, also for names like constructor or __proto__", () => {
    const source = fc.oneof(
      fc.string(),
      fc.constantFrom("constructor", "portal:constructor", "__proto__", "toString:x", "portal:hasOwnProperty"),
    );
    fc.assert(
      fc.property(source, (raw) => {
        expect(typeof sourceName(raw, t)).toBe("string");
      }),
    );
  });
});

describe("codeOf", () => {
  it("returns a string code or nothing and an object of parameters", () => {
    fc.assert(
      fc.property(fc.option(fc.dictionary(fc.string(), fc.jsonValue()), { nil: undefined }), (data) => {
        const [code, params] = codeOf(data as Record<string, unknown> | undefined);
        expect(code === undefined || typeof code === "string").toBe(true);
        expect(typeof params).toBe("object");
      }),
    );
  });
});
