import { BROWSER_DEMO } from "./mode";

// The only way the app reaches data. Every value on screen comes from one of these calls.

export type Paged<T> = { items: T[]; total: number; limit: number; offset: number };

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public correlationId: string | null,
    public details: unknown,
  ) {
    super(message);
  }
}

const TOKEN_KEY = BROWSER_DEMO ? "fieldtwin.demo.role" : "fieldtwin.token";

export function getToken(): string | null {
  try {
    return sessionStorage.getItem(TOKEN_KEY) ?? (BROWSER_DEMO ? "demo:OPERATOR" : null);
  } catch {
    return null;
  }
}

export function setToken(token: string | null) {
  try {
    if (token) sessionStorage.setItem(TOKEN_KEY, token);
    else sessionStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable: the token lives only for this page */
  }
}

export type RequestOptions = { method?: "GET" | "POST"; body?: unknown; idempotencyKey?: string; signal?: AbortSignal };

async function parse(response: Response): Promise<unknown> {
  const text = await response.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

export async function request<T>(
  path: string,
  init: RequestOptions = {},
): Promise<T> {
  if (BROWSER_DEMO) {
    const { demoRequest } = await import("./demo/client");
    return demoRequest<T>(path, init);
  }
  const headers: Record<string, string> = { Accept: "application/json" };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (init.body !== undefined) headers["Content-Type"] = "application/json";
  if (init.idempotencyKey) headers["Idempotency-Key"] = init.idempotencyKey;
  let response: Response;
  try {
    response = await fetch(path, {
      method: init.method ?? "GET",
      headers,
      body: init.body === undefined ? undefined : JSON.stringify(init.body),
      signal: init.signal,
    });
  } catch (error) {
    if ((error as Error).name === "AbortError") throw error;
    throw new ApiError(0, "API_UNREACHABLE", "The FieldTwin API is not reachable.", null, null);
  }
  const body = await parse(response);
  if (!response.ok) {
    const err = (body as { error?: { code?: string; message?: string; details?: unknown } } | null)?.error;
    throw new ApiError(
      response.status,
      err?.code ?? `HTTP_${response.status}`,
      err?.message ?? response.statusText,
      response.headers.get("X-Request-ID"),
      err?.details ?? null,
    );
  }
  if (typeof body !== "object" || body === null) {
    throw new ApiError(502, "INVALID_API_RESPONSE", "The server returned a page instead of API data. Check the API deployment or use the explicit browser demo build.", null, null);
  }
  return body as T;
}

export function query(params: Record<string, string | number | undefined | null>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

export function newIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return `ui-${crypto.randomUUID()}`;
  return `ui-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
}
