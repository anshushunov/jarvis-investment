import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

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

function renderPanel(row: ReconciliationRow) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <DecisionPanel row={row} onDone={() => {}} />
    </QueryClientProvider>,
  );
}

describe("DecisionPanel", () => {
  it("предзаполняет форму гипотезой и называет усиливающий признак", () => {
    renderPanel(WITH_SUGGESTION);

    expect(screen.getByDisplayValue("HK0000051877")).toBeInTheDocument();
    expect(screen.getByText(/заблокирован/i)).toBeInTheDocument();
  });

  it("без гипотезы предлагает выбрать действие, а не молчит", () => {
    renderPanel(WITHOUT_SUGGESTION);

    expect(screen.getByLabelText(/что произошло/i)).toBeInTheDocument();
  });

  it("не отправляет решение без пояснения", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    renderPanel(WITH_SUGGESTION);

    await userEvent.click(screen.getByRole("button", { name: /подтвердить/i }));

    expect(screen.getByText(/пояснение обязательно/i)).toBeInTheDocument();
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});
