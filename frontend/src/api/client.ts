// Бэкенд на хосте слушает порт 8001 (порт 8000 занят посторонним контейнером).
const BASE = "http://localhost:8001/api";

export interface Overview {
  // Рублёвая часть портфеля: позиции в других валютах сюда не входят, пока нет
  // пересчёта по курсам. Их итоги — в by_currency.
  total_value: string;
  positions_value: string;
  by_asset_class: Record<string, string>;
  by_account: Record<string, string>;
  // Итог по каждой валюте, включая рубль. Складывать между собой нельзя —
  // это разные деньги. Сюда попадают только оценённые позиции.
  by_currency: Record<string, string>;
  // Валюты всех позиций, включая неоценённые: по ним решается, нужна ли
  // оговорка «рублёвая часть». by_currency для этого не годится — валютная
  // позиция без котировки в него не попадает, но итог от этого рублёвой
  // частью быть не перестаёт.
  position_currencies: string[];
  // Дата актуальности оценки; пусто, если котировок ещё нет.
  as_of: string | null;
  // Покрытие оценкой: сколько позиций удалось оценить из скольких всего.
  // Совокупный капитал посчитан только по оценённым — если оценены не все,
  // это обязано быть видно рядом с самой цифрой.
  valued_positions: number;
  positions_total: number;
}

export interface PositionRow {
  isin: string | null;
  ticker: string | null;
  name: string;
  broker: string;
  // Подпись счёта: один и тот же тикер на нескольких счетах одного брокера
  // даёт несколько строк, различить которые больше нечем.
  account: string;
  // Валюта, в которой номинирована бумага: все суммы строки — в ней.
  currency: string;
  quantity: string;
  average_price: string;
  // null = оценки нет (нет котировки). Это не ноль: у бумаги без котировки
  // стоимость неизвестна, а не равна нулю.
  last_price: string | null;
  market_value: string | null;
  profit: string | null;
  profit_percent: string | null;
}

export interface HistoryPoint {
  date: string;
  total_value: string;
}

export interface ReconciliationRow {
  isin: string | null;
  status: string;
  ledger_quantity: string;
  broker_quantity: string;
  // Подпись счёта, к которому относится расхождение (сверка считается по
  // каждому счёту отдельно — один ISIN может дать две строки на двух счетах).
  account: string;
}

export interface SyncRunResult {
  // Подпись счёта, по которому прошёл этот прогон синхронизации.
  account: string;
  broker: string;
  status: string;
  inserted: number;
  skipped: number;
  mismatches: number;
  error: string | null;
}

// FastAPI сериализует HTTPException как {"detail": "..."} — настоящая причина
// сбоя (например, «Не задан TBANK_TOKEN в .env») лежит в теле ответа; без
// этого пользователь видит только код состояния, который ничего не объясняет.
async function describeError(path: string, response: Response): Promise<string> {
  try {
    const body: unknown = await response.json();
    const detail = (body as { detail?: unknown } | null)?.detail;
    if (typeof detail === "string" && detail.trim() !== "") {
      return detail;
    }
  } catch {
    // Тело не JSON или пустое — довольствуемся кодом состояния ниже.
  }
  return `Запрос ${path} завершился с кодом ${response.status}`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, init);
  if (!response.ok) {
    throw new Error(await describeError(path, response));
  }
  return response.json() as Promise<T>;
}

export const api = {
  overview: () => request<Overview>("/portfolio/overview"),
  positions: () => request<PositionRow[]>("/portfolio/positions"),
  history: (days = 90) => request<HistoryPoint[]>(`/portfolio/history?days=${days}`),
  reconciliations: () => request<ReconciliationRow[]>("/reconciliations"),
  syncTbank: () => request<SyncRunResult[]>("/sync/tbank", { method: "POST" }),
};
