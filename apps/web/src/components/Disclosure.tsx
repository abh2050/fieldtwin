import { Info } from "lucide-react";

// Shown on every screen (it lives in the layout), and announced to assistive technology as a note.
export function Disclosure({ text }: { text: string | null }) {
  return (
    <div
      role="note"
      aria-label="Fictional facility disclosure"
      className="flex items-start gap-2 border-b border-warning/30 bg-warning/10 px-4 py-2 text-xs"
    >
      <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" aria-hidden />
      <p>
        <strong>Fictional facility.</strong>{" "}
        {text ??
          "AETHER Field is fictional. Its assets, telemetry, alarms, and work orders are synthetic; real public records are labelled as such."}
      </p>
    </div>
  );
}
