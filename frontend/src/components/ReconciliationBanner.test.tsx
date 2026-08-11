import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ReconciliationBanner } from "./ReconciliationBanner";
import type { Decision, ReconciliationRow } from "../api/client";

const DECISION: Decision = {
  id: 1,
  account: "Инвестиционный",
  kind: "CONVERSION",
  status: "CONFIRMED",
  from_isin: "HK0000310034",
  from_quantity: "79.00000000",
  to_isin: "HK0000051877",
  to_quantity: "79.00000000",
  effective_at: "2026-08-10T00:00:00Z",
  note: "Смена ISIN гонконгского ETF",
  reverts_id: null,
};

const ROW: ReconciliationRow = {
  isin: "HK0000310034",
  status: "missing_at_broker",
  ledger_quantity: "79.00000000",
  broker_quantity: "0.00000000",
  account: "Инвестиционный",
  suggestions: [],
};

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

function renderBanner(rows: ReconciliationRow[], error: string | null = null) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ReconciliationBanner rows={rows} error={error} />
    </QueryClientProvider>,
  );
}

describe("ReconciliationBanner", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("показывает журнал решений, когда расхождений не осталось", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(jsonResponse([DECISION]));

    renderBanner([]);

    // Расхождение, закрытое решением, исчезает — а пояснение владельца остаётся
    // единственным ответом на вопрос «откуда это количество». Ради этого и
    // заводился GET /api/decisions.
    expect(await screen.findByText(/Смена ISIN гонконгского ETF/)).toBeInTheDocument();
  });

  it("показывает журнал решений, не требуя разворачивать список расхождений", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(jsonResponse([DECISION]));

    renderBanner([ROW]);

    // Список расхождений свёрнут по умолчанию, и решения не должны прятаться
    // вместе с ним.
    expect(await screen.findByText(/Смена ISIN гонконгского ETF/)).toBeInTheDocument();
  });

  it("отменяет подтверждённое решение с пояснением", async () => {
    const user = userEvent.setup();
    const fetchSpy = vi.spyOn(globalThis, "fetch")
      .mockResolvedValue(jsonResponse([DECISION]));

    renderBanner([]);
    await screen.findByText(/Смена ISIN гонконгского ETF/);

    await user.click(screen.getByRole("button", { name: /отменить решение №1/i }));
    await user.type(screen.getByLabelText(/почему отменяем/i), "Ошибся бумагой");
    await user.click(screen.getByRole("button", { name: /^отменить$/i }));

    await waitFor(() => {
      const revertCall = fetchSpy.mock.calls.find(
        ([url]) => typeof url === "string" && url.includes("/decisions/1/revert"),
      );
      expect(revertCall).toBeDefined();
      const init = revertCall![1] as RequestInit;
      expect(init.method).toBe("POST");
      expect(JSON.parse(init.body as string)).toEqual({ note: "Ошибся бумагой" });
    });
  });

  it("не отменяет решение без пояснения", async () => {
    const user = userEvent.setup();
    const fetchSpy = vi.spyOn(globalThis, "fetch")
      .mockResolvedValue(jsonResponse([DECISION]));

    renderBanner([]);
    await screen.findByText(/Смена ISIN гонконгского ETF/);

    await user.click(screen.getByRole("button", { name: /отменить решение №1/i }));
    await user.click(screen.getByRole("button", { name: /^отменить$/i }));

    expect(screen.getByText(/пояснение обязательно/i)).toBeInTheDocument();
    expect(fetchSpy.mock.calls.some(
      ([url]) => typeof url === "string" && url.includes("/revert"),
    )).toBe(false);
  });

  it("не предлагает отменять уже отменённое решение", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(jsonResponse([
      { ...DECISION, status: "REVERTED" },
    ]));

    renderBanner([]);
    await screen.findByText(/Смена ISIN гонконгского ETF/);

    // Служба откажет: отменить можно только подтверждённое решение
    // (app/decisions/service.py, revert_decision). Кнопку, ведущую в отказ,
    // показывать нечестно.
    expect(screen.queryByRole("button", { name: /отменить решение/i })).not.toBeInTheDocument();
  });
});
