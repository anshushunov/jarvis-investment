import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DecisionPanel } from "./DecisionPanel";
import type { ReconciliationRow } from "../api/client";

const WITH_SUGGESTION: ReconciliationRow = {
  isin: "HK0000310034",
  status: "missing_at_broker",
  ledger_quantity: "79.00000000",
  broker_quantity: "0.00000000",
  account: "Инвестиционный",
  suggestions: [{
    from_isin: "HK0000310034",
    from_quantity: "79.00000000",
    to_isin: "HK0000051877",
    to_quantity: "79.00000000",
    blocked_fully: true,
    ambiguous: false,
  }],
};

const WITHOUT_SUGGESTION: ReconciliationRow = {
  ...WITH_SUGGESTION,
  isin: "US50155Q1004",
  ledger_quantity: "-2.00000000",
  suggestions: [],
};

// Два кандидата равной величины — ровно случай, ради которого backend
// помечает гипотезы признаком ambiguous (см. backend/app/decisions/suggestions.py):
// система не вправе выбрать между ними сама.
const AMBIGUOUS: ReconciliationRow = {
  isin: "HK0000310034",
  status: "missing_at_broker",
  ledger_quantity: "10.00000000",
  broker_quantity: "0.00000000",
  account: "Инвестиционный",
  suggestions: [
    {
      from_isin: "HK0000310034", from_quantity: "10.00000000",
      to_isin: "HK0000051877", to_quantity: "10.00000000",
      blocked_fully: false, ambiguous: true,
    },
    {
      from_isin: "HK0000310034", from_quantity: "10.00000000",
      to_isin: "US0378331005", to_quantity: "10.00000000",
      blocked_fully: false, ambiguous: true,
    },
  ],
};

function renderPanel(row: ReconciliationRow) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <DecisionPanel row={row} onDone={() => {}} />
    </QueryClientProvider>,
  );
}

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

function requestBody(fetchSpy: ReturnType<typeof vi.spyOn>): Record<string, unknown> {
  const call = fetchSpy.mock.calls[0] as [string, RequestInit];
  return JSON.parse(call[1].body as string) as Record<string, unknown>;
}

describe("DecisionPanel", () => {
  // vi.spyOn(globalThis, "fetch") без восстановления между тестами возвращает
  // один и тот же мок повторно: история вызовов и заглушенный ответ одного
  // теста утекают в следующий. Восстанавливаем оригинальный fetch явно.
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("предзаполняет форму гипотезой и называет усиливающий признак", () => {
    renderPanel(WITH_SUGGESTION);

    expect(screen.getByDisplayValue("HK0000051877")).toBeInTheDocument();
    expect(screen.getByText(/заблокирован/i)).toBeInTheDocument();
  });

  it("без гипотезы предлагает выбрать действие вручную, а не подставляет чужую гипотезу", () => {
    renderPanel(WITHOUT_SUGGESTION);

    // Дискриминирующая проверка: у строки без гипотезы вид решения по
    // умолчанию — «поправить количество», а не «конвертация», и в форме нет
    // значения из чужой гипотезы (WITH_SUGGESTION).
    const kindSelect = screen.getByLabelText(/что произошло/i) as HTMLSelectElement;
    expect(kindSelect.value).toBe("ADJUSTMENT");
    expect(screen.queryByDisplayValue("HK0000051877")).not.toBeInTheDocument();
  });

  it("не отправляет решение без пояснения", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    renderPanel(WITH_SUGGESTION);

    await userEvent.click(screen.getByRole("button", { name: /подтвердить/i }));

    expect(screen.getByText(/пояснение обязательно/i)).toBeInTheDocument();
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("при нескольких гипотезах показывает обе и не выбирает за владельца", async () => {
    const user = userEvent.setup();
    renderPanel(AMBIGUOUS);

    // Обе гипотезы видны на экране.
    expect(screen.getByText(/HK0000051877/)).toBeInTheDocument();
    expect(screen.getByText(/US0378331005/)).toBeInTheDocument();

    // До выбора форма пуста ни одним из кандидатов.
    expect(screen.getByLabelText(/из какой бумаги/i)).toHaveValue("");
    expect(screen.getByLabelText(/в какую бумагу/i)).toHaveValue("");

    const radios = screen.getAllByRole("radio");
    expect(radios).toHaveLength(2);
    await user.click(radios[1]!);

    // После явного выбора подставляются значения именно выбранного кандидата.
    expect(screen.getByLabelText(/из какой бумаги/i)).toHaveValue("HK0000310034");
    expect(screen.getByLabelText(/в какую бумагу/i)).toHaveValue("US0378331005");
  });

  it("смена вида после гипотезы не отправляет скрытые поля конвертации", async () => {
    const user = userEvent.setup();
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(jsonResponse({
      id: 1, account: "Инвестиционный", kind: "ADJUSTMENT", status: "CONFIRMED",
      from_isin: null, from_quantity: null, to_isin: "HK0000051877", to_quantity: "5.00000000",
      effective_at: "2026-01-01T00:00:00Z", note: "поправка", reverts_id: null,
    }));
    renderPanel(WITH_SUGGESTION);

    await user.selectOptions(screen.getByLabelText(/что произошло/i), "ADJUSTMENT");
    await user.type(screen.getByLabelText(/в какую бумагу/i), "HK0000051877");
    await user.type(screen.getByLabelText(/сколько зачислить/i), "5");
    await user.type(screen.getByLabelText(/пояснение/i), "поправка");
    await user.click(screen.getByRole("button", { name: /подтвердить/i }));

    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const body = requestBody(fetchSpy);
    expect(body.kind).toBe("ADJUSTMENT");
    // «Сколько списать» из гипотезы конвертации на экране больше не видно —
    // и не должно уехать в теле запроса вместе с видимым полем зачисления.
    expect(body.from_isin).toBeNull();
    expect(body.from_quantity).toBeNull();
    expect(body.to_isin).toBe("HK0000051877");
    expect(body.to_quantity).toBe("5");
  });

  it("списывающая корректировка уходит на бэкенд ровно одной стороной", async () => {
    const user = userEvent.setup();
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(jsonResponse({
      id: 2, account: "Инвестиционный", kind: "ADJUSTMENT", status: "CONFIRMED",
      from_isin: "US50155Q1004", from_quantity: "2.00000000", to_isin: null, to_quantity: null,
      effective_at: "2026-01-01T00:00:00Z", note: "спишем остаток", reverts_id: null,
    }));
    renderPanel(WITHOUT_SUGGESTION);

    await user.click(screen.getByRole("radio", { name: /списать бумагу/i }));
    await user.type(screen.getByLabelText(/из какой бумаги/i), "US50155Q1004");
    await user.type(screen.getByLabelText(/сколько списать/i), "2");
    await user.type(screen.getByLabelText(/пояснение/i), "спишем остаток");
    await user.click(screen.getByRole("button", { name: /подтвердить/i }));

    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const body = requestBody(fetchSpy);
    // Ровно одна сторона — бэкенд отвергает решение, где заполнены обе или
    // ни одной (app/decisions/service.py, _validate).
    expect(body.from_isin).toBe("US50155Q1004");
    expect(body.from_quantity).toBe("2");
    expect(body.to_isin).toBeNull();
    expect(body.to_quantity).toBeNull();
  });
});
