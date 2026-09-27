import "@fontsource/cinzel/600.css";
import "@fontsource/cinzel/700.css";
import "@fontsource/inter/400.css";
import "@fontsource/inter/500.css";
import "@fontsource/inter/600.css";
import "@fontsource/jetbrains-mono/400.css";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import "./styles/tokens.css";
import "./styles/geometry.css";
import "./styles/reference-stage.css";
import "./styles/shell.css";
import "./styles/panels.css";
import "./styles/tables.css";
import "./styles/console.css";
import "./styles/responsive.css";

const root = document.getElementById("root");
if (!root) throw new Error("root missing");

const fixtureBuild =
  import.meta.env.MODE === "fixture" && import.meta.env.VITE_LEVIATHAN_VISUAL_FIXTURE === "1";

if (fixtureBuild) {
  void import("./fixture/FixtureRoot").then(({ FixtureRoot }) => {
    createRoot(root).render(<FixtureRoot />);
  });
} else {
  createRoot(root).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
}
