import crest from "../assets/crest.svg";
import { buildInfo } from "../lib/buildInfo";
import { commandFailureMessage } from "../lib/errors";

async function withWindow(action: "minimize" | "toggleMaximize" | "close") {
  const mod = await import("@tauri-apps/api/window");
  const window = mod.getCurrentWindow();
  if (action === "minimize") await window.minimize();
  if (action === "toggleMaximize") await window.toggleMaximize();
  if (action === "close") await window.close();
}

export function TitleBar({ onError }: { onError?: (message: string) => void }) {
  async function act(action: "minimize" | "toggleMaximize" | "close") {
    try {
      await withWindow(action);
    } catch (error) {
      onError?.(`Window ${action} failed: ${commandFailureMessage(error)}`);
    }
  }
  const build = `${buildInfo.version} ${buildInfo.sha} ${buildInfo.time}`.trim();
  return (
    <header className="titlebar">
      <div className="drag" data-tauri-drag-region onDoubleClick={() => void act("toggleMaximize")} title={build}>
        <img src={crest} alt="" />
        <span data-tauri-drag-region>run_leviathan.exe — LEVIATHAN Backend Host</span>
      </div>
      <div className="winbtns">
        <button type="button" aria-label="Minimize" onClick={() => void act("minimize")}>—</button>
        <button type="button" aria-label="Maximize" onClick={() => void act("toggleMaximize")}>□</button>
        <button type="button" className="close" aria-label="Close" onClick={() => void act("close")}>×</button>
      </div>
    </header>
  );
}
