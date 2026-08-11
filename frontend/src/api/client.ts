// Бэкенд на хосте слушает порт 8001 (порт 8000 занят посторонним контейнером).
const BASE = "http://localhost:8001/api";

export interface Overview {
  // Весь капитал в рублях: бумаги плюс деньги, всё пересчитано по курсам на
  // дату оценки — валюты от ЦБ, драгоценные металлы с MOEX (у ЦБ их нет).
  total_value: string;
  securities_value: string;
  cash_value: string;
  // Часть капитала, которой нельзя распорядиться: заблокированные количества
  // плюс бумаги, ограниченные в обороте. Входит в total_value.
  restricted_value: string;
  by_asset_class: Record<string, string>;
  by_account: Record<string, string>;
  // Итог по каждой валюте в ней самой, без пересчёта. Складывать нельзя.
  by_currency: Record<string, string>;
  position_currencies: string[];
  // Валюты, которым не нашлось курса: их часть капитала в сумму не вошла.
  // Пусто — посчитано всё, что имело цену.
  currencies_without_rate: string[];
  // Дата актуальности оценки; пусто, если котировок ещё нет.
  as_of: string | null;
  // Дата курсов: они обновляются раз в сутки, котировки — каждые 15 минут.
  // Самый старый из курсов, участвовавших в пересчёте, а не самый свежий из
  // имеющихся: подпись отвечает за ту цифру, что рядом.
  fx_as_of: string | null;
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
  // Валюта котировки: текущая цена и стоимость — в ней.
  currency: string;
  quantity: string;
  // null = себестоимость неизвестна: бумаги пришли переводом, брокер цены
  // покупки не сообщил. Это не ноль — на экране прочерк.
  average_price: string | null;
  cost_basis_known: boolean;
  // Валюта средней цены: у замещающей облигации расчёты рублёвые, а котировка
  // валютная, и подписать среднюю знаком котировки значит соврать в разы.
  average_price_currency: string;
  // null = оценки нет (нет котировки). Это не ноль: у бумаги без котировки
  // стоимость неизвестна, а не равна нулю.
  last_price: string | null;
  market_value: string | null;
  profit: string | null;
  profit_percent: string | null;
  // Стоимость в рублях; null, когда цена есть, а курса нет.
  value_base: string | null;
  // "moex" — биржа, "tbank" — цена самого брокера (оценка не независима).
  price_source: string | null;
  // Заблокированная брокером часть количества.
  blocked: string;
  // Бумагой нельзя распорядиться вовсе: ни купить, ни продать.
  restricted: boolean;
}

export interface HistoryPoint {
  date: string;
  total_value: string;
}

export interface Suggestion {
  from_isin: string;
  from_quantity: string;
  to_isin: string;
  to_quantity: string;
  // Бумага-получатель заблокирована у брокера целиком: конвертации часто
  // оседают именно так. Признак усиливающий, сам по себе гипотезу не создаёт.
  blocked_fully: boolean;
  // Кандидатов с такой же величиной несколько — выбирает владелец.
  ambiguous: boolean;
}

export interface ReconciliationRow {
  isin: string | null;
  status: string;
  ledger_quantity: string;
  broker_quantity: string;
  // Подпись счёта, к которому относится расхождение (сверка считается по
  // каждому счёту отдельно — один ISIN может дать две строки на двух счетах).
  account: string;
  suggestions: Suggestion[];
}

export interface DecisionInput {
  account: string;
  kind: "CONVERSION" | "ADJUSTMENT" | "ACCEPTED_AS_IS";
  status: "CONFIRMED" | "REJECTED";
  from_isin?: string | null;
  from_quantity?: string | null;
  to_isin?: string | null;
  to_quantity?: string | null;
  cost_basis?: string | null;
  effective_at: string;
  note: string;
}

export interface Decision {
  id: number;
  account: string;
  kind: string;
  status: string;
  from_isin: string | null;
  from_quantity: string | null;
  to_isin: string | null;
  to_quantity: string | null;
  effective_at: string;
  note: string;
  reverts_id: number | null;
}

export interface CashRow {
  account: string;
  currency: string;
  amount: string;
  blocked: string;
}

export interface SyncRunResult {
  // Подпись счёта, по которому прошёл этот прогон синхронизации.
  account: string;
  broker: string;
  status: string;
  inserted: number;
  skipped: number;
  mismatches: number;
  // Операции, которые брокер переписал задним числом: на разницу записана
  // корректирующая запись. Стабильно ненулевое значение означает поломку
  // обхода доисполняющихся заявок на стороне бэкенда.
  corrected: number;
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
  cash: () => request<CashRow[]>("/portfolio/cash"),
  history: (days = 90) => request<HistoryPoint[]>(`/portfolio/history?days=${days}`),
  reconciliations: () => request<ReconciliationRow[]>("/reconciliations"),
  syncTbank: () => request<SyncRunResult[]>("/sync/tbank", { method: "POST" }),
  decisions: () => request<Decision[]>("/decisions"),
  createDecision: (body: DecisionInput) =>
    request<Decision>("/decisions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  // Отмена адресная: бэкенд снимает те самые партии, которые открыло
  // отменяемое решение. Пояснение обязательно, как и при записи, — иначе через
  // год причину отмены не восстановит никто (бэкенд отвергнет запрос без него).
  // Возвращается зеркальное решение, а не отменённое: журнал append-only.
  revertDecision: (id: number, note: string) =>
    request<Decision>(`/decisions/${id}/revert`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ note }),
    }),
};
