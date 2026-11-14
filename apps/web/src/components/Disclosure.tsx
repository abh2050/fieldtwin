import { Info } from "lucide-react";

// Shown on every screen (it lives in the layout), and announced to assistive technology as a note.
export function Disclosure({ text }: { text: string | null }) {
  return (
    <footer
      role="note"
      aria-label="Data provenance"
      className="flex items-start gap-2 border-t bg-muted/30 px-4 py-3 text-xs text-muted-foreground"
    >
      <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
      <p>
        <strong>Data provenance.</strong>{" "}
        {text ??
          "AETHER is a fictional simulation model. Assets, telemetry, alarms, and work orders are synthetic. Public records retain their source identities; Petrobras 3W is a separate offshore benchmark."}
      </p>
    </footer>
  );
}
