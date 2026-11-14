import { useQuery } from "@tanstack/react-query";
import {
  Activity, BarChart3, ClipboardList, Database, FileText, Gauge, LogIn, LogOut, Map, Network, Plane, Wrench,
} from "lucide-react";
import { useState, type FormEvent } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { ApiError, request } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Health, Me } from "@/lib/types";
import { cn } from "@/lib/utils";
import { BROWSER_DEMO } from "@/lib/mode";
import { DemoControls } from "./DemoControls";
import { Disclosure } from "./Disclosure";
import { ErrorBoundary } from "./ErrorBoundary";
import { Button } from "./ui/button";
import { Input } from "./ui/input";

const NAV = [
  { to: "/", label: "Overview", icon: Gauge },
  { to: "/map", label: "Field Map", icon: Map },
  { to: "/assets", label: "Asset Explorer", icon: Network },
  { to: "/telemetry", label: "Telemetry Lab", icon: Activity },
  { to: "/aerial", label: "Aerial Inspection", icon: Plane },
  { to: "/decisions", label: "Decision Center", icon: ClipboardList },
  { to: "/maintenance", label: "Maintenance", icon: Wrench },
  { to: "/lineage", label: "Data Lineage", icon: Database },
  { to: "/reports", label: "Experiment Reports", icon: FileText },
];

export function useMe() {
  const { token } = useAuth();
  return useQuery({ queryKey: ["me", token], queryFn: () => request<Me>("/api/v1/me"), enabled: !!token, retry: false });
}

function SignIn() {
  const { token, signIn, signOut } = useAuth();
  const me = useMe();
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState("");
  if (BROWSER_DEMO) return <DemoControls />;
  if (token) {
    const failed = me.isError && me.error instanceof ApiError && me.error.status === 401;
    return (
      <div className="flex items-center gap-2 text-xs">
        {me.data && (
          <span>
            <span className="font-medium">{me.data.actor_id}</span>{" "}
            <span className="text-muted-foreground">{me.data.role.replace(/_/g, " ").toLowerCase()}</span>
          </span>
        )}
        {failed && <span className="text-destructive">token not recognised</span>}
        <Button size="sm" variant="ghost" onClick={signOut} aria-label="Sign out">
          <LogOut className="h-3.5 w-3.5" aria-hidden /> Sign out
        </Button>
      </div>
    );
  }
  if (!open)
    return (
      <Button size="sm" variant="outline" onClick={() => setOpen(true)}>
        <LogIn className="h-3.5 w-3.5" aria-hidden /> Sign in to act
      </Button>
    );
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (value.trim()) signIn(value.trim());
    setOpen(false);
    setValue("");
  };
  return (
    <form onSubmit={submit} className="flex items-center gap-2">
      <label htmlFor="token" className="sr-only">Bearer token</label>
      <Input id="token" type="password" autoComplete="off" placeholder="Bearer token (make app-tokens)" value={value} onChange={(e) => setValue(e.target.value)} className="h-8 w-64 text-xs" />
      <Button size="sm" type="submit">Sign in</Button>
    </form>
  );
}

function HealthDot({ health }: { health: Health | undefined; }) {
  if (health?.status === "demo") return <span className="text-xs font-medium text-primary">Browser simulation · session only</span>;
  const ok = health?.status === "ok";
  return (
    <span className="flex items-center gap-1.5 text-xs text-muted-foreground" title={health ? JSON.stringify(health.checks) : "checking"}>
      <span className={cn("h-2 w-2 rounded-full", health ? (ok ? "bg-success" : "bg-destructive") : "bg-muted-foreground")} aria-hidden />
      {health ? (ok ? "API and database up" : "Degraded: database unreachable") : "Checking service"}
    </span>
  );
}

export function Layout() {
  const health = useQuery({
    queryKey: ["health"],
    queryFn: async () => {
      if (BROWSER_DEMO) return request<Health>("/health");
      // /health answers 503 with a body when degraded; keep that body.
      const r = await fetch("/health");
      if (!r.ok && r.status !== 503) throw new ApiError(r.status, "HEALTH_FAILED", r.statusText, null, null);
      return (await r.json()) as Health;
    },
    refetchInterval: 30_000,
    retry: false,
  });
  const unreachable = health.isError;
  const location = useLocation();
  const navigate = useNavigate();
  return (
    <div className="flex min-h-screen flex-col">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-card focus:p-2">
        Skip to content
      </a>
      <div className="flex flex-1">
        <nav aria-label="Main" className="hidden w-56 shrink-0 border-r bg-card md:block">
          <div className="flex items-center gap-2 px-4 py-4">
            <BarChart3 className="h-5 w-5 text-primary" aria-hidden />
            <div>
              <div className="text-sm font-semibold">FieldTwin</div>
              <div className="text-[11px] text-muted-foreground">Operations workspace</div>
            </div>
          </div>
          <ul className="space-y-0.5 px-2">
            {NAV.map(({ to, label, icon: Icon }) => (
              <li key={to}>
                <NavLink
                  to={to}
                  end={to === "/"}
                  className={({ isActive }) =>
                    cn("flex items-center gap-2 rounded-md px-2.5 py-1.5 text-sm", isActive ? "bg-accent font-medium" : "text-muted-foreground hover:bg-accent/60")
                  }
                >
                  <Icon className="h-4 w-4" aria-hidden /> {label}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>
        <div className="flex min-w-0 flex-1 flex-col">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b bg-card px-4 py-2">
            <select
              aria-label="Navigate"
              className="rounded border bg-card px-2 py-1 text-sm md:hidden"
              value={location.pathname}
              onChange={(e) => navigate(e.target.value)}
            >
              {NAV.map((n) => <option key={n.to} value={n.to}>{n.label}</option>)}
            </select>
            {unreachable ? (
              <span role="alert" className="text-xs text-destructive">Degraded: the FieldTwin API is not reachable.</span>
            ) : (
              <HealthDot health={health.data} />
            )}
            <SignIn />
          </div>
          {BROWSER_DEMO && (
            <div role="note" aria-label="Browser demo mode" className="border-b bg-primary/5 px-4 py-3 text-xs">
              <strong>Simulation demo.</strong> Replay stored synthetic scenarios and try the work-order workflow. Role selection demonstrates the controls; it is not sign-in. Changes stay in this browser session.
            </div>
          )}
          <main id="main" className="flex-1">
            <ErrorBoundary resetKey={location.pathname}>
              <Outlet />
            </ErrorBoundary>
          </main>
        </div>
      </div>
      <Disclosure text={health.data?.disclosure ?? null} />
    </div>
  );
}
