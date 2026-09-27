import { tradingHeroes } from "../../../assets/tradingAssets";
import { TradingHero } from "../shared";

export function PaperTradingHero() {
  return (
    <TradingHero
      title="PAPER TRADING"
      kicker="SIMULATE. ORCHESTRATE. OPTIMIZE."
      quote="Test with conviction. Trade with wisdom."
      image={tradingHeroes.paper}
      imageOnly={false}
      objectPosition="center 35%"
      rails={["AGENTS", "STRATEGIES", "SIMULATIONS", "REAL MARKETS", "GREATER INSIGHT"]}
    />
  );
}
