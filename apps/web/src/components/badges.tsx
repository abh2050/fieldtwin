import { Badge } from "./ui/badge";

const PROVENANCE: Record<string, { variant: "default" | "secondary" | "warning" | "success" | "outline"; text: string }> = {
  OBSERVED: { variant: "success", text: "Observed: real public record" },
  DERIVED: { variant: "secondary", text: "Derived from real records" },
  REPLAYED: { variant: "secondary", text: "Replayed real data" },
  SYNTHETIC: { variant: "warning", text: "Synthetic: simulated for a fictional facility" },
  INFERRED: { variant: "default", text: "Inferred by a model from synthetic data" },
};

export function Provenance({ value }: { value: string | null | undefined }) {
  if (!value) return null;
  const p = PROVENANCE[value] ?? { variant: "outline" as const, text: value };
  return (
    <Badge variant={p.variant} title={p.text} aria-label={`Provenance: ${p.text}`}>
      {value}
    </Badge>
  );
}

export function ActorKind({ kind }: { kind: string }) {
  if (kind === "SCRIPTED_DEMO")
    return (
      <Badge variant="warning" title="A scripted demonstration step standing in for a person. Not a human decision.">
        SCRIPTED DEMO · not a person
      </Badge>
    );
  if (kind === "SYSTEM") return <Badge variant="secondary">SYSTEM</Badge>;
  return <Badge variant="success">HUMAN</Badge>;
}

const STATUS: Record<string, "default" | "secondary" | "warning" | "success" | "destructive" | "outline"> = {
  RECOMMENDED: "default",
  APPROVED: "success",
  COMPLETED: "secondary",
  REJECTED: "destructive",
  NEEDS_EVIDENCE: "warning",
  REQUESTED: "default",
};

export function Status({ value }: { value: string }) {
  return <Badge variant={STATUS[value] ?? "outline"}>{value.replace(/_/g, " ")}</Badge>;
}

export function Band({ value }: { value: string | null }) {
  if (!value) return <Badge variant="outline">no dispatch</Badge>;
  return <Badge variant={value === "P1" ? "destructive" : value === "P2" ? "warning" : "secondary"}>{value}</Badge>;
}

export function RealRecord() {
  return (
    <Badge variant="success" title="A real public record. It does not describe AETHER Field.">
      REAL PUBLIC RECORD
    </Badge>
  );
}
