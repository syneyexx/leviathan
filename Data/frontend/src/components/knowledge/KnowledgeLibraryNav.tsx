import { KL_NAV } from "../../pages/knowledge/constants";
import type { KnowledgeLibraryWorkspace } from "../../pages/knowledge/useKnowledgeLibraryWorkspace";

/**
 * Horizontal feature nav — Bibliotheek/Ingestie/Bronnen/Vector Search stay
 * in-page views; Kennis Grafiek/Datasets/Notities/Instellingen are real
 * router navigations (see KL_NAV `kind: "route"`).
 */
export function KnowledgeLibraryNav({ ws }: { ws: KnowledgeLibraryWorkspace }) {
  return (
    <nav className="lv-v2-kl-nav" aria-label="Knowledge Library views">
      {KL_NAV.map((item) => (
        <button
          key={item.id}
          type="button"
          className={ws.view === item.id ? "is-active" : undefined}
          onClick={() => ws.onNav(item.id)}
        >
          {item.label}
        </button>
      ))}
    </nav>
  );
}
