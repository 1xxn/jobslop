import { cleanup, fireEvent, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { type Hotkeys, useHotkeys } from "./hotkeys";

function Probe({ keys }: { keys: Hotkeys }) {
  useHotkeys(keys);
  return <input aria-label="field" />;
}

afterEach(cleanup);

describe("useHotkeys", () => {
  it("runs single keys and two-key sequences", () => {
    const help = vi.fn();
    const settings = vi.fn();
    render(<Probe keys={{ "?": help, "g e": settings }} />);
    fireEvent.keyDown(window, { key: "?" });
    fireEvent.keyDown(window, { key: "g" });
    fireEvent.keyDown(window, { key: "e" });
    expect(help).toHaveBeenCalledOnce();
    expect(settings).toHaveBeenCalledOnce();
  });

  it("lets a started sequence win over a single key of another component", () => {
    const settings = vi.fn();
    const star = vi.fn();
    render(
      <>
        <Probe keys={{ "g s": settings }} />
        <Probe keys={{ s: star }} />
      </>,
    );
    fireEvent.keyDown(window, { key: "g" });
    fireEvent.keyDown(window, { key: "s" });
    expect(settings).toHaveBeenCalledOnce();
    expect(star).not.toHaveBeenCalled();
    fireEvent.keyDown(window, { key: "s" });
    expect(star).toHaveBeenCalledOnce();
  });

  it("stays out of the way while typing or with modifier keys", () => {
    const jump = vi.fn();
    const { getByLabelText } = render(<Probe keys={{ j: jump }} />);
    fireEvent.keyDown(getByLabelText("field"), { key: "j" });
    fireEvent.keyDown(window, { key: "j", ctrlKey: true });
    expect(jump).not.toHaveBeenCalled();
  });
});
