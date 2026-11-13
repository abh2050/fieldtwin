import type { UseQueryResult } from "@tanstack/react-query";
import { AlertTriangle, Inbox, Loader2, WifiOff } from "lucide-react";
import type { ReactNode } from "react";
import { ApiError } from "@/lib/api";

export function Loading({ label = "Loading" }: { label?: string }) {
  return (
    <div role="status" aria-live="polite" className="flex items-center gap-2 p-6 text-sm text-muted-foreground">
      <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> {label}…
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return (
    <div className="flex items-start gap-2 rounded-md border border-dashed p-4 text-sm text-muted-foreground">
      <Inbox className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
      <div>{children}</div>
    </div>
  );
}

export function ErrorState({ error }: { error: unknown }) {
  const e = error instanceof ApiError ? error : null;
  const build = (e?.details as { build_with?: string } | null)?.build_with;
  const unavailable = e && (e.status === 0 || e.status === 503);
  const notBuilt = e?.code === "RESULT_NOT_BUILT";
  return (
    <div
      role="alert"
      className={
        notBuilt
          ? "rounded-md border border-warning/40 bg-warning/10 p-4 text-sm"
          : "rounded-md border border-destructive/40 bg-destructive/10 p-4 text-sm"
      }
    >
      <div className="flex items-center gap-2 font-medium">
        {unavailable ? <WifiOff className="h-4 w-4" aria-hidden /> : <AlertTriangle className="h-4 w-4" aria-hidden />}
        {notBuilt ? "Result not built yet" : unavailable ? "Service degraded" : "Request failed"}
      </div>
      <p className="mt-1">{e?.message ?? String(error)}</p>
      {build && (
        <p className="mt-1 text-xs">
          Build it with <code className="rounded bg-muted px-1 font-mono">{build}</code>. Nothing is shown in its place.
        </p>
      )}
      {e && (
        <p className="mt-1 font-mono text-[11px] text-muted-foreground">
          {e.code}
          {e.correlationId ? ` · request ${e.correlationId}` : ""}
        </p>
      )}
    </div>
  );
}

// Renders loading, error, and (optionally) empty states, then the content.
export function QueryState<T>({
  q,
  empty,
  isEmpty,
  children,
  label,
}: {
  q: UseQueryResult<T>;
  empty?: ReactNode;
  isEmpty?: (data: T) => boolean;
  children: (data: T) => ReactNode;
  label?: string;
}) {
  if (q.isPending) return <Loading label={label} />;
  if (q.isError) return <ErrorState error={q.error} />;
  if (empty && isEmpty?.(q.data)) return <Empty>{empty}</Empty>;
  return <>{children(q.data)}</>;
}
