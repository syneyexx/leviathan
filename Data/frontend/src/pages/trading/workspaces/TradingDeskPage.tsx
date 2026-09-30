/**
 * WAVE 5/6 — Trading Desk is now a fully native, pixel-exact page.
 * No PaperTradingPage / PortefeuillePage / BrokerTradingPage embedding, and no
 * AgentWalletsPanel / PaperDeploymentAdvancedPanel legacy panels; paper
 * execution, wallets, positions/orders, RiskGuard, paper deployments, and the
 * broker boundary all live natively under `workspaces/tradingDesk/`.
 */
export { TradingDeskPage } from "./tradingDesk/TradingDeskPage";
