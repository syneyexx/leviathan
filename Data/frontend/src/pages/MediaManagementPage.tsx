import { media } from "../assets/media";
import { AppShell } from "../layouts/AppShell";
import { useAppToast } from "../state/useAppToast";

const LIBRARIES = [
  { title: "Cinematic Still Library", meta: "1,248 assets · synced", tone: "gold" },
  { title: "Agent Avatar Pack", meta: "64 portraits · elite set", tone: "cyan" },
  { title: "Market Motion Reels", meta: "128 clips · 4K", tone: "green" },
  { title: "Brand Emblem Vault", meta: "42 marks · approved", tone: "gold" },
] as const;

export function MediaManagementPage() {
  const toast = useAppToast();

  return (
    <AppShell
      activeMode="explore"
      modeLabel="Media Mode"
      searchPlaceholder="Search media, clips, avatars, brand marks..."
      layout="wide"
      pageClass="lv-app--media"
    >
      <main className="lv-main lv-media-main">
        <section className="lv-page-hero">
          <div className="lv-hero-media">
            <img src={media.architectureBg} alt="" width={1400} height={380} />
          </div>
          <div className="lv-hero-shade" />
          <div className="lv-hero-content">
            <div className="lv-hero-kicker">
              <span />
              Capture. Curate. Compose.
              <span />
            </div>
            <h1 className="lv-hero-title">Media Control</h1>
            <p className="lv-page-quote">“Every frame is a memory the system can use.”</p>
          </div>
          <div className="lv-hero-rail" aria-hidden="true">
            <span>Ingest</span>
            <span>Tag</span>
            <span>Edit</span>
            <span>Publish</span>
          </div>
        </section>

        <div className="lv-action-row" style={{ gridTemplateColumns: "repeat(4, minmax(0, 1fr))" }}>
          {["Upload Media", "New Collection", "Generate Still", "Review Queue"].map((label) => (
            <button key={label} className="lv-action-card" type="button" onClick={() => toast(label)}>
              <strong>{label}</strong>
              <small>Mock media workflow</small>
            </button>
          ))}
        </div>

        <section className="lv-panel" style={{ padding: 12 }}>
          <div className="lv-section-label">Libraries</div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0,1fr))", gap: 8, marginTop: 8 }}>
            {LIBRARIES.map((item) => (
              <button
                key={item.title}
                type="button"
                className="lv-action-card"
                onClick={() => toast(item.title)}
                style={{ minHeight: 72 }}
              >
                <strong>{item.title}</strong>
                <small>{item.meta}</small>
              </button>
            ))}
          </div>
        </section>

        <p className="lv-footer-quote">“Discipline creates freedom — even in the archive.” — LEVIATHAN</p>
      </main>
    </AppShell>
  );
}
