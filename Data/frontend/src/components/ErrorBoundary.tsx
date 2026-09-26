import { Component, type ErrorInfo, type ReactNode } from "react";

type Props = {
  children: ReactNode;
  fallbackTitle?: string;
};

type State = {
  error: Error | null;
};

/** Route/app error boundary — preserves LEVIATHAN chrome, no silent blank page. */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("[LEVIATHAN] UI error boundary", error, info.componentStack);
  }

  render(): ReactNode {
    if (!this.state.error) return this.props.children;
    return (
      <div className="lv-error-boundary" role="alert">
        <h1>{this.props.fallbackTitle ?? "Something went wrong"}</h1>
        <p>The page failed to render. Your session data was not discarded.</p>
        <pre>{this.state.error.message}</pre>
        <button type="button" className="lv-btn" onClick={() => this.setState({ error: null })}>
          Try again
        </button>
      </div>
    );
  }
}
