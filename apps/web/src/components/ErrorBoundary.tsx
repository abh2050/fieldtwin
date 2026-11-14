import { Component, type ErrorInfo, type ReactNode } from "react";

// A screen that throws while rendering shows this instead; the layout, and with it the fictional-
// facility disclosure and navigation, stay on screen.
export class ErrorBoundary extends Component<{ children: ReactNode; resetKey: string }, { error: Error | null }> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidUpdate(previous: { resetKey: string }) {
    if (previous.resetKey !== this.props.resetKey && this.state.error) this.setState({ error: null });
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Screen failed to render", error, info.componentStack);
  }

  render() {
    if (this.state.error)
      return (
        <div role="alert" className="m-6 rounded-md border border-destructive/40 bg-destructive/10 p-4 text-sm">
          <p className="font-medium">This screen failed to render.</p>
          <p className="mt-1 font-mono text-xs">{this.state.error.message}</p>
          <p className="mt-1 text-xs text-muted-foreground">Other screens still work. Nothing is shown in place of the missing data.</p>
        </div>
      );
    return this.props.children;
  }
}

export function webglAvailable(): boolean {
  try {
    const canvas = document.createElement("canvas");
    return !!(canvas.getContext("webgl2") || canvas.getContext("webgl"));
  } catch {
    return false;
  }
}
