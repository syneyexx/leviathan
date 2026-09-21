import React from "react";
import ReactDOM from "react-dom/client";
import "./app/globals.css";
import "@/components/hades/styles/lux/index.css";
import { UiStyleProvider } from "@/components/hades/ui-style";
import { HadesApp } from "@/components/hades/hades-app";

const root = document.getElementById("root");
if (!root) throw new Error("HADES root element ontbreekt.");

ReactDOM.createRoot(root).render(
  <React.StrictMode>
    <UiStyleProvider>
      <HadesApp />
    </UiStyleProvider>
  </React.StrictMode>,
);
