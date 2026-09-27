import { Component, type ReactNode } from "react";

export class ErrorBoundary extends Component<{ children: ReactNode }, { error: string | null }> {
  state = { error: null as string | null };

  static getDerivedStateFromError(error: unknown) {
    return { error: error instanceof Error ? error.message : "Panel failed" };
  }

  render() {
    if (this.state.error) {
      return <div className="panel panel-error">A panel failed: {this.state.error}</div>;
    }
    return this.props.children;
  }
}
