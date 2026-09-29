import { RD_TEMPLATE_FILTERS, RD_TEMPLATES } from "../../config/research";
import type { ResearchWorkspace } from "../../hooks/useResearchWorkspace";
import { Button, Panel } from "../ui";

type Props = {
  ws: ResearchWorkspace;
};

export function ResearchTemplates({ ws }: Props) {
  const filtered = RD_TEMPLATES.filter(
    (t) => ws.templateFilter === "all" || t.category === ws.templateFilter,
  );
  const visible = ws.showAllTemplates ? filtered : filtered.slice(0, 6);

  return (
    <Panel
      className="lv-v2-research-templates"
      title="Onderzoeks Templates"
      action={
        <button
          type="button"
          className="lv-v2-brain-link"
          onClick={() => ws.setShowAllTemplates(!ws.showAllTemplates)}
        >
          {ws.showAllTemplates ? "Toon minder" : "Alles bekijken"}
        </button>
      }
    >
      <div
        ref={(el) => {
          ws.templatesRef.current = el;
        }}
      >
        <div className="lv-v2-chip-row" role="group" aria-label="Template categorieën">
          {RD_TEMPLATE_FILTERS.map((f) => (
            <button
              key={f.id}
              type="button"
              className={`lv-v2-chip${ws.templateFilter === f.id ? " is-on" : ""}`}
              aria-pressed={ws.templateFilter === f.id}
              onClick={() => ws.setTemplateFilter(f.id)}
            >
              {f.label}
            </button>
          ))}
        </div>

        {visible.length === 0 ? (
          <p className="lv-v2-muted">Geen templates in deze categorie.</p>
        ) : (
          <ul className="lv-v2-template-list">
            {visible.map((t) => (
              <li key={t.id} className={`lv-v2-template-row${ws.templateId === t.id ? " is-selected" : ""}`}>
                <div>
                  <strong>{t.labelNl}</strong>
                  <span>{t.depth} · {t.allowWeb ? "web" : "lokaal"}</span>
                </div>
                <Button variant="secondary" size="sm" onClick={() => ws.applyTemplate(t.id)}>
                  Gebruik
                </Button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </Panel>
  );
}
