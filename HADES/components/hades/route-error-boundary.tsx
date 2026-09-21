"use client";

import { Component, type ErrorInfo, type ReactNode } from "react";
import { AlertTriangle, RefreshCcw } from "lucide-react";
import { Button } from "@/components/ui/button";

type RouteErrorBoundaryProps = {
  children: ReactNode;
  resetKey: string;
};

type RouteErrorBoundaryState = {
  error: Error | null;
};

export class RouteErrorBoundary extends Component<RouteErrorBoundaryProps, RouteErrorBoundaryState> {
  state: RouteErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): RouteErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("HADES route render failed", error, info.componentStack);
  }

  componentDidUpdate(previous: RouteErrorBoundaryProps) {
    if (previous.resetKey !== this.props.resetKey && this.state.error) {
      this.setState({ error: null });
    }
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <section className="route-error-state" role="alert" aria-labelledby="route-error-title">
        <AlertTriangle aria-hidden="true" />
        <div>
          <h1 id="route-error-title">Deze pagina kon niet worden geladen</h1>
          <p>{this.state.error.message || "Onbekende renderfout."}</p>
          <Button type="button" variant="outline" onClick={() => window.location.reload()}>
            <RefreshCcw aria-hidden="true" />
            HADES herladen
          </Button>
        </div>
      </section>
    );
  }
}
