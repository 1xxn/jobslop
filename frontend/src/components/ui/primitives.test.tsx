import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { Field, Input } from "./primitives";

afterEach(cleanup);

describe("Field", () => {
  it("links label and hint to the control", () => {
    render(
      <Field label="Vorname" hint="So steht es im Formular">
        <Input />
      </Field>,
    );
    const input = screen.getByLabelText("Vorname");
    expect(input.tagName).toBe("INPUT");
    expect(document.getElementById(input.getAttribute("aria-describedby") ?? "")?.textContent).toBe("So steht es im Formular");
  });

  it("keeps an id the control already has and marks errors", () => {
    render(
      <Field label="Telefon" error="Bitte mit Ländervorwahl">
        <Input id="phone" />
      </Field>,
    );
    const input = screen.getByLabelText("Telefon");
    expect(input.id).toBe("phone");
    expect(input.getAttribute("aria-invalid")).toBe("true");
  });
});
