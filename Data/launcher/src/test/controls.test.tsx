import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

afterEach(() => cleanup());
import { ConfirmDialog } from "../components/ConfirmDialog";
import { RuntimeControl } from "../components/RuntimeControl";
import { controlGates } from "../domain/controls";
import { stoppedSnapshot } from "../domain/host";
import type { ControlGate } from "../types/host";

vi.mock("../lib/trace", () => ({ traceUi: () => undefined }));

const noop = () => undefined;

function renderControls(gates: Record<string, ControlGate>, onStart = noop, bridge: "READY" | "FAILED" = "READY") {
  return render(
    <RuntimeControl
      host={stoppedSnapshot()}
      gates={gates}
      bridge={bridge}
      onStart={onStart}
      onStop={noop}
      onRestart={noop}
      onSafe={noop}
      onFrontend={noop}
      onConfig={noop}
      onLogs={noop}
      onEmergency={noop}
    />,
  );
}

describe("runtime controls", () => {
  it("starts from click, Enter, and Space", async () => {
    const user = userEvent.setup();
    const onStart = vi.fn();
    renderControls(controlGates(stoppedSnapshot(), null, "READY"), onStart);
    const button = screen.getByRole("button", { name: /start leviathan/i });
    await user.click(button);
    button.focus();
    await user.keyboard("{Enter}");
    await user.keyboard(" ");
    expect(onStart).toHaveBeenCalledTimes(3);
  });

  it("does not start when the gate is disabled", async () => {
    const user = userEvent.setup();
    const onStart = vi.fn();
    const host = { ...stoppedSnapshot(), state: "PREFLIGHT" };
    renderControls(controlGates(host, null, "READY"), onStart);
    const button = screen.getByRole("button", { name: /start leviathan/i });
    expect((button as HTMLButtonElement).disabled).toBe(true);
    await user.click(button);
    expect(onStart).not.toHaveBeenCalled();
  });

  it("shows the bridge failure instead of a healthy stopped host", () => {
    renderControls(controlGates(stoppedSnapshot(), null, "FAILED"), noop, "FAILED");
    expect(screen.getByText("HOST BRIDGE FAILURE")).toBeTruthy();
    expect((screen.getByRole("button", { name: /start leviathan/i }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("names the operator controls", () => {
    renderControls(controlGates(stoppedSnapshot(), true, "READY"));
    for (const name of [/stop/i, /restart/i, /safe mode/i, /open frontend/i, /open config/i, /open logs folder/i, /emergency shutdown/i]) {
      expect(screen.getByRole("button", { name })).toBeTruthy();
    }
  });
});

describe("confirm dialog", () => {
  it("confirms and cancels", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    render(
      <ConfirmDialog
        title="LEVIATHAN is running."
        body="Stop the owned backend before exiting."
        confirmLabel="Stop Leviathan and Exit"
        cancelLabel="Cancel"
        onConfirm={onConfirm}
        onCancel={onCancel}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    await user.click(screen.getByRole("button", { name: "Stop Leviathan and Exit" }));
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });
});
