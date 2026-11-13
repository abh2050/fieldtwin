export function num(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: digits });
}

export function pct(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined) return "—";
  return `${(value * 100).toFixed(digits)}%`;
}

export function usd(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return value.toLocaleString(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 0 });
}

export function when(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toISOString().replace("T", " ").replace(/:\d\d(\.\d+)?Z$/, " UTC");
}

export function short(hash: string | null | undefined, n = 12): string {
  return hash ? `${hash.slice(0, n)}…` : "—";
}

// Intervals in recorded results can hold null for an undefined end; those print as "—".
export function interval(pair: unknown, digits = 2): string {
  if (!Array.isArray(pair) || pair.length !== 2) return "—";
  const end = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v.toFixed(digits) : "—");
  return `${end(pair[0])} to ${end(pair[1])}`;
}
