import crest from "../assets/crest.svg";

async function withWindow(action: "minimize" | "toggleMaximize" | "close") {
  try {
    const mod = await import("@tauri-apps/api/window");
    const window = mod.getCurrentWindow();
    if (action === "minimize") await window.minimize();
    if (action === "toggleMaximize") await window.toggleMaximize();
    if (action === "close") await window.close();
  } catch {
    if (action === "close") window.close();
  }
}

export function TitleBar() {
  return (
    <header className="titlebar">
      <div className="drag" data-tauri-drag-region onDoubleClick={() => void withWindow("toggleMaximize")}>
        <img src={crest} alt="" />
        <span>run_leviathan.exe — LEVIATHAN Backend Host</span>
      </div>
      <div className="winbtns">
        <button type="button" aria-label="Minimize" onClick={() => void withWindow("minimize")}>—</button>
        <button type="button" aria-label="Maximize" onClick={() => void withWindow("toggleMaximize")}>□</button>
        <button type="button" className="close" aria-label="Close" onClick={() => void withWindow("close")}>×</button>
      </div>
    </header>
  );
}
