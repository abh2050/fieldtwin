import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useAuth } from "@/lib/auth";
import { ErrorState } from "./states";
import { Button } from "./ui/button";
import { Select } from "./ui/input";

export function DemoControls() {
  const { token, signIn } = useAuth();
  const client = useQueryClient();
  const [error, setError] = useState<unknown>(null);
  const [resetting, setResetting] = useState(false);
  const reset = async () => {
    setError(null); setResetting(true);
    try {
      const { resetDemoSession } = await import("@/lib/demo/client");
      await resetDemoSession();
      signIn("demo:OPERATOR");
      await client.invalidateQueries();
    } catch (err) { setError(err); }
    finally { setResetting(false); }
  };
  return (
    <div className="flex flex-wrap items-center gap-2">
      <label htmlFor="demo-role" className="text-xs text-muted-foreground">Demo role</label>
      <Select id="demo-role" value={token ?? "demo:OPERATOR"} onChange={(e) => signIn(e.target.value)} className="h-8 w-48 text-xs" title="Demonstration role selection; this is not authentication">
        <option value="demo:VIEWER">Viewer</option>
        <option value="demo:OPERATOR">Operator</option>
        <option value="demo:MAINTENANCE_SUPERVISOR">Maintenance supervisor</option>
      </Select>
      <Button size="sm" variant="outline" onClick={reset} disabled={resetting}>Reset demo</Button>
      {error !== null && <ErrorState error={error} />}
    </div>
  );
}
