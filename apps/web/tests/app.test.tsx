import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ActorKind, Provenance } from "@/components/badges";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { Layout } from "@/components/Layout";
import { ErrorState } from "@/components/states";
import { ApiError, request } from "@/lib/api";
import { AuthProvider } from "@/lib/auth";
import { interval } from "@/lib/format";

function wrap(ui: React.ReactNode, path = "/") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AuthProvider>
        <MemoryRouter initialEntries={[path]}>{ui}</MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("layout", () => {
  const routes = ["/", "/map", "/assets", "/telemetry", "/aerial", "/decisions", "/maintenance", "/lineage", "/reports", "/nowhere"];
  it.each(routes)("shows the fictional-facility disclosure on %s, even with the API down", async (path) => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
    wrap(
      <Routes>
        <Route element={<Layout />}>
          <Route path="*" element={<p>screen</p>} />
        </Route>
      </Routes>,
      path,
    );
    expect(screen.getByRole("note", { name: /fictional facility disclosure/i })).toHaveTextContent(/fictional/i);
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/not reachable/i));
  });
});

describe("states", () => {
  it("explains an unbuilt result with its build command and shows nothing in its place", () => {
    render(<ErrorState error={new ApiError(404, "RESULT_NOT_BUILT", "x has not been built.", "req-1", { build_with: "make gate6" })} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Result not built yet");
    expect(screen.getByText("make gate6")).toBeInTheDocument();
    expect(screen.getByText(/req-1/)).toBeInTheDocument();
  });

  it("labels scripted demonstration decisions as not made by a person", () => {
    render(<ActorKind kind="SCRIPTED_DEMO" />);
    expect(screen.getByText(/not a person/i)).toBeInTheDocument();
  });

  it("describes synthetic provenance to assistive technology", () => {
    render(<Provenance value="SYNTHETIC" />);
    expect(screen.getByLabelText(/simulated for a fictional facility/i)).toBeInTheDocument();
  });

  it("contains a screen that throws", () => {
    const Boom = () => {
      throw new Error("bad data");
    };
    vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <ErrorBoundary resetKey="a">
        <Boom />
      </ErrorBoundary>,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("bad data");
  });
});

describe("api client", () => {
  it("turns the API error shape into an ApiError with the correlation ID", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ error: { code: "WORK_ORDER_EXISTS", message: "exists", details: null } }), {
          status: 409,
          headers: { "X-Request-ID": "abc" },
        }),
      ),
    );
    await expect(request("/api/v1/work-orders", { method: "POST", body: {} })).rejects.toMatchObject({
      status: 409,
      code: "WORK_ORDER_EXISTS",
      correlationId: "abc",
    });
  });

  it("sends the idempotency key and bearer token on a write", async () => {
    sessionStorage.setItem("fieldtwin.token", "t0ken");
    const fetchMock = vi.fn().mockResolvedValue(new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const retry = "retry-0001";
    await request("/x", { method: "POST", body: { a: 1 }, idempotencyKey: retry });
    const headers = fetchMock.mock.calls[0][1].headers;
    expect(headers["Idempotency-Key"]).toBe(retry);
    expect(headers.Authorization).toBe("Bearer t0ken");
    sessionStorage.clear();
  });
});

describe("format", () => {
  it("prints undefined interval ends as a dash", () => {
    expect(interval([0.1, 0.25])).toBe("0.10 to 0.25");
    expect(interval([0.1, null])).toBe("0.10 to —");
    expect(interval(null)).toBe("—");
  });
});
