import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { AppShell } from "../layouts/AppShell";
import { useAppToast } from "../state/useAppToast";

export function CodingPage() {
  const toast = useAppToast();
  const navigate = useNavigate();
  const [prompt, setPrompt] = useState("");

  const openInChat = () => {
    const text = prompt.trim();
    if (!text) {
      navigate("/chat");
      return;
    }
    navigate("/chat", { state: { draft: `Generate code for: ${text}` } });
  };

  return (
    <AppShell
      activeMode="explore"
      modeLabel="Coding Mode"
      searchPlaceholder="Search code, plans, artifacts..."
      layout="wide"
    >
      <main className="lv-main">

        <section className="lv-panel lv-card" style={{ padding: 16 }}>
          <div className="lv-section-label">Coding</div>
          <p className="lv-muted">Plan, generate, and verify code through the shared Leviathan runtime.</p>
          <div className="lv-prompt" style={{ marginTop: 12 }}>
            <textarea
              rows={2}
              placeholder="Describe what you want to build..."
              aria-label="Coding prompt"
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  openInChat();
                }
              }}
            />
            <button className="lv-prompt-send lv-button-primary" type="button" aria-label="Open in chat" onClick={openInChat}>
              <svg className="lv-icon" viewBox="0 0 24 24">
                <path d="M5 12h12M13 6l6 6-6 6" />
              </svg>
            </button>
          </div>
          <div className="lv-feature-row" style={{ marginTop: 12 }}>
            {["Scaffold project", "Review diff", "Write tests", "Fix bug"].map((label) => (
              <button key={label} className="lv-feature" type="button" onClick={() => toast(label)}>
                <span className="lv-feature-copy">
                  <strong>{label}</strong>
                  <small>Coding workflow</small>
                </span>
              </button>
            ))}
          </div>
        </section>
      </main>
    </AppShell>
  );
}
