import { useNavigate } from "react-router-dom";
import { media } from "../../assets/media";
import { Button } from "../ui";

export function DashboardHero() {
  const navigate = useNavigate();

  return (
    <section className="lv-v2-hero" aria-label="Welkom">
      <div className="lv-v2-hero__media">
        <img src={media.hero} alt="" width={1600} height={440} />
      </div>
      <div className="lv-v2-hero__shade" />
      <div className="lv-v2-hero__content">
        <h2 className="lv-v2-hero__title">Welkom bij Leviathan</h2>
        <p className="lv-v2-hero__copy">
          Jouw persoonlijke AI command center. Monitor, beheer en schaal je volledige AI
          infrastructuur, van lokale modellen tot autonome agents.
        </p>
        <div className="lv-v2-hero__actions">
          <Button variant="primary" onClick={() => navigate("/tasks")}>
            + Nieuwe taak starten
          </Button>
          <Button variant="secondary" onClick={() => navigate("/performance")}>
            Systeem bekijken
          </Button>
        </div>
      </div>
      <blockquote className="lv-v2-hero__quote">
        “Meer dan AI.
        <br />
        Een ecosysteem voor intelligentie.”
        <cite>— LEVIATHAN</cite>
      </blockquote>
    </section>
  );
}
