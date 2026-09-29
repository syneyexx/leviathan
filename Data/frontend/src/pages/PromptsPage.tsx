import { Link } from "react-router-dom";
import { AppShell } from "../layouts/AppShell";

/** Same presets as legacy ChatPage — copy-into-chat via location state. */
const QUICK_PROMPTS: Array<{ label: string; text: string }> = [
  {
    label: "Deep Research",
    text: "Research this topic deeply and structure the important questions first: ",
  },
  {
    label: "Analyze Data",
    text: "Analyze the following data and explain the important patterns: ",
  },
  {
    label: "Generate Code",
    text: "Help me design and implement the following code: ",
  },
  {
    label: "Create Plan",
    text: "Create a concrete step-by-step plan for: ",
  },
];

/**
 * Minimal Hades AI / Prompts V2 surface.
 * There is no separate prompt-library backend product yet — this page surfaces
 * existing chat quick-prompt presets and links to LLM gedrag settings.
 */
export function PromptsPage() {
  return (
    <AppShell
      variant="v2"
      v2Title="Hades AI / Prompts"
      v2Subtitle="Snelle starters voor chat — geen aparte prompt-bibliotheek-API."
    >
      <main className="lv-v2-page">
        <section className="lv-v2-panel" aria-labelledby="prompts-presets-title">
          <div className="lv-v2-panel__head">
            <h2 className="lv-v2-panel__title" id="prompts-presets-title">
              Quick-prompt presets
            </h2>
            <span className="lv-v2-panel__meta">Kopieert draft naar Chat</span>
          </div>
          <div className="lv-v2-panel__body">
            <p className="lv-v2-muted" style={{ marginTop: 0 }}>
              Dit zijn dezelfde snelle prompts als in Chat. Een volledige prompt library is{" "}
              <strong>geen</strong> apart backend-product — er is geen{" "}
              <code>/api/prompts</code> catalogus. Beheer van LLM-gedrag (system prompt,
              generatieparameters) zit in Settings.
            </p>
            <ul className="lv-v2-list" style={{ listStyle: "none", padding: 0, margin: 0 }}>
              {QUICK_PROMPTS.map((item) => (
                <li key={item.label}>
                  <Link
                    className="lv-v2-list-row"
                    to="/chat"
                    state={{ draft: item.text }}
                  >
                    <span>
                      <strong>{item.label}</strong>
                      <span className="lv-v2-muted" style={{ display: "block", fontSize: 12 }}>
                        {item.text.trim()}
                      </span>
                    </span>
                    <span className="lv-v2-badge lv-v2-badge--info">Open in Chat</span>
                  </Link>
                </li>
              ))}
            </ul>
            <p style={{ marginTop: 16 }}>
              <Link className="lv-v2-brain-link" to="/settings?section=llm_gedrag">
                LLM gedrag instellingen
              </Link>
            </p>
          </div>
        </section>
      </main>
    </AppShell>
  );
}
