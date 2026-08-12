# Фаза 2c «История стоимости задним числом» — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** График стоимости портфеля показывает историю с 16.07.2020 — даты первой операции журнала, — и у каждой точки известно, какой частью портфеля она посчитана.

**Architecture:** Историю цен и курсов загружают разовые прогоны в существующие таблицы `price` и `fx_rate` (MOEX для российских эмитентов, Yahoo для иностранных, ЦБ для курсов). Состав портфеля на прошлую дату восстанавливается свёрткой среза журнала существующим `fold`, деньги — движением назад от сегодняшнего остатка брокера. Оценка на дату и оценка сегодня идут через одну и ту же чистую функцию, поэтому достроенная часть графика не может разойтись с живой.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL 16, httpx, respx (тесты HTTP), pytest; React 19, TypeScript, ECharts, vitest.

## Global Constraints

- **Все денежные величины — `Decimal`, нигде не `float`.** `app/money.py:money()` бросает `TypeError` на `float` — числа из JSON приводить через `str()`: `money(str(value))`.
- **Комментарии, докстринги, сообщения об ошибках и логи — по-русски**, как во всём проекте.
- **Журнал операций append-only**: `UPDATE`/`DELETE` по таблице `transaction` запрещены триггером БД. Ничего в нём не правим.
- **Дата всегда московская**: `app/timeutils.py:moscow_today()`, никогда `date.today()`.
- **Тесты гоняются на настоящем PostgreSQL**: `cd backend && uv run pytest`. База поднимается из `docker compose up -d db` (порт 5433).
- **Фронтовые тесты**: `cd frontend && pnpm exec vitest run`. Команды `pnpm test` в проекте нет.
- **`uv` лежит в `C:\Users\User\.local\bin` вне PATH.**
- **Проверка типов фронта**: `pnpm run build` (`tsc -b && vite build`).
- Коммиты — по-русски, в стиле истории репозитория: `feat: ...`, `fix: ...`, `docs: ...`.

---

## Карта файлов

**Создаются:**

| Файл | Ответственность |
|---|---|
| `backend/app/marketdata/yahoo.py` | клиент Yahoo Finance: дневные закрытия и валюта инструмента |
| `backend/app/marketdata/symbols.py` | правило «куда идти за ценой» и символ Yahoo по инструменту |
| `backend/app/marketdata/history.py` | запись исторических цен и курсов в `price` и `fx_rate` |
| `backend/app/marketdata/backfill.py` | прогон загрузки истории (ходит в сеть) |
| `backend/app/positions/history.py` | состав портфеля на прошлую дату |
| `backend/app/accounts/cash_history.py` | денежные остатки на прошлую дату |
| `backend/app/snapshots/backfill.py` | прогон достройки снимков (считает из базы) |
| `backend/alembic/versions/0019_snapshot_source_and_coverage.py` | миграция |
| `backend/tests/test_yahoo.py`, `test_symbols.py`, `test_marketdata_history.py`, `test_positions_history.py`, `test_cash_history.py`, `test_snapshot_backfill.py` | тесты нового |
| `frontend/src/components/ValueChart.test.tsx` | тест графика |

**Меняются:**

| Файл | Что |
|---|---|
| `backend/app/marketdata/moex.py` | `close_history`: пагинация, выбор борда, номинал |
| `backend/app/marketdata/cbr.py` | `rate_history` — курсы диапазоном |
| `backend/app/marketdata/service.py` | `prices_as_of` вместо `latest_prices`, общее правило цены облигации, маршрутизация по ISIN |
| `backend/app/analytics/service.py` | разделение «состав» и «оценка», `value_portfolio` |
| `backend/app/positions/service.py` | `ledger_entries` становится публичной |
| `backend/app/models/snapshot.py` | `source`, покрытие, `unpriced` |
| `backend/app/snapshots/service.py` | `store_snapshot` с правилом перезаписи |
| `backend/app/api/schemas.py`, `routes_portfolio.py` | контракт истории |
| `backend/app/timeutils.py` | `moscow_day_end` |
| `frontend/src/api/client.ts`, `components/ValueChart.tsx`, `pages/PortfolioPage.tsx` | неполные точки на графике |
| `README.md`, `docs/roadmap.md` | прогоны и статус фазы |

---

### Task 1: История MOEX перестаёт врать на длинных диапазонах

Сегодня `close_history` отдаёт первые сто строк любого диапазона (ISS страничный, курсор не читается), берёт первую строку даты (у SBER это борд `SMAL` с оборотом в 32 тысячи против 19 миллиардов на `TQBR`) и не возвращает номинал, без которого цена облигации — не деньги, а проценты.

**Files:**
- Modify: `backend/app/marketdata/moex.py:88-107`
- Test: `backend/tests/test_moex.py`

**Interfaces:**
- Consumes: ничего.
- Produces: `MoexHistoryPoint(on_date: date, close: Decimal, face_value: Decimal | None, face_unit: str | None)`; `MoexClient.close_history(secid: str, start: date, end: date, market: str = "shares", engine: str = "stock") -> list[MoexHistoryPoint]`.

- [ ] **Step 1: Написать падающие тесты**

Дописать в `backend/tests/test_moex.py`, заменив существующий `test_close_history_parses_rows`:

```python
from app.marketdata.moex import MoexClient, MoexHistoryPoint

HISTORY = f"{BASE}/history/engines/stock/markets/shares/securities/SBER.json"


def _history(rows: list[list], columns: list[str], cursor: list[int] | None = None) -> dict:
    payload = {"history": {"columns": columns, "data": rows}}
    if cursor is not None:
        payload["history.cursor"] = {"columns": ["INDEX", "TOTAL", "PAGESIZE"], "data": [cursor]}
    return payload


@respx.mock
def test_close_history_parses_rows():
    respx.get(HISTORY).mock(return_value=httpx.Response(200, json=_history(
        [["TQBR", "2026-03-10", 310.5, 1000.0], ["TQBR", "2026-03-11", 314.28, 1000.0]],
        ["BOARDID", "TRADEDATE", "CLOSE", "VALUE"],
    )))
    assert MoexClient(BASE).close_history("SBER", date(2026, 3, 10), date(2026, 3, 11)) == [
        MoexHistoryPoint(on_date=date(2026, 3, 10), close=Decimal("310.5000")),
        MoexHistoryPoint(on_date=date(2026, 3, 11), close=Decimal("314.2800")),
    ]


@respx.mock
def test_close_history_walks_all_pages():
    """ISS отдаёт по сто строк на страницу и сообщает это курсором: у SBER за
    шесть лет строк 2851. Без добора страниц метод возвращал первые сто дней и
    выглядел успешным."""
    first = _history([["TQBR", "2026-03-10", 310.5, 1.0]], ["BOARDID", "TRADEDATE", "CLOSE", "VALUE"], [0, 2, 1])
    second = _history([["TQBR", "2026-03-11", 314.28, 1.0]], ["BOARDID", "TRADEDATE", "CLOSE", "VALUE"], [1, 2, 1])
    route = respx.get(HISTORY).mock(side_effect=[httpx.Response(200, json=first),
                                                 httpx.Response(200, json=second)])

    rows = MoexClient(BASE).close_history("SBER", date(2026, 3, 10), date(2026, 3, 11))

    assert [row.on_date for row in rows] == [date(2026, 3, 10), date(2026, 3, 11)]
    assert route.call_count == 2
    assert route.calls[1].request.url.params["start"] == "1"


@respx.mock
def test_close_history_takes_the_board_with_the_largest_turnover():
    """Живой замер 03.06.2024: у SBER борд SMAL дал закрытие 315 при обороте
    32 960 ₽, а основной TQBR — 310.95 при девятнадцати миллиардах. Первая
    строка ответа — SMAL, и брать её значит ошибаться на процент с лишним."""
    respx.get(HISTORY).mock(return_value=httpx.Response(200, json=_history(
        [["SMAL", "2024-06-03", 315, 32960.77], ["TQBR", "2024-06-03", 310.95, 19130763055.2]],
        ["BOARDID", "TRADEDATE", "CLOSE", "VALUE"],
    )))
    rows = MoexClient(BASE).close_history("SBER", date(2024, 6, 3), date(2024, 6, 3))
    assert [row.close for row in rows] == [Decimal("310.9500")]


@respx.mock
def test_close_history_skips_zero_and_missing_closes():
    """Ноль на валютном рынке означает «не торговалось», а не «стоило ноль»:
    живой замер по GLDRUB_TOM 03.06.2024 — CETS 6610, CNGD 0, LICU 0, SPEC 0.
    Колонки VALUE на этом рынке нет вовсе, поэтому при равном обороте
    побеждает первая строка ответа."""
    respx.get(f"{BASE}/history/engines/currency/markets/selt/securities/GLDRUB_TOM.json").mock(
        return_value=httpx.Response(200, json=_history(
            [["CETS", "2024-06-03", 6610], ["CNGD", "2024-06-03", 0],
             ["LICU", "2024-06-03", None], ["CETS", "2024-06-04", 6585], ["CNGD", "2024-06-04", 6617]],
            ["BOARDID", "TRADEDATE", "CLOSE"],
        ))
    )
    rows = MoexClient(BASE).close_history(
        "GLDRUB_TOM", date(2024, 6, 3), date(2024, 6, 4), market="selt", engine="currency"
    )
    assert [(row.on_date, row.close) for row in rows] == [
        (date(2024, 6, 3), Decimal("6610.0000")),
        (date(2024, 6, 4), Decimal("6585.0000")),
    ]


@respx.mock
def test_close_history_carries_face_value_of_the_day():
    """Номинал приходит на каждую дату, и у амортизируемого выпуска он
    меняется по ходу истории: пересчитывать старую цену нынешним номиналом
    нельзя. Живой замер по RU000A1054W1 03.06.2024: FACEVALUE 1000, FACEUNIT
    CNY — облигация российского эмитента с юаневым номиналом."""
    respx.get(f"{BASE}/history/engines/stock/markets/bonds/securities/RU000A1054W1.json").mock(
        return_value=httpx.Response(200, json=_history(
            [["TQCB", "2024-06-03", 91.3995, 2221429.39, 1000, "CNY"],
             ["TQOY", "2024-06-03", 92.7794, 1181540.36, 1000, "CNY"]],
            ["BOARDID", "TRADEDATE", "CLOSE", "VALUE", "FACEVALUE", "FACEUNIT"],
        ))
    )
    rows = MoexClient(BASE).close_history(
        "RU000A1054W1", date(2024, 6, 3), date(2024, 6, 3), market="bonds"
    )
    assert rows == [MoexHistoryPoint(on_date=date(2024, 6, 3), close=Decimal("91.3995"),
                                     face_value=Decimal("1000.0000"), face_unit="CNY")]
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `cd backend && uv run pytest tests/test_moex.py -v`
Expected: FAIL — `ImportError: cannot import name 'MoexHistoryPoint'`.

- [ ] **Step 3: Переписать `close_history`**

В `backend/app/marketdata/moex.py` добавить после `MoexQuote`:

```python
@dataclass(frozen=True)
class MoexHistoryPoint:
    """Закрытие торгового дня как его отдаёт MOEX, без интерпретации.

    `close` для акций и фондов — цена бумаги, для облигаций — процент от
    номинала; `face_value` и `face_unit` относятся к той же дате. Перевод в
    деньги делает вызывающий (app/marketdata/service.py): он знает вид
    инструмента, а клиент — нет.
    """

    on_date: date
    close: Decimal
    face_value: Decimal | None = None
    face_unit: str | None = None


# Колонки истории. Оборот нужен, чтобы выбрать борд (см. _best_of_day); номинал
# — чтобы пересчитать процент облигации в деньги. Рынок, на котором такой
# колонки нет (валютный), молча отдаёт пересечение — поэтому все обращения к
# строке идут через .get().
HISTORY_COLUMNS = "BOARDID,TRADEDATE,CLOSE,VALUE,FACEVALUE,FACEUNIT"
```

И заменить сам метод вместе с двумя вспомогательными функциями:

```python
def _cursor(block: dict | None) -> tuple[int, int, int] | None:
    """Позиция, всего строк и размер страницы. None — курсора в ответе нет,
    добирать нечем."""
    if not block or not block.get("data"):
        return None
    row = dict(zip(block["columns"], block["data"][0]))
    return int(row["INDEX"]), int(row["TOTAL"]), int(row["PAGESIZE"])


def _turnover(row: dict) -> Decimal:
    value = row.get("VALUE")
    return Decimal(str(value)) if value else Decimal("0")


def _best_of_day(rows: list[dict]) -> dict[date, dict]:
    """Одна строка на дату: та, где реально торговали.

    Инструмент приходит сразу с нескольких бордов. Замер 03.06.2024 по SBER:
    борд SMAL дал закрытие 315 при обороте 32 960 ₽, основной TQBR — 310.95
    при девятнадцати миллиардах; первая строка ответа — SMAL. Нулевое и пустое
    закрытие отбрасывается до выбора: ноль на бирже означает «не торговалось»,
    а не «стоило ноль». При равном обороте (на валютном рынке колонки оборота
    нет вовсе) остаётся первая строка ответа.
    """
    best: dict[date, dict] = {}
    for row in rows:
        close = row.get("CLOSE")
        if close is None or close == 0:
            continue
        traded = datetime.strptime(row["TRADEDATE"], "%Y-%m-%d").date()
        if traded not in best or _turnover(row) > _turnover(best[traded]):
            best[traded] = row
    return best


class MoexClient:
    ...

    def close_history(
        self, secid: str, start: date, end: date, market: str = "shares", engine: str = "stock"
    ) -> list[MoexHistoryPoint]:
        """Закрытия торговых дней за период, по одной строке на дату.

        ISS отдаёт историю страницами по сто строк и сообщает об этом курсором:
        у SBER за шесть лет строк 2851. Без добора страниц метод возвращал
        первые сто дней и выглядел работающим — дефект не проявляется на
        коротком диапазоне, а именно такими его и проверяли.
        """
        rows: list[dict] = []
        position = 0
        while True:
            payload = self._get(
                f"/history/engines/{engine}/markets/{market}/securities/{secid}.json",
                params={
                    "iss.meta": "off",
                    "iss.only": "history,history.cursor",
                    "history.columns": HISTORY_COLUMNS,
                    "from": start.isoformat(),
                    "till": end.isoformat(),
                    "start": str(position),
                },
            )
            page = _rows(payload["history"])
            rows.extend(page)
            cursor = _cursor(payload.get("history.cursor"))
            if not page or cursor is None:
                break
            index, total, page_size = cursor
            position = index + page_size
            if position >= total:
                break

        return [
            MoexHistoryPoint(
                on_date=traded,
                close=money(str(row["CLOSE"])),
                face_value=money(str(row["FACEVALUE"])) if row.get("FACEVALUE") else None,
                face_unit=row.get("FACEUNIT"),
            )
            for traded, row in sorted(_best_of_day(rows).items())
        ]
```

- [ ] **Step 4: Убедиться, что тесты проходят**

Run: `cd backend && uv run pytest tests/test_moex.py -v`
Expected: PASS, все тесты файла.

- [ ] **Step 5: Коммит**

```bash
git add backend/app/marketdata/moex.py backend/tests/test_moex.py
git commit -m "fix: история MOEX добирает страницы, выбирает борд по обороту и несёт номинал"
```

---

### Task 2: Клиент Yahoo Finance

Иностранные бумаги — 126 записей справочника — не котируются на MOEX ни в каком виде. Yahoo отдаёт дневные закрытия без ключа и сообщает валюту инструмента, по которой сопоставление символа можно проверить.

**Files:**
- Create: `backend/app/marketdata/yahoo.py`
- Create: `backend/tests/test_yahoo.py`
- Modify: `backend/app/config.py`

**Interfaces:**
- Consumes: `app.money.money`.
- Produces: `YahooHistory(currency: str, points: list[tuple[date, Decimal]])`; `YahooClient(base_url: str | None = None, timeout: float = 20.0)`; `YahooClient.close_history(symbol: str, start: date, end: date) -> YahooHistory | None` (None — символа нет).

- [ ] **Step 1: Написать падающий тест**

Создать `backend/tests/test_yahoo.py`:

```python
from datetime import date
from decimal import Decimal

import httpx
import pytest
import respx

from app.marketdata.yahoo import YahooClient

BASE = "https://query1.finance.yahoo.com"

# Обрезанный настоящий ответ по 9988.HK за 03–06.06.2024. Закрытия приходят
# числами с плавающей точкой и мусором в хвосте (76.6500015258789), метки
# времени — в секундах эпохи на момент открытия торгов, gmtoffset — сдвиг
# биржи (Гонконг +8 часов).
SAMPLE = {
    "chart": {
        "result": [{
            "meta": {"currency": "HKD", "symbol": "9988.HK", "gmtoffset": 28800},
            "timestamp": [1717378200, 1717464600, 1717551000],
            "indicators": {"quote": [{"close": [76.6500015258789, None, 76.94999694824219]}]},
        }],
        "error": None,
    }
}

NOT_FOUND = {"chart": {"result": None, "error": {"code": "Not Found", "description": "No data found"}}}


@respx.mock
def test_returns_daily_closes_and_currency():
    respx.get(f"{BASE}/v8/finance/chart/9988.HK").mock(return_value=httpx.Response(200, json=SAMPLE))

    history = YahooClient(BASE).close_history("9988.HK", date(2024, 6, 3), date(2024, 6, 5))

    assert history.currency == "HKD"
    assert history.points == [
        (date(2024, 6, 3), Decimal("76.6500")),
        (date(2024, 6, 5), Decimal("76.9500")),
    ]


@respx.mock
def test_skips_days_without_close():
    """Пустое закрытие — день без торгов, а не ноль: строки для него быть не
    должно вовсе, иначе бумага «подешевела до нуля» на праздник."""
    respx.get(f"{BASE}/v8/finance/chart/9988.HK").mock(return_value=httpx.Response(200, json=SAMPLE))
    history = YahooClient(BASE).close_history("9988.HK", date(2024, 6, 3), date(2024, 6, 5))
    assert date(2024, 6, 4) not in [day for day, _ in history.points]


@respx.mock
def test_unknown_symbol_returns_none_instead_of_raising():
    """Несопоставленный символ — обычный исход разовой загрузки истории по
    сотне бумаг, а не сбой: он оставляет бумагу неоценённой на её датах и не
    роняет прогон."""
    respx.get(f"{BASE}/v8/finance/chart/NOSUCH").mock(return_value=httpx.Response(404, json=NOT_FOUND))
    assert YahooClient(BASE).close_history("NOSUCH", date(2024, 6, 3), date(2024, 6, 5)) is None


@respx.mock
def test_requests_the_whole_day_range_and_identifies_itself():
    respx.get(f"{BASE}/v8/finance/chart/U").mock(return_value=httpx.Response(200, json=SAMPLE))

    YahooClient(BASE).close_history("U", date(2024, 6, 3), date(2024, 6, 5))

    request = respx.calls[0].request
    # Конец диапазона — начало следующих суток: иначе последний день выпадает.
    assert request.url.params["period1"] == "1717372800"
    assert request.url.params["period2"] == "1717632000"
    assert request.url.params["interval"] == "1d"
    assert "Mozilla" in request.headers["user-agent"]


@respx.mock
def test_server_error_raises():
    """Отказ сервера — не то же самое, что «нет такого символа»: молча вернуть
    None значит объявить бумагу неоценимой из-за пятисекундной аварии."""
    respx.get(f"{BASE}/v8/finance/chart/U").mock(return_value=httpx.Response(503))
    with pytest.raises(httpx.HTTPStatusError):
        YahooClient(BASE).close_history("U", date(2024, 6, 3), date(2024, 6, 5))
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `cd backend && uv run pytest tests/test_yahoo.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.marketdata.yahoo'`.

- [ ] **Step 3: Написать клиент**

Создать `backend/app/marketdata/yahoo.py`:

```python
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

import httpx

from app.config import get_settings
from app.money import money

# Yahoo отвечает 429 на запросы без опознавательных знаков.
USER_AGENT = "Mozilla/5.0 (compatible; jarvis-investment/1.0)"


@dataclass(frozen=True)
class YahooHistory:
    """Дневные закрытия и валюта, в которой они номинированы.

    Валюта здесь не справочная: по ней вызывающий проверяет, что символ
    сопоставлен верно (см. app/marketdata/symbols.py). Тикер `700` на
    американском рынке — не Tencent, и цена чужой бумаги ничем не отличается
    от настоящей, кроме того, что неверна.
    """

    currency: str
    points: list[tuple[date, Decimal]]


def _day_start(day: date) -> int:
    return int(datetime.combine(day, time.min, tzinfo=timezone.utc).timestamp())


class YahooClient:
    """Дневные закрытия Yahoo Finance.

    Берётся неприведённое закрытие (`indicators.quote[0].close`), а не
    `adjclose`: количество бумаг в журнале записано таким, каким оно было на ту
    дату, и приведённая к сплитам цена дала бы стоимость позиции мимо в разы —
    у NVDA сплит 10:1 в 2024 году.
    """

    def __init__(self, base_url: str | None = None, timeout: float = 20.0) -> None:
        self.base_url = (base_url or get_settings().yahoo_base_url).rstrip("/")
        self.timeout = timeout

    def close_history(self, symbol: str, start: date, end: date) -> YahooHistory | None:
        """Закрытия за период включительно. None — такого символа у Yahoo нет.

        Ненайденный символ — обычный исход разовой загрузки по сотне бумаг
        (делистинг, переименование тикера), и он обязан отличаться от отказа
        сервера: первое оставляет бумагу неоценённой, второе требует повтора.
        """
        response = httpx.get(
            f"{self.base_url}/v8/finance/chart/{symbol}",
            params={
                "period1": str(_day_start(start)),
                # Начало следующих суток: иначе последний день диапазона выпадает.
                "period2": str(_day_start(end + timedelta(days=1))),
                "interval": "1d",
            },
            headers={"User-Agent": USER_AGENT},
            timeout=self.timeout,
        )
        if response.status_code == httpx.codes.NOT_FOUND:
            return None
        response.raise_for_status()

        result = ((response.json().get("chart") or {}).get("result") or [None])[0]
        if not result:
            return None

        meta = result.get("meta") or {}
        offset = int(meta.get("gmtoffset") or 0)
        stamps = result.get("timestamp") or []
        quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
        closes = quote.get("close") or []

        points: list[tuple[date, Decimal]] = []
        for stamp, close in zip(stamps, closes):
            if close is None:
                continue
            # Метка времени — момент открытия торгов в UTC; торговый день
            # берётся в поясе самой биржи, иначе гонконгская сессия у полуночи
            # уезжает на сутки.
            traded = datetime.fromtimestamp(stamp + offset, tz=timezone.utc).date()
            points.append((traded, money(str(close))))

        return YahooHistory(currency=(meta.get("currency") or "").upper(), points=points)
```

- [ ] **Step 4: Добавить настройку базового адреса**

В `backend/app/config.py` в класс `Settings` после `cbr_base_url`:

```python
    yahoo_base_url: str = "https://query1.finance.yahoo.com"
```

- [ ] **Step 5: Убедиться, что тесты проходят**

Run: `cd backend && uv run pytest tests/test_yahoo.py -v`
Expected: PASS, пять тестов.

- [ ] **Step 6: Коммит**

```bash
git add backend/app/marketdata/yahoo.py backend/app/config.py backend/tests/test_yahoo.py
git commit -m "feat: клиент исторических котировок Yahoo Finance"
```

---

### Task 3: Куда идти за ценой и под каким символом

Сегодняшнее правило «на MOEX ходим за рублёвыми» (`_priced_at_moex`) смотрит на валюту и потому уводит с биржи восемь облигаций российских эмитентов с юаневым номиналом — РУСАЛ, Полюс, Роснефть, ЭН+ и другие. Площадку задаёт эмитент, а не валюта расчётов.

**Files:**
- Create: `backend/app/marketdata/symbols.py`
- Create: `backend/tests/test_symbols.py`
- Modify: `backend/app/marketdata/service.py:56-58,82-88`

**Interfaces:**
- Consumes: `app.models.Instrument`.
- Produces: `priced_at_moex(instrument: Instrument) -> bool`; `yahoo_symbol(instrument: Instrument) -> str | None`; `moex_isin_filter(column) -> object` (условие SQLAlchemy для выборки).

- [ ] **Step 1: Написать падающий тест**

Создать `backend/tests/test_symbols.py`:

```python
import pytest

from app.marketdata.symbols import priced_at_moex, yahoo_symbol
from app.models import Instrument


def instrument(**kwargs) -> Instrument:
    defaults = {"isin": "RU000A0JQUZ6", "ticker": "AGRO", "secid": "AGRO",
                "currency": "RUB", "kind": "share"}
    return Instrument(**{**defaults, **kwargs})


@pytest.mark.parametrize("isin,ticker,expected", [
    ("RU000A0JQUZ6", "AGRO", True),
    # Облигация российского эмитента с юаневым номиналом: на MOEX она есть, и
    # правило по валюте уводило её к брокеру.
    ("RU000A1054W1", "RU000A1054W1", True),
    ("US67066G1040", "NVDA", False),
    ("KYG875721634", "700", False),
    ("HK0000651213", "3067", False),
])
def test_moex_routing_follows_the_issuer_not_the_currency(isin, ticker, expected):
    assert priced_at_moex(instrument(isin=isin, ticker=ticker, secid=ticker)) is expected


def test_instrument_without_secid_is_not_priced_at_moex():
    """Без идентификатора площадки запрос строить не из чего."""
    assert priced_at_moex(instrument(secid=None)) is False


@pytest.mark.parametrize("isin,ticker,currency,expected", [
    ("US67066G1040", "NVDA", "USD", "NVDA"),
    ("US69608A1088", "PLTR", "USD", "PLTR"),
    # Гонконгская нумерация — четыре знака: 700 это 0700.HK.
    ("KYG875721634", "700", "HKD", "0700.HK"),
    ("KYG017191142", "9988", "HKD", "9988.HK"),
])
def test_yahoo_symbol_from_ticker(isin, ticker, currency, expected):
    assert yahoo_symbol(instrument(isin=isin, ticker=ticker, currency=currency)) == expected


@pytest.mark.parametrize("isin,expected", [
    # Тикер сменился после того, как бумага перестала торговаться у брокера.
    ("US8522341036", "XYZ"),
    ("US87918A1051", "TDOC"),
    ("US91332U1016", "U"),
    # Гонконгский фонд в двух валютных линейках: гонконгская и юаневая.
    ("HK0000051877", "3010.HK"),
    ("HK0000310034", "83010.HK"),
])
def test_known_exceptions_are_resolved_by_isin(isin, expected):
    """У этих бумаг справочник брокера положил в тикер сам ISIN — вывести
    символ из него нельзя, он задан поимённо."""
    assert yahoo_symbol(instrument(isin=isin, ticker=isin, currency="USD")) == expected


def test_delisted_instrument_has_no_symbol():
    """ТКС Холдинг делистингован: символа нет ни у Yahoo, ни где-либо ещё.
    None здесь — не ошибка, а честный ответ, который оставит бумагу
    неоценённой на её датах."""
    assert yahoo_symbol(instrument(isin="US87238U2033", ticker="US87238U2033", currency="USD")) is None


def test_ticker_equal_to_isin_gives_no_symbol():
    """Справочник брокера кладёт ISIN в тикер, когда настоящего тикера не
    знает. Отправлять ISIN на Yahoo бессмысленно, а угадывать — опасно."""
    assert yahoo_symbol(instrument(isin="US1234567890", ticker="US1234567890", currency="USD")) is None


def test_russian_instrument_has_no_yahoo_symbol():
    """Российская бумага идёт на MOEX; символа Yahoo у неё быть не должно —
    иначе один инструмент попадёт в оба прогона и получит две цены за день."""
    assert yahoo_symbol(instrument()) is None
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `cd backend && uv run pytest tests/test_symbols.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.marketdata.symbols'`.

- [ ] **Step 3: Написать правило**

Создать `backend/app/marketdata/symbols.py`:

```python
"""Куда идти за ценой бумаги и под каким именем её там спрашивать.

Правило здесь одно на проект: и ежедневное обновление котировок
(app/marketdata/service.py), и разовая загрузка истории
(app/marketdata/history.py) спрашивают его, а не решают сами. Два правила о
том, где котируется бумага, разъедутся так же, как разъехались два правила о
знаке ADJUSTMENT — и стоить это будет неверной оценки капитала.
"""

from sqlalchemy import func

from app.models import Instrument

# Площадку задаёт эмитент, а не валюта расчётов. Восемь облигаций российских
# эмитентов номинированы в юанях (РУСАЛ, Полюс, Роснефть, ЭН+ и другие) и
# торгуются на MOEX; прежнее правило «на MOEX ходим только за рублёвыми»
# уводило их к брокеру, и биржевой цены у них не было вовсе.
MOEX_ISIN_PREFIX = "RU"

# Гонконгская биржа нумерует бумаги четырьмя знаками: 700 — это 0700.HK.
HK_SYMBOL_WIDTH = 4

# Бумаги, у которых справочник брокера положил в тикер сам ISIN, а настоящий
# символ известен. Сопоставление задано поимённо, потому что вывести его не из
# чего: тикер сменился (Block был SQ, стал XYZ) либо бумага живёт в двух
# валютных линейках (гонконгский фонд iShares: 3010.HK за гонконгские доллары,
# 83010.HK за юани). Проверено на живых ответах Yahoo 12.08.2026; валюта в
# ответе совпала с валютой инструмента у всех пяти.
YAHOO_SYMBOL_BY_ISIN = {
    "US8522341036": "XYZ",       # Block, бывший SQ
    "US87918A1051": "TDOC",      # Teladoc Health
    "US91332U1016": "U",         # Unity Software
    "HK0000051877": "3010.HK",   # iShares Core MSCI Asia ex Japan, гонконгская линейка
    "HK0000310034": "83010.HK",  # он же, юаневая линейка
}

# Бумаги, которых у Yahoo нет и не будет: делистинг без правопреемника на
# бирже. Перечислены явно, чтобы прогон не тратил на них запрос и чтобы
# следующая сессия не искала «почему не нашлось».
YAHOO_UNAVAILABLE = {
    "US87238U2033",  # ТКС Холдинг после редомициляции
}


def priced_at_moex(instrument: Instrument) -> bool:
    """Идём ли за ценой этой бумаги на MOEX."""
    isin = instrument.isin or ""
    return bool(instrument.secid) and isin.startswith(MOEX_ISIN_PREFIX)


def moex_isin_filter(column) -> object:
    """То же правило для выборки из базы: ISIN российского эмитента."""
    return func.upper(func.coalesce(column, "")).startswith(MOEX_ISIN_PREFIX)


def yahoo_symbol(instrument: Instrument) -> str | None:
    """Символ Yahoo или None, если спрашивать нечего.

    None означает «символа нет», а не «ошибка»: бумага останется неоценённой на
    своих датах, и это будет видно в покрытии снимка. Угадывать хуже, чем не
    знать: неверный символ даёт правдоподобную цену чужой бумаги.
    """
    isin = instrument.isin or ""
    if isin in YAHOO_UNAVAILABLE:
        return None
    known = YAHOO_SYMBOL_BY_ISIN.get(isin)
    if known:
        return known
    if priced_at_moex(instrument):
        return None

    ticker = (instrument.ticker or "").strip().upper()
    if not ticker or ticker == isin.upper():
        return None
    if ticker.isdigit():
        return f"{ticker.zfill(HK_SYMBOL_WIDTH)}.HK"
    return ticker
```

- [ ] **Step 4: Перевести ежедневное обновление котировок на то же правило**

В `backend/app/marketdata/service.py` удалить функцию `_priced_at_moex` (строки 56-58) и заменить её использование в `refresh_last_prices`:

```python
from app.marketdata.symbols import moex_isin_filter

...

def refresh_last_prices(session: Session, client: MoexClient, on_date: date) -> int:
    instruments = session.execute(
        select(Instrument).where(
            Instrument.secid.is_not(None),
            moex_isin_filter(Instrument.isin),
        )
    ).scalars().all()
```

- [ ] **Step 5: Прогнать тесты котировок целиком**

Run: `cd backend && uv run pytest tests/test_symbols.py tests/test_marketdata_service.py -v`
Expected: PASS. Если тест в `test_marketdata_service.py` опирался на отбор по валюте — поправить его данные на ISIN (у рублёвой бумаги ISIN должен начинаться с `RU`), а не возвращать старое правило.

- [ ] **Step 6: Коммит**

```bash
git add backend/app/marketdata/symbols.py backend/app/marketdata/service.py backend/tests/test_symbols.py backend/tests/test_marketdata_service.py
git commit -m "feat: маршрут за ценой задаёт эмитент, а не валюта расчётов"
```

---

### Task 4: Архив курсов ЦБ

`fx_rate` заполняется только с текущего дня, а капитал валютный: без исторических курсов достроенная точка не переведёт в рубли ни гонконгскую бумагу, ни юаневую облигацию.

**Files:**
- Modify: `backend/app/marketdata/cbr.py`
- Test: `backend/tests/test_cbr.py`

**Interfaces:**
- Consumes: ничего.
- Produces: `CbrClient.rate_history(currency: str, start: date, end: date) -> list[tuple[date, Decimal]]`; `CbrClient.currency_codes() -> dict[str, str]` (ISO-код → внутренний код ЦБ).

- [ ] **Step 1: Написать падающий тест**

Дописать в `backend/tests/test_cbr.py`:

```python
# Обрезанный настоящий ответ XML_dynamic по доллару за 01–10.03.2022: курса на
# 07–09 марта нет вовсе — праздники, ЦБ их не публикует.
DYNAMIC = """<?xml version="1.0" encoding="windows-1251"?>
<ValCurs ID="R01235" DateRange1="01.03.2022" DateRange2="10.03.2022" name="Foreign Currency Market Dynamic">
<Record Date="01.03.2022" Id="R01235"><Nominal>1</Nominal><Value>93,5589</Value><VunitRate>93,5589</VunitRate></Record>
<Record Date="02.03.2022" Id="R01235"><Nominal>1</Nominal><Value>91,7457</Value><VunitRate>91,7457</VunitRate></Record>
<Record Date="10.03.2022" Id="R01235"><Nominal>1</Nominal><Value>116,0847</Value><VunitRate>116,0847</VunitRate></Record>
</ValCurs>"""

# Обрезанный XML_valFull: соответствие ISO-кода внутреннему коду ЦБ. Иена
# котируется за сотню — номинал здесь тоже есть, но делит на него разбор
# самого курса.
VAL_FULL = """<?xml version="1.0" encoding="windows-1251"?>
<Valuta name="Foreign Currency Market Lib">
<Item ID="R01235"><Name>Доллар США</Name><Nominal>1</Nominal><ISO_Char_Code>USD</ISO_Char_Code></Item>
<Item ID="R01200"><Name>Гонконгский доллар</Name><Nominal>1</Nominal><ISO_Char_Code>HKD</ISO_Char_Code></Item>
<Item ID="R01375"><Name>Юань</Name><Nominal>1</Nominal><ISO_Char_Code>CNY</ISO_Char_Code></Item>
<Item ID="R01720A"><Name>Украинский карбованец</Name><Nominal>1</Nominal><ISO_Char_Code></ISO_Char_Code></Item>
</Valuta>"""


class RoutingTransport:
    """Отвечает по адресу: истории курсов и справочнику кодов — разные ответы."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str]]] = []

    def __call__(self, url: str, params: dict[str, str], timeout: float) -> bytes:
        self.calls.append((url, params))
        body = VAL_FULL if url.endswith("XML_valFull.asp") else DYNAMIC
        return body.encode("windows-1251")


def test_rate_history_returns_published_days_only():
    """Курса на 07–09.03.2022 нет: ЦБ в праздники не публикует. Достраивать
    пропущенные дни здесь нельзя — «курс, действующий на дату» выводит
    читающая сторона (latest_rates), и делает это одним правилом на проект."""
    client = CbrClient(fetch=RoutingTransport())

    rows = client.rate_history("USD", date(2022, 3, 1), date(2022, 3, 10))

    assert rows == [
        (date(2022, 3, 1), Decimal("93.55890000")),
        (date(2022, 3, 2), Decimal("91.74570000")),
        (date(2022, 3, 10), Decimal("116.08470000")),
    ]


def test_rate_history_asks_the_internal_code_of_the_currency():
    transport = RoutingTransport()

    CbrClient(fetch=transport).rate_history("HKD", date(2022, 3, 1), date(2022, 3, 10))

    dynamic = [params for url, params in transport.calls if url.endswith("XML_dynamic.asp")]
    assert dynamic == [{"date_req1": "01/03/2022", "date_req2": "10/03/2022", "VAL_NM_RQ": "R01200"}]


def test_currency_codes_are_fetched_once_per_client():
    """Справочник кодов не меняется в течение прогона, а бумаг и валют в нём
    сотни: второй запрос за тем же ответом — чистая трата."""
    transport = RoutingTransport()
    client = CbrClient(fetch=transport)

    client.rate_history("USD", date(2022, 3, 1), date(2022, 3, 10))
    client.rate_history("CNY", date(2022, 3, 1), date(2022, 3, 10))

    assert sum(1 for url, _ in transport.calls if url.endswith("XML_valFull.asp")) == 1


def test_unknown_currency_raises():
    """Валюта без кода ЦБ — это ошибка сопоставления, а не пустая история:
    молчаливый пустой ответ выглядел бы как «курса не публиковали»."""
    with pytest.raises(KeyError):
        CbrClient(fetch=RoutingTransport()).rate_history("XAU", date(2022, 3, 1), date(2022, 3, 10))
```

Добавить в начало файла `import pytest`, если его там ещё нет.

- [ ] **Step 2: Убедиться, что тест падает**

Run: `cd backend && uv run pytest tests/test_cbr.py -v`
Expected: FAIL — `AttributeError: 'CbrClient' object has no attribute 'rate_history'`.

- [ ] **Step 3: Дописать клиент**

В `backend/app/marketdata/cbr.py` добавить в класс `CbrClient`:

```python
    def currency_codes(self) -> dict[str, str]:
        """ISO-код валюты → внутренний код ЦБ (`USD` → `R01235`).

        Читается из справочника, а не зашивается литералами: кодов больше
        сотни, и ошибка в одном даёт не отказ, а курс чужой валюты. Ответ не
        меняется в течение прогона и запрашивается один раз.
        """
        if self._codes is None:
            body = self._fetch(f"{self.base_url}/scripts/XML_valFull.asp", {}, self.timeout)
            root = ElementTree.fromstring(body.decode(ENCODING))
            self._codes = {
                code.upper(): item.attrib["ID"]
                for item in root.findall("Item")
                if (code := item.findtext("ISO_Char_Code") or "")
            }
        return self._codes

    def rate_history(self, currency: str, start: date, end: date) -> list[tuple[date, Decimal]]:
        """Курсы валюты за период — одним запросом на всю историю.

        Отдаются только опубликованные дни: в выходные и праздники ЦБ курса не
        устанавливает, и достраивать пропуски здесь нельзя. Вопрос «какой курс
        действовал в субботу» решает читающая сторона (`latest_rates`), одним
        правилом на проект.
        """
        code = self.currency_codes()[currency.upper()]
        body = self._fetch(
            f"{self.base_url}/scripts/XML_dynamic.asp",
            {
                "date_req1": start.strftime("%d/%m/%Y"),
                "date_req2": end.strftime("%d/%m/%Y"),
                "VAL_NM_RQ": code,
            },
            self.timeout,
        )
        root = ElementTree.fromstring(body.decode(ENCODING))

        rows: list[tuple[date, Decimal]] = []
        for record in root.findall("Record"):
            nominal = record.findtext("Nominal")
            value = record.findtext("Value")
            if not nominal or not value:
                continue
            rate = Decimal(value.replace(",", ".")) / Decimal(nominal)
            rows.append((
                datetime.strptime(record.attrib["Date"], "%d.%m.%Y").date(),
                rate.quantize(RATE_EXP),
            ))
        return rows
```

И в `__init__` добавить последней строкой:

```python
        self._codes: dict[str, str] | None = None
```

- [ ] **Step 4: Убедиться, что тесты проходят**

Run: `cd backend && uv run pytest tests/test_cbr.py -v`
Expected: PASS, все тесты файла.

- [ ] **Step 5: Коммит**

```bash
git add backend/app/marketdata/cbr.py backend/tests/test_cbr.py
git commit -m "feat: архив курсов ЦБ диапазоном, коды валют из справочника"
```

---

### Task 5: Запись исторических цен

**Files:**
- Create: `backend/app/marketdata/history.py`
- Create: `backend/tests/test_marketdata_history.py`
- Modify: `backend/app/marketdata/service.py:60-80`

**Interfaces:**
- Consumes: `MoexHistoryPoint`, `YahooClient`, `priced_at_moex`, `yahoo_symbol`, `ENGINE_MARKET_BY_KIND`.
- Produces: `price_in_money(kind: str, price: Decimal, face_value: Decimal | None, face_unit: str | None) -> tuple[Decimal, str] | None` (в `service.py`); `load_price_history(session, instrument, start, end, *, moex, yahoo) -> int` (в `history.py`), возвращает число записанных дней; `YAHOO_SOURCE = "yahoo"`.

- [ ] **Step 1: Написать падающий тест**

Создать `backend/tests/test_marketdata_history.py`:

```python
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.marketdata.history import load_price_history
from app.marketdata.moex import MoexHistoryPoint
from app.marketdata.yahoo import YahooHistory
from app.models import Instrument, Price

START = date(2024, 6, 3)
END = date(2024, 6, 4)


class FakeMoex:
    def __init__(self, points: list[MoexHistoryPoint]) -> None:
        self.points = points
        self.calls: list[tuple[str, str, str]] = []

    def close_history(self, secid, start, end, market="shares", engine="stock"):
        self.calls.append((secid, market, engine))
        return self.points


class FakeYahoo:
    def __init__(self, history: YahooHistory | None) -> None:
        self.history = history
        self.calls: list[str] = []

    def close_history(self, symbol, start, end):
        self.calls.append(symbol)
        return self.history


def _instrument(session, **kwargs) -> Instrument:
    defaults = {"isin": "RU000A0JQUZ6", "ticker": "AGRO", "secid": "AGRO",
                "currency": "RUB", "kind": "share"}
    instrument = Instrument(**{**defaults, **kwargs})
    session.add(instrument)
    session.flush()
    return instrument


def _prices(session, instrument) -> list[Price]:
    return list(session.execute(
        select(Price).where(Price.instrument_id == instrument.id).order_by(Price.on_date)
    ).scalars())


def test_russian_share_is_loaded_from_moex(session):
    instrument = _instrument(session)
    moex = FakeMoex([MoexHistoryPoint(on_date=START, close=Decimal("1350.0000"))])

    written = load_price_history(session, instrument, START, END,
                                 moex=moex, yahoo=FakeYahoo(None))

    assert written == 1
    price = _prices(session, instrument)[0]
    assert (price.close, price.currency, price.source) == (Decimal("1350.0000"), "RUB", "moex")
    assert moex.calls == [("AGRO", "shares", "stock")]


def test_bond_price_is_converted_by_the_face_value_of_that_day(session):
    """Облигация котируется в процентах от номинала, и у амортизируемого
    выпуска номинал меняется по ходу истории: 91.3995% от юаневой тысячи —
    913.995 юаня, а не 91 рубль."""
    instrument = _instrument(session, isin="RU000A1054W1", ticker="RU000A1054W1",
                             secid="RU000A1054W1", kind="bond", currency="CNY")
    moex = FakeMoex([MoexHistoryPoint(on_date=START, close=Decimal("91.3995"),
                                      face_value=Decimal("1000.0000"), face_unit="CNY")])

    load_price_history(session, instrument, START, END, moex=moex, yahoo=FakeYahoo(None))

    price = _prices(session, instrument)[0]
    assert (price.close, price.currency) == (Decimal("913.9950"), "CNY")
    assert moex.calls == [("RU000A1054W1", "bonds", "stock")]


def test_foreign_share_is_loaded_from_yahoo(session):
    instrument = _instrument(session, isin="KYG017191142", ticker="9988",
                             secid="9988", currency="HKD")
    yahoo = FakeYahoo(YahooHistory(currency="HKD", points=[(START, Decimal("76.6500"))]))

    written = load_price_history(session, instrument, START, END, moex=FakeMoex([]), yahoo=yahoo)

    assert written == 1
    price = _prices(session, instrument)[0]
    assert (price.close, price.currency, price.source) == (Decimal("76.6500"), "HKD", "yahoo")
    assert yahoo.calls == ["9988.HK"]


def test_symbol_answering_in_another_currency_is_refused(session):
    """Тикер `700` на американском рынке — не Tencent. Цена чужой бумаги ничем
    не отличается от настоящей, кроме того, что неверна, поэтому несовпадение
    валюты — отказ, а не предупреждение."""
    instrument = _instrument(session, isin="KYG875721634", ticker="700", secid="700", currency="HKD")
    yahoo = FakeYahoo(YahooHistory(currency="USD", points=[(START, Decimal("12.3400"))]))

    written = load_price_history(session, instrument, START, END, moex=FakeMoex([]), yahoo=yahoo)

    assert written == 0
    assert _prices(session, instrument) == []


def test_instrument_without_symbol_is_skipped_without_calling_anyone(session):
    instrument = _instrument(session, isin="US87238U2033", ticker="US87238U2033",
                             secid="US87238U2033", currency="USD")
    yahoo = FakeYahoo(YahooHistory(currency="USD", points=[(START, Decimal("1.0000"))]))

    assert load_price_history(session, instrument, START, END, moex=FakeMoex([]), yahoo=yahoo) == 0
    assert yahoo.calls == []


def test_repeated_load_updates_instead_of_duplicating(session):
    """Прогон повторяется, и второй заход обязан оставить одну строку на день:
    ключ таблицы цен — инструмент, дата и источник."""
    instrument = _instrument(session)
    moex = FakeMoex([MoexHistoryPoint(on_date=START, close=Decimal("1350.0000"))])
    load_price_history(session, instrument, START, END, moex=moex, yahoo=FakeYahoo(None))

    moex.points = [MoexHistoryPoint(on_date=START, close=Decimal("1360.0000"))]
    load_price_history(session, instrument, START, END, moex=moex, yahoo=FakeYahoo(None))

    prices = _prices(session, instrument)
    assert len(prices) == 1
    assert prices[0].close == Decimal("1360.0000")
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `cd backend && uv run pytest tests/test_marketdata_history.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.marketdata.history'`.

- [ ] **Step 3: Вынести правило цены облигации в общую функцию**

В `backend/app/marketdata/service.py` заменить `_price_in_money` на публичную функцию, работающую с числами, а не с объектом котировки, — её зовут оба пути, живой и исторический:

```python
def price_in_money(
    kind: str, price: Decimal, face_value: Decimal | None, face_unit: str | None
) -> tuple[Decimal, str] | None:
    """Цена одной бумаги и валюта этой цены.

    Акции и фонды MOEX котирует прямо в деньгах и всегда в рублях. Облигации —
    в процентах от номинала, и номинал бывает не рублёвым: замещающие и
    юаневые выпуски. Без пересчёта из процентов облигация с номиналом 1000 ₽
    оценивалась в сотню рублей.

    Накопленный купонный доход в цену не входит: он платится сверх неё и по
    смыслу ближе к начислению, чем к стоимости бумаги.

    Функция берёт числа, а не котировку: живая цена приходит из блока
    marketdata, историческая — из блока history, и правило перевода у них
    обязано быть одно.
    """
    if kind != kinds.BOND:
        return price, BASE_CURRENCY
    if not face_value:
        return None
    unit = (face_unit or "SUR").upper()
    currency = FACE_UNIT_TO_ISO.get(unit, unit)
    return money(price / Decimal("100") * face_value), currency
```

И заменить её вызов в `refresh_last_prices`:

```python
        priced = (
            None if quote.price is None
            else price_in_money(instrument.kind, quote.price, quote.face_value, quote.face_unit)
        )
```

- [ ] **Step 4: Написать загрузку истории**

Создать `backend/app/marketdata/history.py`:

```python
"""Загрузка исторических котировок в таблицу `price`.

Отдельно от `service.py`: тот отвечает за сегодняшнюю цену и за чтение цен, а
здесь — разовое наполнение истории. Общее у них — правило перевода котировки в
деньги (`price_in_money`) и правило маршрута (`app/marketdata/symbols.py`); оба
живут в одном месте на проект и зовутся отсюда, а не переписываются.
"""

import logging
from datetime import date

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.marketdata.service import (
    ENGINE_MARKET_BY_KIND,
    MOEX_SOURCE,
    price_in_money,
)
from app.marketdata.symbols import priced_at_moex, yahoo_symbol
from app.models import Instrument, Price
from app.money import BASE_CURRENCY

logger = logging.getLogger(__name__)

# Метка независимого источника иностранных котировок.
YAHOO_SOURCE = "yahoo"


def _store(session: Session, instrument_id: int, rows: list[tuple[date, object, str]], source: str) -> int:
    written = 0
    for on_date, close, currency in rows:
        statement = insert(Price).values(
            instrument_id=instrument_id, on_date=on_date, close=close,
            currency=currency, source=source,
        ).on_conflict_do_update(
            index_elements=[Price.instrument_id, Price.on_date, Price.source],
            set_={"close": close, "currency": currency},
        )
        session.execute(statement)
        written += 1
    session.flush()
    return written


def _from_moex(instrument: Instrument, start: date, end: date, moex) -> list[tuple[date, object, str]]:
    engine, market = ENGINE_MARKET_BY_KIND.get(instrument.kind, ("stock", "shares"))
    rows: list[tuple[date, object, str]] = []
    for point in moex.close_history(instrument.secid, start, end, market=market, engine=engine):
        priced = price_in_money(instrument.kind, point.close, point.face_value, point.face_unit)
        if priced is None:
            # Облигация без номинала на эту дату: процент в деньги не перевести,
            # а записать процент ценой значило бы оценить выпуск в сотню рублей.
            continue
        close, currency = priced
        rows.append((point.on_date, close, currency))
    return rows


def _from_yahoo(instrument: Instrument, start: date, end: date, yahoo) -> list[tuple[date, object, str]]:
    symbol = yahoo_symbol(instrument)
    if symbol is None:
        logger.info("Инструмент %s (%s): символа Yahoo нет, история не загружается",
                    instrument.id, instrument.isin)
        return []

    history = yahoo.close_history(symbol, start, end)
    if history is None:
        logger.warning("Символ %s у Yahoo не найден (инструмент %s, %s)",
                       symbol, instrument.id, instrument.isin)
        return []

    expected = (instrument.currency or BASE_CURRENCY).upper()
    if history.currency != expected:
        # Сопоставление символа неверно. Отказ, а не предупреждение: цена чужой
        # бумаги ничем не отличается от настоящей, кроме того, что неверна, —
        # и обнаружится это не сразу, а через месяцы, кривым графиком.
        logger.error(
            "Символ %s отвечает в %s, а инструмент %s (%s) номинирован в %s — "
            "сопоставление неверно, история не загружается",
            symbol, history.currency, instrument.id, instrument.isin, expected,
        )
        return []

    return [(on_date, close, history.currency) for on_date, close in history.points]


def load_price_history(
    session: Session, instrument: Instrument, start: date, end: date, *, moex, yahoo
) -> int:
    """Загружает историю котировок одного инструмента. Возвращает число дней.

    Маршрут выбирается общим правилом (`app/marketdata/symbols.py`): бумага
    российского эмитента идёт на MOEX независимо от валюты расчётов, остальные
    — на Yahoo. Ноль возвращается и когда истории нет, и когда спрашивать
    некого: и то и другое оставляет бумагу неоценённой на своих датах, и видно
    это будет в покрытии снимка, а не в тишине.
    """
    if priced_at_moex(instrument):
        return _store(session, instrument.id, _from_moex(instrument, start, end, moex), MOEX_SOURCE)
    return _store(session, instrument.id, _from_yahoo(instrument, start, end, yahoo), YAHOO_SOURCE)
```

- [ ] **Step 5: Дать Yahoo место в приоритете источников**

В `backend/app/marketdata/service.py` заменить `SOURCE_PRIORITY`:

```python
# Приоритет при одинаковой дате: биржа важнее независимого источника, а тот
# важнее брокера. Брокер — сторона, с чьим снимком мы сверяемся; оценивать
# портфель его же числами можно, только когда своих нет.
SOURCE_PRIORITY = {MOEX_SOURCE: 0, "yahoo": 1, TBANK_SOURCE: 2}
```

Литерал, а не импорт `YAHOO_SOURCE`: `history.py` уже импортирует `service.py`, и обратный импорт замкнёт круг. Рядом оставить комментарий об этом.

- [ ] **Step 6: Убедиться, что тесты проходят**

Run: `cd backend && uv run pytest tests/test_marketdata_history.py tests/test_marketdata_service.py -v`
Expected: PASS.

- [ ] **Step 7: Коммит**

```bash
git add backend/app/marketdata/history.py backend/app/marketdata/service.py backend/tests/test_marketdata_history.py
git commit -m "feat: загрузка исторических котировок с MOEX и Yahoo"
```

---

### Task 6: Запись исторических курсов и золота

**Files:**
- Modify: `backend/app/marketdata/history.py`
- Modify: `backend/tests/test_marketdata_history.py`

**Interfaces:**
- Consumes: `CbrClient.rate_history`, `MoexClient.close_history`, `app.marketdata.fx.CBR_SOURCE`, `app.marketdata.fx.MOEX_SOURCE`, `app.marketdata.fx.METAL_SECIDS`.
- Produces: `load_fx_history(session, currencies: list[str], start: date, end: date, *, cbr) -> int`; `load_metal_history(session, start: date, end: date, *, moex) -> int`.

- [ ] **Step 1: Написать падающий тест**

Дописать в `backend/tests/test_marketdata_history.py`:

```python
from app.marketdata.history import load_fx_history, load_metal_history
from app.models import FxRate


class FakeCbr:
    def __init__(self, rows: dict[str, list[tuple[date, Decimal]]]) -> None:
        self.rows = rows
        self.calls: list[str] = []

    def rate_history(self, currency, start, end):
        self.calls.append(currency)
        return self.rows.get(currency, [])


def _rates(session, currency) -> list[FxRate]:
    return list(session.execute(
        select(FxRate).where(FxRate.currency == currency).order_by(FxRate.on_date)
    ).scalars())


def test_fx_history_is_stored_under_the_published_date(session):
    cbr = FakeCbr({"USD": [(date(2022, 3, 1), Decimal("93.55890000")),
                           (date(2022, 3, 2), Decimal("91.74570000"))]})

    written = load_fx_history(session, ["USD"], date(2022, 3, 1), date(2022, 3, 10), cbr=cbr)

    assert written == 2
    rows = _rates(session, "USD")
    assert [(row.on_date, row.rate, row.source) for row in rows] == [
        (date(2022, 3, 1), Decimal("93.55890000"), "cbr"),
        (date(2022, 3, 2), Decimal("91.74570000"), "cbr"),
    ]


def test_fx_history_skips_the_base_currency(session):
    """Рубль к рублю — единица, и она не хранится: строка, которая никогда не
    меняется, лишь создаёт впечатление, что её можно не найти."""
    cbr = FakeCbr({})
    load_fx_history(session, ["RUB", "USD"], date(2022, 3, 1), date(2022, 3, 10), cbr=cbr)
    assert cbr.calls == ["USD"]


def test_metal_history_comes_from_the_exchange(session):
    """У ЦБ драгоценных металлов нет вовсе, а в остатках Т-Банка золото лежит
    наравне с валютами: курс берётся с MOEX, где GLDRUB_TOM котируется в
    рублях за грамм."""
    moex = FakeMoex([MoexHistoryPoint(on_date=date(2024, 6, 3), close=Decimal("6610.0000"))])

    written = load_metal_history(session, date(2024, 6, 3), date(2024, 6, 4), moex=moex)

    assert written == 1
    rows = _rates(session, "XAU")
    assert (rows[0].rate, rows[0].source) == (Decimal("6610.00000000"), "moex")
    assert moex.calls == [("GLDRUB_TOM", "selt", "currency")]
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `cd backend && uv run pytest tests/test_marketdata_history.py -v -k "fx or metal"`
Expected: FAIL — `ImportError: cannot import name 'load_fx_history'`.

- [ ] **Step 3: Дописать загрузку**

В `backend/app/marketdata/history.py` добавить импорты и две функции:

```python
from app.marketdata.fx import CBR_SOURCE, METAL_SECIDS
from app.marketdata.fx import MOEX_SOURCE as FX_MOEX_SOURCE
from app.models import FxRate


def _store_rate(session: Session, currency: str, on_date: date, rate, source: str) -> None:
    statement = insert(FxRate).values(
        currency=currency, on_date=on_date, rate=rate, source=source
    ).on_conflict_do_update(
        index_elements=[FxRate.currency, FxRate.on_date],
        set_={"rate": rate, "source": source},
    )
    session.execute(statement)


def load_fx_history(session: Session, currencies: list[str], start: date, end: date, *, cbr) -> int:
    """Курсы ЦБ за период по каждой названной валюте. Возвращает число строк.

    Базовая валюта пропускается: рубль к рублю — единица, и она не хранится
    (см. `latest_rates`). Дни, в которые ЦБ курса не публиковал, остаются
    пустыми — «курс, действующий на дату» выводит читающая сторона.
    """
    written = 0
    for currency in currencies:
        if currency.upper() == BASE_CURRENCY:
            continue
        for on_date, rate in cbr.rate_history(currency, start, end):
            _store_rate(session, currency.upper(), on_date, rate, CBR_SOURCE)
            written += 1
    session.flush()
    return written


def load_metal_history(session: Session, start: date, end: date, *, moex) -> int:
    """Курсы металлов за период с MOEX: у ЦБ их нет вовсе.

    Тот же инструмент, которым фаза 2a считает золото сегодня (GLDRUB_TOM,
    движок currency, рынок selt), — рубли за грамм.
    """
    written = 0
    for currency, secid in METAL_SECIDS.items():
        for point in moex.close_history(secid, start, end, market="selt", engine="currency"):
            _store_rate(session, currency, point.on_date, point.close, FX_MOEX_SOURCE)
            written += 1
    session.flush()
    return written
```

- [ ] **Step 4: Убедиться, что тесты проходят**

Run: `cd backend && uv run pytest tests/test_marketdata_history.py -v`
Expected: PASS, девять тестов файла.

- [ ] **Step 5: Коммит**

```bash
git add backend/app/marketdata/history.py backend/tests/test_marketdata_history.py
git commit -m "feat: загрузка истории курсов ЦБ и золота с MOEX"
```

---

### Task 7: Цена на дату с предельным возрастом

Сегодня `latest_prices` берёт самую свежую цену без всяких условий. Для истории этого мало: нужна цена на дату, и нужна граница, за которой «последняя известная» перестаёт быть ценой. Владелец выбрал неделю: выходные, праздники и несовпадение календарей трёх бирж — устройство биржи, а остановка торгов 2022 года за неделю выходит и честно показывается неоценённой.

**Files:**
- Modify: `backend/app/marketdata/service.py:134-166`
- Modify: `backend/app/analytics/service.py:159-166,227-235`
- Test: `backend/tests/test_marketdata_service.py`

**Interfaces:**
- Consumes: ничего.
- Produces: `PRICE_MAX_AGE: timedelta` (7 дней); `prices_as_of(session: Session, on_date: date, max_age: timedelta = PRICE_MAX_AGE) -> dict[int, LatestPrice]`. Функция `latest_prices` удаляется.

- [ ] **Step 1: Написать падающий тест**

Дописать в `backend/tests/test_marketdata_service.py`:

```python
from datetime import date, timedelta

from app.marketdata.service import PRICE_MAX_AGE, prices_as_of


def test_price_of_the_day_ignores_later_quotes(session):
    """Точка истории обязана считаться ценой своего дня: завтрашняя котировка
    в ней — это знание из будущего, от которого график поедет вверх ровно там,
    где рынок падал."""
    instrument = _instrument(session)  # существующая фабрика файла
    _price(session, instrument, date(2024, 6, 3), Decimal("100.0000"))
    _price(session, instrument, date(2024, 6, 5), Decimal("120.0000"))

    prices = prices_as_of(session, date(2024, 6, 4))

    assert prices[instrument.id].close == Decimal("100.0000")
    assert prices[instrument.id].on_date == date(2024, 6, 3)


def test_price_older_than_the_limit_is_not_a_price(session):
    """Бумага не торговалась две недели — цены на дату нет. Показать
    двухнедельную как сегодняшнюю значит выдать остановку торгов за факт."""
    instrument = _instrument(session)
    _price(session, instrument, date(2024, 6, 3), Decimal("100.0000"))

    assert prices_as_of(session, date(2024, 6, 3) + PRICE_MAX_AGE + timedelta(days=1)) == {}


def test_price_within_the_limit_survives_a_weekend(session):
    instrument = _instrument(session)
    _price(session, instrument, date(2024, 6, 3), Decimal("100.0000"))

    prices = prices_as_of(session, date(2024, 6, 3) + PRICE_MAX_AGE)

    assert prices[instrument.id].close == Decimal("100.0000")
```

Если в файле нет фабрик `_instrument` и `_price` — написать их рядом с тестами:

```python
def _instrument(session) -> Instrument:
    instrument = Instrument(isin="RU000A0JQUZ6", ticker="AGRO", secid="AGRO",
                            currency="RUB", kind="share")
    session.add(instrument)
    session.flush()
    return instrument


def _price(session, instrument, on_date, close, source="moex", currency="RUB") -> None:
    session.add(Price(instrument_id=instrument.id, on_date=on_date, close=close,
                      currency=currency, source=source))
    session.flush()
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `cd backend && uv run pytest tests/test_marketdata_service.py -v -k "price_of_the_day or older_than or within_the_limit"`
Expected: FAIL — `ImportError: cannot import name 'prices_as_of'`.

- [ ] **Step 3: Заменить `latest_prices` на `prices_as_of`**

В `backend/app/marketdata/service.py`:

```python
from datetime import date, timedelta

# Предельный возраст цены. Выходные, праздники и несовпадение календарей MOEX,
# США и Гонконга закрываются молча — это устройство биржи, а не пробел в
# данных. Настоящая остановка торгов (иностранные бумаги в 2022 году) за неделю
# выходит, и позиция честно становится неоценённой: замороженная цена, которую
# тянут месяцами, выглядит фактом и им не является.
PRICE_MAX_AGE = timedelta(days=7)


def prices_as_of(
    session: Session, on_date: date, max_age: timedelta = PRICE_MAX_AGE
) -> dict[int, LatestPrice]:
    """Цена каждого инструмента на дату: самая свежая не позже неё.

    Свежесть решает первой, происхождение — вторым: вчерашняя биржевая цена
    хуже сегодняшней брокерской, потому что вопрос стоит «сколько стоит на эту
    дату». При равной дате выигрывает биржа, затем независимый источник, и
    только потом брокер (SOURCE_PRIORITY).

    Цена старше `max_age` не возвращается вовсе: инструмент считается
    неоценённым, и покрытие снимка это назовёт.
    """
    priority = case(SOURCE_PRIORITY, value=Price.source, else_=_UNKNOWN_SOURCE_PRIORITY)
    ranked = select(
        Price.instrument_id,
        Price.close,
        Price.on_date,
        Price.currency,
        Price.source,
        func.row_number().over(
            partition_by=Price.instrument_id,
            order_by=(Price.on_date.desc(), priority.asc()),
        ).label("rn"),
    ).where(
        Price.on_date <= on_date,
        Price.on_date >= on_date - max_age,
    ).subquery()

    rows = session.execute(
        select(
            ranked.c.instrument_id, ranked.c.close, ranked.c.on_date,
            ranked.c.currency, ranked.c.source,
        ).where(ranked.c.rn == 1)
    ).all()
    return {
        instrument_id: LatestPrice(close=close, on_date=on_date, currency=currency, source=source)
        for instrument_id, close, on_date, currency, source in rows
    }
```

Удалить прежнюю `latest_prices`.

- [ ] **Step 4: Перевести аналитику на новую функцию**

В `backend/app/analytics/service.py` заменить импорт `latest_prices` на `prices_as_of` и оба вызова:

```python
# position_rows
    today = moscow_today()
    prices = prices_as_of(session, today)
    rates = latest_rates(session, today)

# portfolio_overview
    today = moscow_today()
    prices = prices_as_of(session, today)
```

В `position_rows` дата берётся один раз и передаётся обоим вызовам — по той же причине, по которой это уже сделано в `portfolio_overview`: два отдельных обращения к часам разошлись бы на сутки у прогона, начатого за миг до московской полуночи.

- [ ] **Step 5: Прогнать весь бэкенд**

Run: `cd backend && uv run pytest -q`
Expected: PASS. Тесты, звавшие `latest_prices`, поправить на `prices_as_of(session, <дата теста>)`; тесты, где цена записана «сегодня», продолжают работать.

- [ ] **Step 6: Проверить на живых данных, что сегодняшние цифры не изменились**

```bash
docker compose up -d db
docker exec jarvis-investment-db-1 psql -U jarvis -d jarvis -c "
select max(current_date - on_date) as самая_старая_цена_в_днях from price;"
```

Ожидание: значение меньше семи. Если так — предельный возраст сегодня не отсекает ни одной цены, и дашборд не меняется. Если больше — **остановиться и сказать владельцу**, какие позиции выпадут: это видимое изменение, а не деталь.

- [ ] **Step 7: Коммит**

```bash
git add backend/app/marketdata/service.py backend/app/analytics/service.py backend/tests/test_marketdata_service.py
git commit -m "feat: цена на дату с предельным возрастом вместо просто последней"
```

---

### Task 8: Состав портфеля на прошлую дату

**Files:**
- Create: `backend/app/positions/history.py`
- Create: `backend/tests/test_positions_history.py`
- Modify: `backend/app/positions/service.py:14-40`
- Modify: `backend/app/timeutils.py`

**Interfaces:**
- Consumes: `app.positions.engine.fold`, `LedgerEntry`, `PositionState`.
- Produces: `moscow_day_end(on_date: date) -> datetime` (в `timeutils.py`); `ledger_entries(session: Session, account: Account) -> list[LedgerEntry]` (публичная, бывшая `_entries`); `holdings_at(entries: list[LedgerEntry], on_date: date) -> dict[int, PositionState]`.

- [ ] **Step 1: Написать падающий тест**

Создать `backend/tests/test_positions_history.py`:

```python
from datetime import date, datetime, timezone
from decimal import Decimal

from app.models import OperationType
from app.positions.engine import LedgerEntry
from app.positions.history import holdings_at


def entry(day: str, op_type: OperationType, quantity: str, price: str = "100") -> LedgerEntry:
    return LedgerEntry(
        op_type=op_type,
        executed_at=datetime.fromisoformat(day),
        instrument_id=1,
        quantity=Decimal(quantity),
        price=Decimal(price),
        amount=Decimal("0"),
        fee=Decimal("0"),
    )


ENTRIES = [
    entry("2024-06-03T10:00:00+00:00", OperationType.BUY, "10"),
    entry("2024-06-05T10:00:00+00:00", OperationType.BUY, "5"),
    entry("2024-06-07T10:00:00+00:00", OperationType.SELL, "12"),
]


def test_holdings_include_operations_of_the_day_itself():
    assert holdings_at(ENTRIES, date(2024, 6, 3))[1].quantity == Decimal("10.00000000")


def test_holdings_ignore_the_future():
    assert holdings_at(ENTRIES, date(2024, 6, 4))[1].quantity == Decimal("10.00000000")
    assert holdings_at(ENTRIES, date(2024, 6, 6))[1].quantity == Decimal("15.00000000")
    assert holdings_at(ENTRIES, date(2024, 6, 7))[1].quantity == Decimal("3.00000000")


def test_before_the_first_operation_the_portfolio_is_empty():
    assert holdings_at(ENTRIES, date(2024, 6, 2)) == {}


def test_the_day_ends_by_moscow_not_by_utc():
    """Операция 21:30 UTC — это уже 00:30 следующих суток по Москве, и в
    сегодняшний снимок она попасть не должна: снимки живут в московской
    календарной дате, и вечерняя сделка иначе оказалась бы вчерашней."""
    late = [entry("2024-06-03T21:30:00+00:00", OperationType.BUY, "10")]

    assert holdings_at(late, date(2024, 6, 3)) == {}
    assert holdings_at(late, date(2024, 6, 4))[1].quantity == Decimal("10.00000000")


def test_closed_position_is_not_returned():
    """Позиция, закрытая к дате, — это отсутствие позиции, а не ноль штук:
    иначе оценка считала бы её неоценённой и портила покрытие."""
    closed = ENTRIES + [entry("2024-06-08T10:00:00+00:00", OperationType.SELL, "3")]
    assert holdings_at(closed, date(2024, 6, 8)) == {}
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `cd backend && uv run pytest tests/test_positions_history.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.positions.history'`.

- [ ] **Step 3: Добавить конец московских суток**

В `backend/app/timeutils.py`:

```python
from datetime import date, datetime, time, timedelta


def moscow_day_end(on_date: date) -> datetime:
    """Момент, до которого операция считается совершённой в этот день.

    Это начало следующих московских суток: операция 21:30 UTC — уже 00:30
    следующего дня по Москве, и в снимок сегодняшнего дня она попадать не
    должна. Снимки живут в московской календарной дате (см. moscow_today), и
    граница дня обязана считаться в том же поясе.
    """
    return datetime.combine(on_date + timedelta(days=1), time.min, tzinfo=MOSCOW_TZ)
```

- [ ] **Step 4: Сделать сборку записей журнала публичной**

В `backend/app/positions/service.py` переименовать `_entries` в `ledger_entries`, дописав докстринг, и поправить единственный вызов в `rebuild_positions`:

```python
def ledger_entries(session: Session, account: Account) -> list[LedgerEntry]:
    """Записи журнала счёта в виде, понятном движку позиций.

    Публичная: тем же входом пользуется восстановление состава на прошлую дату
    (app/positions/history.py). Собирать LedgerEntry в двух местах нельзя —
    разъедется трактовка payload, и одна из сторон перестанет видеть решения
    владельца.
    """
```

- [ ] **Step 5: Написать восстановление состава**

Создать `backend/app/positions/history.py`:

```python
"""Состав портфеля на прошлую дату.

Свёртка журнала — существующая (`app/positions/engine.py:fold`), а не своя:
FIFO, закрытые сделки, конвертации и отмены решений владельца считаются одним
кодом и сегодня, и год назад. Второй реализации свёртки в проекте быть не
должно — она разойдётся с первой на первом же корпоративном действии.
"""

from datetime import date

from app.positions.engine import LedgerEntry, PositionState, fold
from app.timeutils import moscow_day_end


def holdings_at(entries: list[LedgerEntry], on_date: date) -> dict[int, PositionState]:
    """Открытые позиции на конец дня: инструмент → состояние.

    Позиция с нулевым количеством не возвращается вовсе: к этой дате её нет, и
    это не то же самое, что «есть, но неоценена». Иначе каждая закрытая за
    шесть лет бумага портила бы покрытие снимка.

    Записи фильтруются по московскому концу суток — тому же поясу, в котором
    живёт календарная дата снимка.
    """
    cutoff = moscow_day_end(on_date)
    result = fold([entry for entry in entries if entry.executed_at < cutoff])
    return {
        instrument_id: state
        for instrument_id, state in result.positions.items()
        if state.quantity != 0
    }
```

- [ ] **Step 6: Убедиться, что тесты проходят**

Run: `cd backend && uv run pytest tests/test_positions_history.py tests/test_positions_service.py -v`
Expected: PASS.

- [ ] **Step 7: Коммит**

```bash
git add backend/app/positions/history.py backend/app/positions/service.py backend/app/timeutils.py backend/tests/test_positions_history.py
git commit -m "feat: состав портфеля на прошлую дату свёрткой среза журнала"
```

---

### Task 9: Денежные остатки на прошлую дату

Свёртка журнала вперёд от нуля не сходится с брокером: на «Инвестиционном» расхождение 53 083,71 ₽. Поэтому остаток считается назад от сегодняшнего, известного точно, и накопленная ошибка уходит в глубь истории, где её можно измерить, а не на сегодняшний экран, где ей верят.

**Files:**
- Create: `backend/app/accounts/cash_history.py`
- Create: `backend/tests/test_cash_history.py`

**Interfaces:**
- Consumes: `app.accounts.cash.cash_by_account`, `app.positions.engine.signed_quantity`, `app.timeutils.moscow_day_end`.
- Produces: `CURRENCY_BY_FIGI: dict[str, str]`; `cash_flows(session: Session) -> list[tuple[datetime, int, str, Decimal]]`; `cash_history(session: Session, start: date, end: date) -> dict[date, dict[int, dict[str, Decimal]]]`.

- [ ] **Step 1: Написать падающий тест**

Создать `backend/tests/test_cash_history.py`:

```python
from datetime import date, datetime, timezone
from decimal import Decimal

from app.accounts.cash_history import cash_history
from app.models import CashBalance, OperationType, Transaction


def _tx(session, account, *, day: str, op_type: OperationType, amount: str,
        currency: str = "RUB", quantity: str = "0", fee: str = "0",
        payload: dict | None = None, external_id: str = "x") -> Transaction:
    tx = Transaction(
        account_id=account.id, instrument_id=None, op_type=op_type,
        executed_at=datetime.fromisoformat(day), quantity=Decimal(quantity),
        price=Decimal("0"), amount=Decimal(amount), currency=currency,
        fee=Decimal(fee), external_id=external_id, source="tbank",
        dedup_key=f"k-{external_id}", payload=payload or {},
    )
    session.add(tx)
    session.flush()
    return tx


def _balance(session, account, currency: str, amount: str) -> None:
    session.add(CashBalance(account_id=account.id, currency=currency,
                            amount=Decimal(amount), blocked=Decimal("0")))
    session.flush()


def test_yesterday_is_today_minus_todays_flows(session, account):
    _balance(session, account, "RUB", "1000")
    _tx(session, account, day="2024-06-05T10:00:00+00:00",
        op_type=OperationType.DEPOSIT, amount="400", external_id="a")

    history = cash_history(session, date(2024, 6, 3), date(2024, 6, 5))

    assert history[date(2024, 6, 5)][account.id]["RUB"] == Decimal("1000.0000")
    assert history[date(2024, 6, 4)][account.id]["RUB"] == Decimal("600.0000")
    assert history[date(2024, 6, 3)][account.id]["RUB"] == Decimal("600.0000")


def test_fee_is_subtracted_together_with_the_amount(session, account):
    _balance(session, account, "RUB", "1000")
    _tx(session, account, day="2024-06-05T10:00:00+00:00",
        op_type=OperationType.BUY, amount="-400", fee="10", external_id="a")

    history = cash_history(session, date(2024, 6, 4), date(2024, 6, 5))

    assert history[date(2024, 6, 4)][account.id]["RUB"] == Decimal("1410.0000")


def test_currency_purchase_moves_both_legs(session, account):
    """Покупка юаня — двуногая операция: рубли уходят суммой, юани приходят
    количеством. Без второй ноги история валютных остатков не сходится ни на
    одном счёте: живой замер давал −43 338 HKD при нуле у брокера."""
    _balance(session, account, "RUB", "1000")
    _balance(session, account, "CNY", "200")
    _tx(session, account, day="2024-06-05T10:00:00+00:00", op_type=OperationType.BUY,
        amount="-2145.80", quantity="200", external_id="a",
        payload={"instrument_kind": "currency", "figi": "BBG0013HRTL0"})

    history = cash_history(session, date(2024, 6, 4), date(2024, 6, 5))

    assert history[date(2024, 6, 4)][account.id]["RUB"] == Decimal("3145.8000")
    assert history[date(2024, 6, 4)][account.id]["CNY"] == Decimal("0.0000")


def test_currency_sale_moves_both_legs_the_other_way(session, account):
    _balance(session, account, "RUB", "1000")
    _balance(session, account, "USD", "50")
    _tx(session, account, day="2024-06-05T10:00:00+00:00", op_type=OperationType.SELL,
        amount="4000", quantity="50", external_id="a",
        payload={"instrument_kind": "currency", "figi": "BBG0013HGFT4"})

    history = cash_history(session, date(2024, 6, 4), date(2024, 6, 5))

    assert history[date(2024, 6, 4)][account.id]["RUB"] == Decimal("-3000.0000")
    assert history[date(2024, 6, 4)][account.id]["USD"] == Decimal("100.0000")


def test_unknown_currency_figi_moves_only_the_rouble_leg(session, account, caplog):
    """Незнакомый валютный псевдоинструмент не угадывается: угаданная валюта
    молча испортила бы историю остатков, а запись в логе даёт починить
    сопоставление."""
    _balance(session, account, "RUB", "1000")
    _tx(session, account, day="2024-06-05T10:00:00+00:00", op_type=OperationType.BUY,
        amount="-500", quantity="7", external_id="a",
        payload={"instrument_kind": "currency", "figi": "BBG00НЕИЗВЕСТНО"})

    history = cash_history(session, date(2024, 6, 4), date(2024, 6, 5))

    assert history[date(2024, 6, 4)][account.id]["RUB"] == Decimal("1500.0000")
    assert "BBG00НЕИЗВЕСТНО" in caplog.text


def test_ordinary_share_purchase_has_no_second_leg(session, account):
    """У покупки акции количество — это бумаги, а не деньги: вторая нога тут
    была бы выдумкой."""
    _balance(session, account, "RUB", "1000")
    _tx(session, account, day="2024-06-05T10:00:00+00:00", op_type=OperationType.BUY,
        amount="-500", quantity="7", external_id="a",
        payload={"instrument_kind": "share", "figi": "BBG004730N88"})

    history = cash_history(session, date(2024, 6, 4), date(2024, 6, 5))

    assert history[date(2024, 6, 4)][account.id] == {"RUB": Decimal("1500.0000")}
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `cd backend && uv run pytest tests/test_cash_history.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.accounts.cash_history'`.

- [ ] **Step 3: Написать восстановление остатков**

Создать `backend/app/accounts/cash_history.py`:

```python
"""Денежные остатки счетов на прошлые даты.

Считаются назад от сегодняшнего остатка брокера, а не вперёд от нуля. Причина
измерена: свёртка журнала вперёд не сходится с брокером — на «Инвестиционном»
расхождение 53 083,71 ₽ (замер 12.08.2026). Сегодняшний остаток известен точно,
и якорь на нём уводит накопленную ошибку в глубь истории, где её можно
измерить по дате открытия счёта, а не на сегодняшний экран, где ей верят.
"""

import logging
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.accounts.cash import cash_by_account
from app.models import Transaction
from app.money import money
from app.positions.engine import signed_quantity
from app.timeutils import moscow_day_end

logger = logging.getLogger(__name__)

# Валютные псевдоинструменты Т-Банка: покупка валюты приходит обычной BUY, где
# сумма — рубли, а количество — сама валюта. FIGI, а не название: название
# брокер меняет, идентификатор — нет. Список закрыт замером живого журнала
# 12.08.2026 (988 операций, пять инструментов); незнакомый FIGI не угадывается,
# а пишется в лог.
CURRENCY_BY_FIGI = {
    "BBG0013HRTL0": "CNY",
    "BBG0013HSW87": "HKD",
    "BBG0013HGFT4": "USD",
    "BBG0013HJJ31": "EUR",
    "BBG000VJ5YR4": "XAU",
}

CURRENCY_KIND = "currency"


def cash_flows(session: Session) -> list[tuple[datetime, int, str, Decimal]]:
    """Все движения денег журнала: когда, по какому счёту, в какой валюте, сколько.

    У валютной операции ног две: рублёвая (сумма минус комиссия) и валютная
    (количество со знаком по типу операции). Знак валютной ноги берётся из
    общего доменного соглашения (`signed_quantity`), а не ставится здесь: то же
    правило читают движок позиций и служба решений, и разъезжаться им нельзя.
    """
    flows: list[tuple[datetime, int, str, Decimal]] = []
    transactions = session.execute(
        select(Transaction).order_by(Transaction.executed_at)
    ).scalars().all()

    for tx in transactions:
        flows.append((tx.executed_at, tx.account_id, tx.currency.upper(),
                      money(tx.amount - tx.fee)))

        payload = tx.payload or {}
        if payload.get("instrument_kind") != CURRENCY_KIND:
            continue

        figi = payload.get("figi") or ""
        currency = CURRENCY_BY_FIGI.get(figi)
        if currency is None:
            logger.warning(
                "Валютная операция %s с неизвестным FIGI %s: вторая нога не "
                "учтена, история остатков по этой валюте неполна",
                tx.id, figi,
            )
            continue

        amount = signed_quantity(tx.op_type, tx.quantity)
        if amount:
            flows.append((tx.executed_at, tx.account_id, currency, money(amount)))

    return flows


def cash_history(
    session: Session, start: date, end: date
) -> dict[date, dict[int, dict[str, Decimal]]]:
    """Остатки на каждый день периода: дата → счёт → валюта → сумма.

    Идём от `end` назад: остаток предыдущего дня — это остаток следующего минус
    движения следующего дня. Валюта, которой в сегодняшнем остатке нет, но
    которая встречалась в журнале, появляется по ходу сама — так в истории
    оживают доллары, проданные в 2023 году.
    """
    balances: dict[int, dict[str, Decimal]] = {
        account_id: dict(currencies)
        for account_id, currencies in cash_by_account(session).items()
    }

    by_day: dict[date, list[tuple[int, str, Decimal]]] = defaultdict(list)
    for executed_at, account_id, currency, amount in cash_flows(session):
        # День операции — московский, тот же, в котором живёт снимок.
        by_day[(executed_at - (moscow_day_end(date(1970, 1, 1)) - datetime(
            1970, 1, 2, tzinfo=executed_at.tzinfo))).date()].append(
            (account_id, currency, amount))

    history: dict[date, dict[int, dict[str, Decimal]]] = {}
    day = end
    while day >= start:
        history[day] = {
            account_id: dict(currencies) for account_id, currencies in balances.items()
        }
        for account_id, currency, amount in by_day.get(day, []):
            account = balances.setdefault(account_id, {})
            account[currency] = money(account.get(currency, money("0")) - amount)
        day -= timedelta(days=1)

    return history
```

- [ ] **Step 4: Заменить вычисление московского дня операции на честное**

Выражение в `by_day` выше намеренно оставлено неверным — считать московскую дату вычитанием разницы двух моментов нельзя. Заменить его на явное:

```python
from app.timeutils import MOSCOW_TZ

...

    for executed_at, account_id, currency, amount in cash_flows(session):
        # Московская календарная дата операции: снимок живёт в ней же, и
        # операция 21:30 UTC обязана попасть в следующий день, а не в текущий.
        moscow_day = executed_at.astimezone(MOSCOW_TZ).date()
        by_day[moscow_day].append((account_id, currency, amount))
```

и убрать из импортов `moscow_day_end`, если он больше не нужен.

- [ ] **Step 5: Убедиться, что тесты проходят**

Run: `cd backend && uv run pytest tests/test_cash_history.py -v`
Expected: PASS, шесть тестов.

- [ ] **Step 6: Коммит**

```bash
git add backend/app/accounts/cash_history.py backend/tests/test_cash_history.py
git commit -m "feat: денежные остатки на прошлую дату от якоря сегодняшнего остатка"
```

---

### Task 10: Оценка отделяется от источника состава

Вторая реализация оценки — гарантированный способ вернуть ступеньку между достроенной частью графика и живой, просто по другой причине. Одна функция делает такую ступеньку невозможной по построению.

**Files:**
- Modify: `backend/app/analytics/service.py:227-384`
- Test: `backend/tests/test_analytics.py`

**Interfaces:**
- Consumes: `value_position`, `to_base`, `asset_class_of`, `cash_asset_class`.
- Produces:
  - `Holding(account_id: int, instrument: Instrument, quantity: Decimal, blocked: Decimal)`;
  - `value_portfolio(holdings: list[Holding], cash: dict[int, dict[str, Decimal]], blocked_cash: dict[int, dict[str, Decimal]], prices: dict[int, LatestPrice], rates: dict[str, Decimal], rate_dates: dict[str, date]) -> Overview`;
  - у `Overview` появляется поле `unpriced: list[str]`.

- [ ] **Step 1: Написать падающий тест**

Дописать в `backend/tests/test_analytics.py`:

```python
from app.analytics.service import Holding, value_portfolio
from app.marketdata.service import LatestPrice


def test_value_portfolio_counts_securities_and_cash(session):
    instrument = Instrument(isin="RU000A0JQUZ6", ticker="AGRO", secid="AGRO",
                            currency="RUB", kind="share")
    session.add(instrument)
    session.flush()
    holdings = [Holding(account_id=1, instrument=instrument,
                        quantity=Decimal("10"), blocked=Decimal("0"))]
    prices = {instrument.id: LatestPrice(close=Decimal("100.0000"),
                                         on_date=date(2024, 6, 3),
                                         currency="RUB", source="moex")}

    overview = value_portfolio(
        holdings=holdings, cash={1: {"RUB": Decimal("500.0000")}}, blocked_cash={},
        prices=prices, rates={"RUB": Decimal("1")}, rate_dates={},
    )

    assert overview.total_value == Decimal("1500.0000")
    assert overview.securities_value == Decimal("1000.0000")
    assert overview.cash_value == Decimal("500.0000")
    assert overview.by_account == {1: Decimal("1500.0000")}


def test_value_portfolio_names_unpriced_positions(session):
    """«Оценено 1 из 2» не отвечает на вопрос, какой бумаги не хватило, а без
    ответа пункт не починить: список — это рабочий список сопоставлений."""
    priced = Instrument(isin="RU000A0JQUZ6", ticker="AGRO", secid="AGRO",
                        currency="RUB", kind="share", issuer="Русагро")
    unpriced = Instrument(isin="US87238U2033", ticker="US87238U2033", secid="US87238U2033",
                          currency="USD", kind="share", issuer="ТКС Холдинг")
    session.add_all([priced, unpriced])
    session.flush()

    overview = value_portfolio(
        holdings=[
            Holding(account_id=1, instrument=priced, quantity=Decimal("10"), blocked=Decimal("0")),
            Holding(account_id=1, instrument=unpriced, quantity=Decimal("5"), blocked=Decimal("0")),
        ],
        cash={}, blocked_cash={},
        prices={priced.id: LatestPrice(close=Decimal("100.0000"), on_date=date(2024, 6, 3),
                                       currency="RUB", source="moex")},
        rates={"RUB": Decimal("1")}, rate_dates={},
    )

    assert (overview.valued_positions, overview.positions_total) == (1, 2)
    assert overview.unpriced == ["ТКС Холдинг"]


def test_position_without_rate_is_named_too(session):
    instrument = Instrument(isin="KYG017191142", ticker="9988", secid="9988",
                            currency="HKD", kind="share", issuer="Alibaba")
    session.add(instrument)
    session.flush()

    overview = value_portfolio(
        holdings=[Holding(account_id=1, instrument=instrument,
                          quantity=Decimal("10"), blocked=Decimal("0"))],
        cash={}, blocked_cash={},
        prices={instrument.id: LatestPrice(close=Decimal("76.6500"), on_date=date(2024, 6, 3),
                                           currency="HKD", source="yahoo")},
        rates={"RUB": Decimal("1")}, rate_dates={},
    )

    assert overview.currencies_without_rate == ["HKD"]
    assert overview.unpriced == ["Alibaba"]
    assert overview.total_value == Decimal("0.0000")
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `cd backend && uv run pytest tests/test_analytics.py -v -k value_portfolio`
Expected: FAIL — `ImportError: cannot import name 'Holding'`.

- [ ] **Step 3: Разделить состав и оценку**

В `backend/app/analytics/service.py`:

Добавить входной тип и поле `unpriced` в `Overview`:

```python
@dataclass(frozen=True)
class Holding:
    """Позиция на вход оценки — вне зависимости от того, откуда она взялась.

    Сегодняшний состав приходит из таблицы `position`, исторический —
    восстановлен свёрткой журнала (app/positions/history.py). Оценка обязана не
    различать их: одна функция на оба пути — единственная гарантия, что
    достроенная точка графика не разойдётся с живой.
    """

    account_id: int
    instrument: Instrument
    quantity: Decimal
    # Заблокированная брокером часть. У исторической точки её взять неоткуда —
    # снимок блокировок текущий, — и приходит ноль: `restricted_value` такой
    # точки неполон и в снимке не хранится.
    blocked: Decimal
```

В `Overview` добавить поле после `positions_total`:

```python
    # Бумаги, которые оценить не удалось, — поимённо. Пара чисел покрытия
    # говорит «сколько», а починить можно только то, что названо.
    unpriced: list[str]
```

Заменить тело `portfolio_overview` на сбор состава и вызов оценки:

```python
def _holdings(session: Session) -> list[Holding]:
    blocked = blocked_by_instrument(session)
    return [
        Holding(
            account_id=account.id,
            instrument=instrument,
            quantity=position.quantity,
            blocked=blocked.get((account.id, instrument.id), Decimal("0")),
        )
        for position, instrument, account in _rows(session)
    ]


def portfolio_overview(session: Session) -> Overview:
    # Дата берётся один раз на весь обзор: два отдельных вызова разошлись бы на
    # сутки у прогона, начатого за миг до московской полуночи, и курсы оказались
    # бы датированы не тем днём, по которому посчитаны.
    today = moscow_today()
    return value_portfolio(
        holdings=_holdings(session),
        cash=cash_by_account(session),
        blocked_cash=blocked_cash_by_account(session),
        prices=prices_as_of(session, today),
        rates=latest_rates(session, today),
        rate_dates=latest_rate_dates(session, today),
    )


def value_portfolio(
    holdings: list[Holding],
    cash: dict[int, dict[str, Decimal]],
    blocked_cash: dict[int, dict[str, Decimal]],
    prices: dict[int, LatestPrice],
    rates: dict[str, Decimal],
    rate_dates: dict[str, date],
) -> Overview:
    """Оценка портфеля по готовому составу, ценам и курсам.

    Чистая: в базу не ходит и о том, «сегодня» это или 2021 год, не знает
    вовсе. Всё, что различает живой дашборд и достроенную точку истории, —
    аргументы.
    """
```

Тело функции — существующий код `portfolio_overview` со строки `by_class: dict[str, Decimal] = {}` до `return Overview(...)`, с четырьмя правками:

1. Цикл идёт по `holdings`, а не по `_rows(session)`:
   `for holding in holdings:` и внутри `instrument = holding.instrument`, `quantity = holding.quantity`, `account_id = holding.account_id`, `blocked_quantity = holding.blocked`.
2. `prices.get(...)`, `rates`, `rate_dates` берутся из аргументов, локальные вычисления удаляются.
3. Денежный цикл идёт по аргументу `cash`, а блокировки — по `blocked_cash`.
4. Неоценённые бумаги собираются в список и уезжают в `Overview`:

```python
    unpriced: list[str] = []
    ...
        if valued.value_base is None:
            if valued.value is not None and valued.currency:
                missing_rates.add(valued.currency.upper())
            # Название — то же, каким бумага подписана в таблице позиций
            # (issuer, иначе тикер, иначе ISIN): владелец ищет её глазами по
            # тому же имени.
            unpriced.append(
                instrument.issuer or instrument.ticker or instrument.isin or "—"
            )
            continue
```

и в `Overview(...)`: `unpriced=sorted(unpriced),`.

- [ ] **Step 4: Прогнать аналитику и API целиком**

Run: `cd backend && uv run pytest tests/test_analytics.py tests/test_api.py tests/test_valuation.py tests/test_cash.py -v`
Expected: PASS. Ни одна цифра существующих тестов меняться не должна: разделение — перестановка кода, а не смена правил.

- [ ] **Step 5: Проверить на живых данных, что дашборд не сдвинулся**

```bash
docker compose up -d --build backend
sleep 20
curl -s localhost:8001/api/portfolio/overview | python -m json.tool | head -20
```

Сравнить `total_value`, `securities_value`, `cash_value`, `valued_positions` с теми, что были до задачи (снять их до пересборки контейнера — образ со старым кодом ещё не перезаписан). Расхождение — дефект разделения, а не улучшение.

- [ ] **Step 6: Коммит**

```bash
git add backend/app/analytics/service.py backend/tests/test_analytics.py
git commit -m "refactor: оценка портфеля отделена от источника состава"
```

---

### Task 11: Снимок перестаёт быть безымянной цифрой

**Files:**
- Create: `backend/alembic/versions/0019_snapshot_source_and_coverage.py`
- Modify: `backend/app/models/snapshot.py`
- Test: `backend/tests/test_migrations.py`

**Interfaces:**
- Consumes: ничего.
- Produces: колонки `DailySnapshot.source: str`, `positions_total: int | None`, `valued_positions: int | None`, `unpriced: list`; константы `SNAPSHOT_LIVE = "live"`, `SNAPSHOT_BACKFILL = "backfill"`.

- [ ] **Step 1: Написать падающий тест**

Дописать в `backend/tests/test_models.py`:

```python
def test_snapshot_carries_origin_and_coverage(session):
    """Снимок, снятый живьём, и снимок, восстановленный задним числом, — разные
    утверждения о мире, и различать их обязана сама строка."""
    from app.models import SNAPSHOT_BACKFILL, DailySnapshot

    snapshot = DailySnapshot(
        on_date=date(2024, 6, 3), total_value=Decimal("100.0000"),
        by_asset_class={}, by_account={}, source=SNAPSHOT_BACKFILL,
        positions_total=59, valued_positions=57, unpriced=["ТКС Холдинг", "Block"],
    )
    session.add(snapshot)
    session.flush()
    session.expire(snapshot)

    assert snapshot.source == "backfill"
    assert (snapshot.valued_positions, snapshot.positions_total) == (57, 59)
    assert snapshot.unpriced == ["ТКС Холдинг", "Block"]


def test_snapshot_coverage_is_unknown_by_default(session):
    """У снимков, снятых до этой фазы, покрытие неизвестно, и NULL здесь
    означает ровно это. Заполнить его сегодняшним числом значило бы сочинить
    прошлое."""
    from app.models import DailySnapshot

    snapshot = DailySnapshot(on_date=date(2024, 6, 4), total_value=Decimal("100.0000"),
                             by_asset_class={}, by_account={})
    session.add(snapshot)
    session.flush()
    session.expire(snapshot)

    assert snapshot.source == "live"
    assert snapshot.valued_positions is None
    assert snapshot.unpriced == []
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `cd backend && uv run pytest tests/test_models.py -v -k snapshot`
Expected: FAIL — `TypeError: 'source' is an invalid keyword argument for DailySnapshot`.

- [ ] **Step 3: Расширить модель**

В `backend/app/models/snapshot.py`:

```python
from sqlalchemy import Date, Integer, Numeric, String, UniqueConstraint

# Происхождение снимка. Живой снят в свой день по состоянию, которое система
# тогда видела; достроенный восстановлен задним числом по журналу и истории
# котировок. Это разные утверждения о мире, и правило перезаписи опирается на
# различие (см. app/snapshots/service.py:store_snapshot).
SNAPSHOT_LIVE = "live"
SNAPSHOT_BACKFILL = "backfill"


class DailySnapshot(Base):
    __tablename__ = "daily_snapshot"
    __table_args__ = (UniqueConstraint("on_date", name="uq_snapshot_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    on_date: Mapped[date] = mapped_column(Date, index=True)
    total_value: Mapped[Decimal] = mapped_column(Numeric(20, 4))
    by_asset_class: Mapped[dict] = mapped_column(JSONB, default=dict)
    by_account: Mapped[dict] = mapped_column(JSONB, default=dict)
    source: Mapped[str] = mapped_column(String(16), default=SNAPSHOT_LIVE,
                                        server_default=SNAPSHOT_LIVE)
    # NULL — покрытие неизвестно, и это не то же самое, что ноль: у снимков,
    # снятых до фазы 2c, его никто не считал.
    positions_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    valued_positions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Бумаги без цены на эту дату, поимённо.
    unpriced: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
```

И добавить экспорт в `backend/app/models/__init__.py`: `SNAPSHOT_BACKFILL`, `SNAPSHOT_LIVE` в импорт из `app.models.snapshot` и в `__all__`.

- [ ] **Step 4: Написать миграцию**

Создать `backend/alembic/versions/0019_snapshot_source_and_coverage.py`:

```python
"""происхождение и покрытие у снимка стоимости

Revision ID: 0019
Revises: 0018

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0019'
down_revision: Union[str, Sequence[str], None] = '0018'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Существующие снимки сняты живьём — это про них известно точно.
    op.add_column('daily_snapshot', sa.Column('source', sa.String(16), nullable=False,
                                              server_default='live'))
    # А вот покрытие у них неизвестно, и NULL означает ровно это: заполнить его
    # сегодняшним числом значило бы сочинить прошлое. На этом же NULL стоит
    # правило перезаписи: снимок с неизвестным покрытием достройка перебивает.
    op.add_column('daily_snapshot', sa.Column('positions_total', sa.Integer(), nullable=True))
    op.add_column('daily_snapshot', sa.Column('valued_positions', sa.Integer(), nullable=True))
    op.add_column('daily_snapshot', sa.Column('unpriced', sa.dialects.postgresql.JSONB(),
                                              nullable=False, server_default='[]'))


def downgrade() -> None:
    op.drop_column('daily_snapshot', 'unpriced')
    op.drop_column('daily_snapshot', 'valued_positions')
    op.drop_column('daily_snapshot', 'positions_total')
    op.drop_column('daily_snapshot', 'source')
```

- [ ] **Step 5: Проверить накат и откат на живой базе**

```bash
cd backend
uv run alembic upgrade head
uv run alembic current
uv run alembic downgrade -1
uv run alembic upgrade head
```

Expected: `0019` в `alembic current`, откат и повторный накат без ошибок.

- [ ] **Step 6: Убедиться, что тесты проходят**

Run: `cd backend && uv run pytest tests/test_models.py tests/test_migrations.py -v`
Expected: PASS.

- [ ] **Step 7: Коммит**

```bash
git add backend/app/models/snapshot.py backend/app/models/__init__.py backend/alembic/versions/0019_snapshot_source_and_coverage.py backend/tests/test_models.py
git commit -m "feat: снимок стоимости несёт происхождение, покрытие и список неоценённых"
```

---

### Task 12: Правило перезаписи снимка

**Files:**
- Modify: `backend/app/snapshots/service.py:12-38`
- Create: `backend/tests/test_snapshot_backfill.py`

**Interfaces:**
- Consumes: `Overview`, `SNAPSHOT_LIVE`, `SNAPSHOT_BACKFILL`.
- Produces: `store_snapshot(session: Session, on_date: date, overview: Overview, source: str) -> DailySnapshot`; `take_snapshot(session, on_date)` сохраняет прежнюю сигнатуру и зовёт `store_snapshot` с `SNAPSHOT_LIVE`.

- [ ] **Step 1: Написать падающий тест**

Создать `backend/tests/test_snapshot_backfill.py`:

```python
from datetime import date
from decimal import Decimal

from app.analytics.service import Overview
from app.models import SNAPSHOT_BACKFILL, SNAPSHOT_LIVE, DailySnapshot
from app.snapshots.service import store_snapshot

DAY = date(2026, 8, 9)


def overview(total: str, valued: int | None, total_positions: int | None) -> Overview:
    return Overview(
        total_value=Decimal(total), securities_value=Decimal(total),
        cash_value=Decimal("0"), restricted_value=Decimal("0"),
        by_asset_class={}, by_account={}, by_currency={},
        position_currencies=[], currencies_without_rate=[],
        as_of=DAY, fx_as_of=DAY,
        valued_positions=valued, positions_total=total_positions, unpriced=[],
    )


def _stored(session) -> DailySnapshot:
    return session.query(DailySnapshot).filter(DailySnapshot.on_date == DAY).one()


def test_backfill_overwrites_a_snapshot_with_unknown_coverage(session):
    """Снимок 09.08.2026 снят живьём, но кодом до фазы 2a: в нём нет ни денег,
    ни двух третей позиций. Покрытие у него неизвестно, и это единственное, что
    достройке нужно знать, чтобы его перебить."""
    session.add(DailySnapshot(on_date=DAY, total_value=Decimal("6937338.9045"),
                              by_asset_class={}, by_account={}, source=SNAPSHOT_LIVE))
    session.flush()

    store_snapshot(session, DAY, overview("10948918.0777", 57, 59), SNAPSHOT_BACKFILL)

    stored = _stored(session)
    assert stored.total_value == Decimal("10948918.0777")
    assert stored.source == SNAPSHOT_BACKFILL


def test_backfill_does_not_overwrite_a_better_covered_live_snapshot(session):
    """Живой снимок не свят, но свято покрытие: достройка, оценившая меньше
    позиций, не имеет права затирать точку, где их оценено больше."""
    store_snapshot(session, DAY, overview("10948918.0777", 59, 59), SNAPSHOT_LIVE)

    store_snapshot(session, DAY, overview("1.0000", 40, 59), SNAPSHOT_BACKFILL)

    stored = _stored(session)
    assert stored.total_value == Decimal("10948918.0777")
    assert stored.source == SNAPSHOT_LIVE


def test_equal_coverage_leaves_the_live_snapshot_alone(session):
    """Равное покрытие — не повод переписывать: живой снимок снят по состоянию,
    которое система тогда видела, и это более прямое свидетельство."""
    store_snapshot(session, DAY, overview("10948918.0777", 57, 59), SNAPSHOT_LIVE)

    store_snapshot(session, DAY, overview("1.0000", 57, 59), SNAPSHOT_BACKFILL)

    assert _stored(session).total_value == Decimal("10948918.0777")


def test_a_run_can_always_refresh_its_own_snapshot(session):
    """Повторный прогон того же рода обязан обновлять свою же точку: иначе
    пересчёт после починки сопоставления символа не даст ничего."""
    store_snapshot(session, DAY, overview("1.0000", 57, 59), SNAPSHOT_BACKFILL)

    store_snapshot(session, DAY, overview("2.0000", 57, 59), SNAPSHOT_BACKFILL)

    assert _stored(session).total_value == Decimal("2.0000")
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `cd backend && uv run pytest tests/test_snapshot_backfill.py -v`
Expected: FAIL — `ImportError: cannot import name 'store_snapshot'`.

- [ ] **Step 3: Написать правило**

В `backend/app/snapshots/service.py` заменить `take_snapshot`:

```python
from sqlalchemy import or_

from app.analytics.service import Overview, portfolio_overview
from app.models import SNAPSHOT_LIVE, Account, DailySnapshot


def store_snapshot(
    session: Session, on_date: date, overview: Overview, source: str
) -> DailySnapshot:
    """Записывает точку истории, не затирая более полную.

    Правило одно: перезаписать можно свою же точку (повторный прогон обязан
    обновлять то, что сам записал) либо чужую, у которой покрытие меньше или
    неизвестно вовсе. Живой снимок не свят — свято покрытие: точка 09.08.2026
    снята живьём, но кодом, не знавшим ни денег, ни двух третей позиций.

    Выражено правилом, а не разовой правкой руками: прогон повторяется, и через
    месяц никто не вспомнит, какие даты правились.
    """
    values = {
        "on_date": on_date,
        "total_value": overview.total_value,
        "by_asset_class": {k: str(v) for k, v in overview.by_asset_class.items()},
        # Ключ — идентификатор счёта, а не его подпись. Подпись меняется вместе
        # с именем счёта и вместе с составом выборки, а снимок живёт годами:
        # снимки, снятые до и после переименования (или до и после появления
        # второго счёта с тем же именем), переставали склеиваться по счёту.
        # JSONB хранит ключи строками, поэтому идентификатор здесь — строка.
        "by_account": {str(account_id): str(value) for account_id, value in overview.by_account.items()},
        "source": source,
        "positions_total": overview.positions_total,
        "valued_positions": overview.valued_positions,
        "unpriced": overview.unpriced,
    }

    statement = insert(DailySnapshot).values(**values)
    statement = statement.on_conflict_do_update(
        index_elements=[DailySnapshot.on_date],
        set_={key: value for key, value in values.items() if key != "on_date"},
        where=or_(
            DailySnapshot.source == source,
            DailySnapshot.valued_positions.is_(None),
            DailySnapshot.valued_positions < statement.excluded.valued_positions,
        ),
    )
    session.execute(statement)
    session.flush()

    return session.query(DailySnapshot).filter(DailySnapshot.on_date == on_date).one()


def take_snapshot(session: Session, on_date: date) -> DailySnapshot:
    """Снимок сегодняшнего состояния — тот, что снимает планировщик."""
    return store_snapshot(session, on_date, portfolio_overview(session), SNAPSHOT_LIVE)
```

- [ ] **Step 4: Убедиться, что тесты проходят**

Run: `cd backend && uv run pytest tests/test_snapshot_backfill.py tests/test_scheduler.py tests/test_api.py -v`
Expected: PASS.

- [ ] **Step 5: Коммит**

```bash
git add backend/app/snapshots/service.py backend/tests/test_snapshot_backfill.py
git commit -m "feat: достройка перебивает снимок с меньшим покрытием"
```

---

### Task 13: Достройка одной даты и прогон по периоду

**Files:**
- Create: `backend/app/snapshots/backfill.py`
- Modify: `backend/tests/test_snapshot_backfill.py`

**Interfaces:**
- Consumes: `holdings_at`, `cash_history`, `value_portfolio`, `prices_as_of`, `latest_rates`, `latest_rate_dates`, `store_snapshot`, `ledger_entries`.
- Produces: `snapshot_at(session, on_date, *, entries_by_account, cash, accounts, instruments) -> DailySnapshot`; `backfill_snapshots(session, start: date, end: date) -> int`; `first_operation_date(session) -> date | None`; `main()`.

- [ ] **Step 1: Написать падающий тест**

Дописать в `backend/tests/test_snapshot_backfill.py`:

```python
from datetime import datetime, timezone

from app.models import Instrument, Price, Transaction
from app.snapshots.backfill import backfill_snapshots, first_operation_date


def _buy(session, account, instrument, day: str, quantity: str, price: str, external_id: str):
    session.add(Transaction(
        account_id=account.id, instrument_id=instrument.id, op_type=OperationType.BUY,
        executed_at=datetime.fromisoformat(day), quantity=Decimal(quantity),
        price=Decimal(price), amount=Decimal(price) * -Decimal(quantity), currency="RUB",
        fee=Decimal("0"), external_id=external_id, source="tbank",
        dedup_key=f"k-{external_id}", payload={},
    ))
    session.flush()


def test_backfill_builds_a_point_per_day(session, account):
    instrument = Instrument(isin="RU000A0JQUZ6", ticker="AGRO", secid="AGRO",
                            currency="RUB", kind="share", issuer="Русагро")
    session.add(instrument)
    session.flush()
    _buy(session, account, instrument, "2024-06-03T10:00:00+00:00", "10", "100", "a")
    for day, close in [(date(2024, 6, 3), "100"), (date(2024, 6, 4), "110")]:
        session.add(Price(instrument_id=instrument.id, on_date=day, close=Decimal(close),
                          currency="RUB", source="moex"))
    session.flush()

    written = backfill_snapshots(session, date(2024, 6, 3), date(2024, 6, 4))

    assert written == 2
    points = session.query(DailySnapshot).order_by(DailySnapshot.on_date).all()
    assert [(p.on_date, p.total_value, p.source) for p in points] == [
        (date(2024, 6, 3), Decimal("1000.0000"), SNAPSHOT_BACKFILL),
        (date(2024, 6, 4), Decimal("1100.0000"), SNAPSHOT_BACKFILL),
    ]
    assert points[0].valued_positions == 1 and points[0].positions_total == 1


def test_backfill_records_coverage_when_a_price_is_missing(session, account):
    """День без цены — не день без портфеля: точка обязана появиться и назвать,
    чего в ней не хватило."""
    instrument = Instrument(isin="US87238U2033", ticker="US87238U2033", secid="US87238U2033",
                            currency="USD", kind="share", issuer="ТКС Холдинг")
    session.add(instrument)
    session.flush()
    _buy(session, account, instrument, "2024-06-03T10:00:00+00:00", "10", "100", "a")

    backfill_snapshots(session, date(2024, 6, 3), date(2024, 6, 3))

    point = session.query(DailySnapshot).one()
    assert (point.valued_positions, point.positions_total) == (0, 1)
    assert point.unpriced == ["ТКС Холдинг"]


def test_first_operation_date_is_the_start_of_history(session, account):
    instrument = Instrument(isin="RU000A0JQUZ6", ticker="AGRO", secid="AGRO",
                            currency="RUB", kind="share")
    session.add(instrument)
    session.flush()
    _buy(session, account, instrument, "2020-07-16T10:00:00+00:00", "1", "100", "a")
    _buy(session, account, instrument, "2024-06-03T10:00:00+00:00", "1", "100", "b")

    assert first_operation_date(session) == date(2020, 7, 16)
```

Добавить в начало файла недостающие импорты (`OperationType`).

- [ ] **Step 2: Убедиться, что тест падает**

Run: `cd backend && uv run pytest tests/test_snapshot_backfill.py -v -k "per_day or coverage or first_operation"`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.snapshots.backfill'`.

- [ ] **Step 3: Написать достройку**

Создать `backend/app/snapshots/backfill.py`:

```python
"""Достройка истории стоимости задним числом.

Запуск (из каталога backend):

    uv run python -m app.snapshots.backfill
    uv run python -m app.snapshots.backfill --from 2024-01-01 --to 2024-12-31

В сеть не ходит вовсе: считает по журналу, по уже загруженной истории цен и
курсов (`uv run python -m app.marketdata.backfill`) и по сегодняшним остаткам
брокера. Разделение не косметическое: пересчёт понадобится повторять — после
разбора расхождений владельцем, после починки сопоставления символа, — и если
каждый пересчёт заново выгребает сеть, его не будут делать вовсе.

Прогон идемпотентен: правило перезаписи живёт в `store_snapshot`.
"""

import argparse
import logging
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.accounts.cash_history import cash_history
from app.analytics.service import Holding, value_portfolio
from app.db import SessionLocal
from app.marketdata.fx import latest_rate_dates, latest_rates
from app.marketdata.service import prices_as_of
from app.models import SNAPSHOT_BACKFILL, Account, DailySnapshot, Instrument, Transaction
from app.positions.history import holdings_at
from app.positions.service import ledger_entries
from app.snapshots.service import store_snapshot
from app.timeutils import moscow_today

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def first_operation_date(session: Session) -> date | None:
    """Дата первой операции журнала — начало истории портфеля."""
    earliest = session.execute(select(func.min(Transaction.executed_at))).scalar()
    return earliest.date() if earliest is not None else None


def backfill_snapshots(session: Session, start: date, end: date) -> int:
    """Достраивает точки истории за период. Возвращает число записанных дней.

    Журнал каждого счёта читается один раз на весь период, а не на каждую дату:
    двух тысяч обходов таблицы операций прогон бы не пережил. Цены и курсы, в
    отличие от него, спрашиваются на каждую дату — они и есть то, что меняется.
    """
    accounts = list(session.execute(select(Account)).scalars())
    entries = {account.id: ledger_entries(session, account) for account in accounts}
    instruments = {
        instrument.id: instrument
        for instrument in session.execute(select(Instrument)).scalars()
    }
    cash = cash_history(session, start, end)

    written = 0
    day = start
    while day <= end:
        holdings: list[Holding] = []
        for account in accounts:
            for instrument_id, state in holdings_at(entries[account.id], day).items():
                holdings.append(Holding(
                    account_id=account.id,
                    instrument=instruments[instrument_id],
                    quantity=state.quantity,
                    # Блокировки на прошлую дату взять неоткуда: снимок
                    # блокировок у брокера текущий. Ноль честнее подстановки
                    # сегодняшнего значения — оно к 2021 году отношения не имеет.
                    blocked=Decimal("0"),
                ))

        overview = value_portfolio(
            holdings=holdings,
            cash=cash.get(day, {}),
            blocked_cash={},
            prices=prices_as_of(session, day),
            rates=latest_rates(session, day),
            rate_dates=latest_rate_dates(session, day),
        )
        store_snapshot(session, day, overview, SNAPSHOT_BACKFILL)
        written += 1

        if day.day == 1:
            logger.info("Достроено по %s: %s ₽, оценено %s из %s",
                        day, overview.total_value,
                        overview.valued_positions, overview.positions_total)
        day += timedelta(days=1)

    session.flush()
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description="Достройка истории стоимости портфеля")
    parser.add_argument("--from", dest="start", type=date.fromisoformat, default=None,
                        help="начало периода; по умолчанию — дата первой операции журнала")
    parser.add_argument("--to", dest="end", type=date.fromisoformat, default=None,
                        help="конец периода; по умолчанию — сегодня")
    args = parser.parse_args()

    with SessionLocal() as session:
        start = args.start or first_operation_date(session)
        if start is None:
            logger.warning("Журнал пуст — достраивать нечего")
            return
        end = args.end or moscow_today()

        written = backfill_snapshots(session, start, end)
        session.commit()

        points = session.execute(
            select(
                func.count(DailySnapshot.id),
                func.count(DailySnapshot.id).filter(
                    DailySnapshot.valued_positions == DailySnapshot.positions_total
                ),
            )
        ).one()
        logger.info("Достроено дней: %s (с %s по %s)", written, start, end)
        logger.info("Точек всего %s, из них с полной оценкой %s", points[0], points[1])


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Убедиться, что тесты проходят**

Run: `cd backend && uv run pytest tests/test_snapshot_backfill.py -v`
Expected: PASS, семь тестов.

- [ ] **Step 5: Коммит**

```bash
git add backend/app/snapshots/backfill.py backend/tests/test_snapshot_backfill.py
git commit -m "feat: прогон достройки истории стоимости"
```

---

### Task 14: Прогон загрузки истории цен и курсов

**Files:**
- Create: `backend/app/marketdata/backfill.py`

**Interfaces:**
- Consumes: `load_price_history`, `load_fx_history`, `load_metal_history`, `MoexClient`, `YahooClient`, `CbrClient`, `first_operation_date`.
- Produces: `history_currencies(session) -> list[str]`; `main()`.

- [ ] **Step 1: Написать прогон**

Создать `backend/app/marketdata/backfill.py`:

```python
"""Разовая загрузка исторических котировок и курсов.

Запуск (из каталога backend):

    uv run python -m app.marketdata.backfill
    uv run python -m app.marketdata.backfill --from 2024-01-01
    uv run python -m app.marketdata.backfill --dry-run

Ходит в сеть: MOEX по бумагам российских эмитентов, Yahoo по иностранным, ЦБ
по валютам, MOEX по золоту. Объём — сотни запросов, минуты работы. Пишет в
`price` и `fx_rate`; повторный прогон обновляет уже загруженное, а не двоит.

`--dry-run` ничего не загружает, а показывает таблицу сопоставлений: какая
бумага куда пойдёт и под каким символом. Смотреть её до первого прогона
обязательно — неверно сопоставленный символ даёт не отказ, а правдоподобную
цену чужой бумаги.
"""

import argparse
import logging
from datetime import date

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.marketdata.cbr import CbrClient
from app.marketdata.history import load_fx_history, load_metal_history, load_price_history
from app.marketdata.moex import MoexClient
from app.marketdata.symbols import priced_at_moex, yahoo_symbol
from app.marketdata.yahoo import YahooClient
from app.models import CashBalance, Instrument, Transaction
from app.money import BASE_CURRENCY
from app.snapshots.backfill import first_operation_date
from app.timeutils import moscow_today

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def history_currencies(session: Session) -> list[str]:
    """Валюты, для которых нужна история курсов.

    Собираются из трёх мест сразу: валюты операций (в них шли расчёты), валюты
    инструментов (в них номинированы цены) и валюты сегодняшних остатков.
    Металлы сюда не входят — у ЦБ их нет, они идут с MOEX отдельно.
    """
    currencies: set[str] = set()
    for column, model in ((Transaction.currency, Transaction),
                          (Instrument.currency, Instrument),
                          (CashBalance.currency, CashBalance)):
        for value in session.execute(select(column).distinct()).scalars():
            if value:
                currencies.add(value.upper())
    currencies.discard(BASE_CURRENCY)
    currencies -= {"XAU", "XAG", "XPT", "XPD"}
    return sorted(currencies)


def _report_mapping(session: Session) -> None:
    instruments = list(session.execute(select(Instrument).order_by(Instrument.isin)).scalars())
    unresolved: list[Instrument] = []
    for instrument in instruments:
        if priced_at_moex(instrument):
            logger.info("MOEX   %-14s %-12s %s", instrument.isin, instrument.secid,
                        instrument.issuer or "")
            continue
        symbol = yahoo_symbol(instrument)
        if symbol is None:
            unresolved.append(instrument)
            continue
        logger.info("Yahoo  %-14s %-12s %s", instrument.isin, symbol, instrument.issuer or "")

    logger.info("")
    logger.info("Не сопоставлено: %s из %s", len(unresolved), len(instruments))
    for instrument in unresolved:
        logger.info("  %-14s %-12s %s", instrument.isin, instrument.ticker or "",
                    instrument.issuer or "")
    logger.info("")
    logger.info("Каждая несопоставленная бумага останется неоценённой на тех датах, "
                "где она лежала в портфеле. Символ добавляется в "
                "YAHOO_SYMBOL_BY_ISIN (app/marketdata/symbols.py).")


def main() -> None:
    parser = argparse.ArgumentParser(description="Загрузка истории котировок и курсов")
    parser.add_argument("--from", dest="start", type=date.fromisoformat, default=None,
                        help="начало периода; по умолчанию — дата первой операции журнала")
    parser.add_argument("--to", dest="end", type=date.fromisoformat, default=None,
                        help="конец периода; по умолчанию — сегодня")
    parser.add_argument("--dry-run", action="store_true",
                        help="показать сопоставление бумаг с источниками и выйти")
    args = parser.parse_args()

    with SessionLocal() as session:
        if args.dry_run:
            _report_mapping(session)
            return

        start = args.start or first_operation_date(session)
        if start is None:
            logger.warning("Журнал пуст — загружать историю не для чего")
            return
        end = args.end or moscow_today()

        moex, yahoo, cbr = MoexClient(), YahooClient(), CbrClient()

        instruments = list(session.execute(select(Instrument).order_by(Instrument.id)).scalars())
        loaded = 0
        for number, instrument in enumerate(instruments, start=1):
            try:
                days = load_price_history(session, instrument, start, end, moex=moex, yahoo=yahoo)
            except httpx.HTTPError:
                # Отказ источника по одной бумаге не должен ронять прогон на
                # двести пятьдесят бумаг: бумага останется неоценённой, и это
                # будет видно в покрытии, а не потеряно.
                logger.warning("Инструмент %s (%s): источник недоступен",
                               instrument.id, instrument.isin, exc_info=True)
                continue
            loaded += days
            if days:
                logger.info("[%s/%s] %s: дней %s", number, len(instruments),
                            instrument.isin or instrument.ticker, days)
            session.commit()

        currencies = history_currencies(session)
        rates = load_fx_history(session, currencies, start, end, cbr=cbr)
        metals = load_metal_history(session, start, end, moex=moex)
        session.commit()

        logger.info("Загружено дней котировок: %s по %s инструментам", loaded, len(instruments))
        logger.info("Курсов: %s по валютам %s; металлов: %s", rates, ", ".join(currencies), metals)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Проверить, что прогон запускается и показывает сопоставление**

```bash
docker compose up -d db
cd backend && uv run python -m app.marketdata.backfill --dry-run
```

Expected: список бумаг с источниками и отдельным списком несопоставленных. **Показать этот список владельцу и дождаться подтверждения до первого настоящего прогона** — это outward-facing артефакт: по нему решается, какие бумаги останутся без истории.

- [ ] **Step 3: Коммит**

```bash
git add backend/app/marketdata/backfill.py
git commit -m "feat: прогон загрузки истории котировок и курсов"
```

---

### Task 15: Контракт истории

**Files:**
- Modify: `backend/app/api/schemas.py:104-118`
- Modify: `backend/app/api/routes_portfolio.py:97-130`
- Test: `backend/tests/test_api.py`

**Interfaces:**
- Consumes: `snapshot_by_account`.
- Produces: `HistoryPointOut` с полями `date`, `total_value`, `by_account`, `source`, `valued_positions`, `positions_total`, `unpriced`; `GET /api/portfolio/history?days=<n>` — без `days` отдаёт весь период.

- [ ] **Step 1: Написать падающий тест**

Дописать в `backend/tests/test_api.py`:

```python
def test_history_returns_the_whole_period_by_default(client, session):
    """По умолчанию окно было девяносто дней, и достроенной истории за шесть
    лет в нём не видно вовсе."""
    session.add_all([
        DailySnapshot(on_date=date(2020, 7, 16), total_value=Decimal("1000.0000"),
                      by_asset_class={}, by_account={}, source="backfill",
                      positions_total=1, valued_positions=1, unpriced=[]),
        DailySnapshot(on_date=moscow_today(), total_value=Decimal("2000.0000"),
                      by_asset_class={}, by_account={}, source="live",
                      positions_total=2, valued_positions=1, unpriced=["ТКС Холдинг"]),
    ])
    session.commit()

    rows = client.get("/api/portfolio/history").json()

    assert [row["date"] for row in rows] == ["2020-07-16", moscow_today().isoformat()]


def test_history_point_carries_origin_and_coverage(client, session):
    session.add(DailySnapshot(on_date=date(2024, 6, 3), total_value=Decimal("1000.0000"),
                              by_asset_class={}, by_account={}, source="backfill",
                              positions_total=59, valued_positions=57,
                              unpriced=["ТКС Холдинг", "Block"]))
    session.commit()

    row = client.get("/api/portfolio/history").json()[0]

    assert row["source"] == "backfill"
    assert (row["valued_positions"], row["positions_total"]) == (57, 59)
    assert row["unpriced"] == ["ТКС Холдинг", "Block"]


def test_history_window_still_works_when_asked(client, session):
    session.add_all([
        DailySnapshot(on_date=date(2020, 7, 16), total_value=Decimal("1000.0000"),
                      by_asset_class={}, by_account={}),
        DailySnapshot(on_date=moscow_today(), total_value=Decimal("2000.0000"),
                      by_asset_class={}, by_account={}),
    ])
    session.commit()

    rows = client.get("/api/portfolio/history?days=30").json()

    assert [row["date"] for row in rows] == [moscow_today().isoformat()]
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `cd backend && uv run pytest tests/test_api.py -v -k history`
Expected: FAIL — в ответе нет ключа `source`, и первая точка не возвращается.

- [ ] **Step 3: Расширить схему**

В `backend/app/api/schemas.py`:

```python
class HistoryPointOut(BaseModel):
    date: date
    total_value: Decimal
    # Разбивка по счетам, подписанным той же единственной на проект функцией,
    # что и везде (app/accounts/labels.py). В самом снимке лежит устойчивый
    # идентификатор счёта — подпись строится при чтении.
    by_account: dict[str, Decimal] = {}
    # Происхождение точки: снята живьём в свой день или восстановлена задним
    # числом. Разные утверждения о мире, и на экране они не должны выглядеть
    # одинаково уверенно.
    source: str
    # Покрытие оценкой. None — неизвестно: у точек, снятых до фазы 2c, его
    # никто не считал, и ноль тут был бы враньём.
    valued_positions: int | None = None
    positions_total: int | None = None
    # Бумаги без цены на эту дату, поимённо: пара чисел говорит «сколько», а
    # искать глазами владелец будет по имени.
    unpriced: list[str] = []
```

- [ ] **Step 4: Отдавать весь период по умолчанию**

В `backend/app/api/routes_portfolio.py`:

```python
@router.get("/portfolio/history", response_model=list[HistoryPointOut])
def get_history(
    days: int | None = None, session: Session = Depends(get_session)
) -> list[HistoryPointOut]:
    # Без окна — вся история: после достройки график начинается датой первой
    # операции, и девяностодневное окно по умолчанию прятало бы шесть лет.
    query = select(DailySnapshot).order_by(DailySnapshot.on_date)
    if days is not None:
        # Дата берётся в московском поясе явно: снимки пишутся под московской
        # календарной датой (см. app/timeutils.py), и окно истории обязано
        # отсчитываться от той же, а не от даты по поясу контейнера.
        query = query.where(DailySnapshot.on_date >= moscow_today() - timedelta(days=days))
    rows = session.execute(query).scalars().all()
    ...
    return [
        HistoryPointOut(
            date=row.on_date,
            total_value=row.total_value,
            by_account=snapshot_by_account(accounts, row),
            source=row.source,
            valued_positions=row.valued_positions,
            positions_total=row.positions_total,
            unpriced=row.unpriced or [],
        )
        for row in rows
    ]
```

- [ ] **Step 5: Убедиться, что тесты проходят**

Run: `cd backend && uv run pytest tests/test_api.py -v`
Expected: PASS.

- [ ] **Step 6: Коммит**

```bash
git add backend/app/api/schemas.py backend/app/api/routes_portfolio.py backend/tests/test_api.py
git commit -m "feat: история отдаёт весь период вместе с происхождением и покрытием точки"
```

---

### Task 16: График показывает, чего в нём не хватает

**Files:**
- Modify: `frontend/src/api/client.ts:68-74,178`
- Modify: `frontend/src/components/ValueChart.tsx`
- Modify: `frontend/src/pages/PortfolioPage.tsx:16`
- Create: `frontend/src/components/ValueChart.test.tsx`

**Interfaces:**
- Consumes: `HistoryPoint`.
- Produces: `HistoryPoint` с полями `source: string`, `valued_positions: number | null`, `positions_total: number | null`, `unpriced: string[]`; `api.history(days?: number)`.

- [ ] **Step 1: Написать падающий тест**

Создать `frontend/src/components/ValueChart.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ValueChart } from "./ValueChart";
import type { HistoryPoint } from "../api/client";

// Настоящий ECharts в jsdom не рисует; проверяем то, что ему передано, —
// именно это и есть содержание графика.
const captured: { option: Record<string, unknown> | null } = { option: null };

vi.mock("echarts-for-react", () => ({
  default: ({ option }: { option: Record<string, unknown> }) => {
    captured.option = option;
    return <div data-testid="chart" />;
  },
}));

function point(overrides: Partial<HistoryPoint>): HistoryPoint {
  return {
    date: "2024-06-03",
    total_value: "1000.0000",
    by_account: {},
    source: "backfill",
    valued_positions: 2,
    positions_total: 2,
    unpriced: [],
    ...overrides,
  };
}

const FULL = point({ date: "2024-06-03" });
const PARTIAL = point({
  date: "2024-06-04",
  total_value: "900.0000",
  valued_positions: 1,
  positions_total: 2,
  unpriced: ["ТКС Холдинг"],
});

describe("ValueChart", () => {
  it("рисует линию по всем точкам", () => {
    render(<ValueChart points={[FULL, PARTIAL]} error={null} loading={false} />);

    const series = captured.option!.series as Array<{ type: string; data: unknown[] }>;
    expect(series[0].type).toBe("line");
    expect(series[0].data).toEqual([1000, 900]);
  });

  it("отмечает отдельной серией даты с неполной оценкой", () => {
    render(<ValueChart points={[FULL, PARTIAL]} error={null} loading={false} />);

    const series = captured.option!.series as Array<{ type: string; data: unknown[] }>;
    const incomplete = series.find((item) => item.type === "scatter")!;
    expect(incomplete.data).toEqual([[1, 900]]);
  });

  it("не отмечает точки, у которых покрытие неизвестно", () => {
    // У снимков, снятых до фазы 2c, покрытие не считали: NULL значит
    // «неизвестно», и объявлять их неполными — такое же враньё, как полными.
    const unknown = point({ valued_positions: null, positions_total: null });

    render(<ValueChart points={[FULL, unknown]} error={null} loading={false} />);

    const series = captured.option!.series as Array<{ type: string; data: unknown[] }>;
    expect(series.find((item) => item.type === "scatter")!.data).toEqual([]);
  });

  it("показывает график по одной точке", () => {
    // Заглушка про «накопится два снимка» после достройки перестала быть
    // правдой: история приходит целиком, а не копится по дню.
    render(<ValueChart points={[FULL]} error={null} loading={false} />);

    expect(screen.getByTestId("chart")).toBeInTheDocument();
  });

  it("сбой запроса не выдаётся за отсутствие данных", () => {
    render(<ValueChart points={[]} error="сеть недоступна" loading={false} />);

    expect(screen.getByText(/сеть недоступна/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `cd frontend && pnpm exec vitest run src/components/ValueChart.test.tsx`
Expected: FAIL — в переданной опции нет серии `scatter`.

- [ ] **Step 3: Расширить контракт фронта**

В `frontend/src/api/client.ts`:

```ts
export interface HistoryPoint {
  date: string;
  total_value: string;
  // Разбивка итога по счетам на эту дату; ключ — подпись счёта. Пусто у
  // снимков, снятых до появления разбивки.
  by_account: Record<string, string>;
  // "live" — точка снята в свой день, "backfill" — восстановлена задним числом.
  source: string;
  // Покрытие оценкой. null — неизвестно: у снимков, снятых до достройки, его
  // не считали, и это не то же самое, что ноль.
  valued_positions: number | null;
  positions_total: number | null;
  // Бумаги без цены на эту дату, поимённо.
  unpriced: string[];
}
```

И запрос без окна по умолчанию:

```ts
  history: (days?: number) =>
    request<HistoryPoint[]>(`/portfolio/history${days ? `?days=${days}` : ""}`),
```

В `frontend/src/pages/PortfolioPage.tsx`:

```tsx
  const history = useQuery({ queryKey: ["history"], queryFn: () => api.history() });
```

- [ ] **Step 4: Переписать график**

Заменить `frontend/src/components/ValueChart.tsx`:

```tsx
import ReactECharts from "echarts-for-react";
import { formatDate } from "../api/format";
import type { HistoryPoint } from "../api/client";

// Точка неполна, когда оценены не все позиции. Неизвестное покрытие (null у
// снимков, снятых до достройки) неполнотой не считается: объявить их неполными
// — такое же враньё, как объявить полными.
function isIncomplete(point: HistoryPoint): boolean {
  return (
    point.valued_positions !== null &&
    point.positions_total !== null &&
    point.valued_positions < point.positions_total
  );
}

export function ValueChart({ points, error, loading }: {
  points: HistoryPoint[];
  error: string | null;
  loading: boolean;
}) {
  // Сбой запроса — не то же самое, что «истории ещё нет»: заглушка про
  // накопление снимков при реальном сбое сети была бы враньём.
  if (error) {
    return (
      <div className="card" style={{ color: "var(--red)", fontSize: 13 }}>
        Не удалось загрузить историю стоимости: {error}
      </div>
    );
  }

  if (loading) {
    return (
      <div className="card" style={{ color: "var(--tx-2)", fontSize: 13 }}>Загрузка истории…</div>
    );
  }

  if (points.length === 0) {
    return (
      <div className="card" style={{ color: "var(--tx-2)", fontSize: 13 }}>
        Истории пока нет: достройте её прогоном app.snapshots.backfill.
      </div>
    );
  }

  const values = points.map((point) => Number.parseFloat(point.total_value));
  const incomplete = points
    .map((point, index) => (isIncomplete(point) ? [index, values[index]] : null))
    .filter((item): item is number[] => item !== null);

  return (
    <div className="card">
      <div style={{ color: "var(--tx-2)", fontSize: 12, marginBottom: 8 }}>Стоимость портфеля</div>
      <ReactECharts
        style={{ height: 260 }}
        option={{
          grid: { left: 60, right: 16, top: 16, bottom: 32 },
          // Та же функция форматирования даты, что и в шапке страницы —
          // подписи оси не должны расходиться по формату с остальным интерфейсом.
          xAxis: { type: "category", data: points.map((p) => formatDate(p.date) ?? p.date),
                   axisLine: { lineStyle: { color: "#3a4763" } } },
          yAxis: { type: "value", scale: true, splitLine: { lineStyle: { color: "#1c2438" } },
                   axisLabel: { color: "#9aa5c4" } },
          tooltip: {
            trigger: "axis",
            formatter: (params: Array<{ dataIndex: number }>) => {
              const point = points[params[0].dataIndex];
              const value = Number.parseFloat(point.total_value).toLocaleString("ru-RU", {
                maximumFractionDigits: 0,
              });
              const head = `${formatDate(point.date) ?? point.date}<br/>${value} ₽`;
              if (!isIncomplete(point)) return head;
              // Названия бумаг, а не только счёт: искать глазами владелец
              // будет по имени, а «оценено 57 из 59» не говорит, каких.
              const names = point.unpriced.join(", ");
              return `${head}<br/>оценено ${point.valued_positions} из ${point.positions_total}` +
                     (names ? `<br/>нет цены: ${names}` : "");
            },
          },
          series: [
            {
              type: "line", smooth: true, showSymbol: false,
              lineStyle: { color: "#638cff", width: 2 },
              areaStyle: { color: "rgba(99,140,255,0.18)" },
              data: values,
            },
            {
              // Неполнота передаётся и цветом, и формой: спека системы требует,
              // чтобы факт и предположение различались, а цвет в одиночку не
              // различает их для того, кто его не видит.
              type: "scatter", symbol: "triangle", symbolSize: 8,
              itemStyle: { color: "#e2b93b" },
              data: incomplete,
            },
          ],
        }}
      />
      {incomplete.length > 0 && (
        <div style={{ color: "var(--tx-2)", fontSize: 12, marginTop: 8 }}>
          ▲ — дни, где оценены не все позиции: цены на эти бумаги нет ни на бирже, ни у брокера.
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 5: Убедиться, что тесты и типы проходят**

```bash
cd frontend
pnpm exec vitest run
pnpm run build
```

Expected: все тесты PASS, сборка без ошибок типов (остаётся только прежнее предупреждение о размере чанка).

- [ ] **Step 6: Коммит**

```bash
git add frontend/src/api/client.ts frontend/src/components/ValueChart.tsx frontend/src/components/ValueChart.test.tsx frontend/src/pages/PortfolioPage.tsx
git commit -m "feat: график стоимости отмечает даты с неполной оценкой"
```

---

### Task 17: Прогон на живых данных и признак готовности

Здесь фаза либо закрывается, либо нет. Задача не пишет кода — она измеряет четыре утверждения из раздела 7 дизайна и записывает измеренное.

**Files:**
- Modify: `README.md`
- Modify: `docs/roadmap.md`

- [ ] **Step 1: Снять замер «до» на старом образе**

Пока контейнер бэкенда ещё не пересобран (тома с исходником у него нет — внутри код `main`):

```bash
docker compose up -d
curl -s localhost:8001/api/portfolio/overview > /tmp/overview-before.json
curl -s localhost:8001/api/portfolio/history > /tmp/history-before.json
cat /tmp/overview-before.json | python -m json.tool | head -20
```

- [ ] **Step 2: Пересобрать и накатить миграцию**

```bash
docker compose up -d --build backend frontend
sleep 25
docker exec jarvis-investment-backend-1 uv run alembic current
```

Expected: `0019`.

- [ ] **Step 3: Показать владельцу сопоставление и дождаться подтверждения**

```bash
cd backend && uv run python -m app.marketdata.backfill --dry-run
```

**Остановиться и показать список.** Несопоставленные бумаги останутся без истории; символ добавляется в `YAHOO_SYMBOL_BY_ISIN`. Продолжать только после ответа владельца.

- [ ] **Step 4: Загрузить историю**

```bash
cd backend && uv run python -m app.marketdata.backfill 2>&1 | tee /tmp/prices.log
```

Записать: сколько дней котировок загружено, по скольким инструментам, сколько курсов, какие бумаги отказали и почему.

- [ ] **Step 5: Достроить снимки**

```bash
cd backend && uv run python -m app.snapshots.backfill 2>&1 | tee /tmp/snapshots.log
```

- [ ] **Step 6: Измерить четыре утверждения**

**7.1 — график начинается датой первой операции:**

```bash
docker exec jarvis-investment-db-1 psql -U jarvis -d jarvis -c "
select min(on_date) as первая, max(on_date) as последняя, count(*) as точек from daily_snapshot;
select min(executed_at)::date as первая_операция from transaction;"
```

**7.2 — достроенная точка за 10.08.2026 сходится с живым снимком того же дня.** Живой снимок за 10.08 в базе уже есть; достройка его не перезапишет (покрытие живого неизвестно — перезапишет; поэтому замер снять до достройки либо посчитать точку отдельно):

```bash
docker exec jarvis-investment-db-1 psql -U jarvis -d jarvis -c "
select on_date, source, total_value, valued_positions, positions_total from daily_snapshot
where on_date between '2026-08-09' and '2026-08-12' order by on_date;"
```

Сравнить `total_value` достроенной точки за 10.08 с 10 948 918,0777 из замера «до» (`/tmp/history-before.json`). Расхождение допустимо только от цены; разбивки по счетам и по классам активов обязаны сойтись каждая по отдельности — две ошибки разного знака дают верную сумму при неверном составе:

```bash
docker exec jarvis-investment-db-1 psql -U jarvis -d jarvis -c "
select on_date, by_account, by_asset_class from daily_snapshot where on_date = '2026-08-10';"
```

**7.3 — восстановленный остаток на дату открытия каждого счёта:**

```bash
cd backend && uv run python -c "
from datetime import timedelta
from app.accounts.cash_history import cash_history
from app.db import SessionLocal
from app.snapshots.backfill import first_operation_date
from sqlalchemy import func, select
from app.models import Account, Transaction

with SessionLocal() as session:
    for account in session.execute(select(Account)).scalars():
        opened = session.execute(
            select(func.min(Transaction.executed_at)).where(Transaction.account_id == account.id)
        ).scalar()
        if opened is None:
            continue
        day = opened.date() - timedelta(days=1)
        history = cash_history(session, day, day)
        print(account.name, history.get(day, {}).get(account.id, {}))
"
```

Ожидание: близко к нулю по каждому счёту. На «Инвестиционном» — заведомо не ноль (журнал расходится с сегодняшним остатком брокера на 53 083,71 ₽). **Записать полученные числа: это измеренная мера качества всего восстановления.**

**7.4 — доля дат с полной оценкой:**

```bash
docker exec jarvis-investment-db-1 psql -U jarvis -d jarvis -c "
select count(*) as всего,
       count(*) filter (where valued_positions = positions_total) as полных,
       round(100.0 * count(*) filter (where valued_positions = positions_total) / count(*), 1) as процент
from daily_snapshot where source = 'backfill';"
docker exec jarvis-investment-db-1 psql -U jarvis -d jarvis -c "
select name, count(*) from (
  select jsonb_array_elements_text(unpriced) as name from daily_snapshot
) t group by 1 order by 2 desc limit 20;"
```

- [ ] **Step 7: Посмотреть глазами**

Открыть `http://localhost:3000`. Убедиться: график начинается 2020 годом, ступеньки 6,94 → 10,93 млн нет, дни с неполной оценкой отмечены треугольниками, подсказка называет бумаги.

- [ ] **Step 8: Обновить README**

В `README.md` рядом с описанием `app.valuation_check` добавить раздел о двух прогонах фазы 2c: что делает каждый, чем они разделены, что `--dry-run` показывает сопоставление и его надо смотреть до первого прогона.

- [ ] **Step 9: Обновить роадмеп**

В `docs/roadmap.md`: в разделе 2c дописать «завершена <дата>» и «как закрылось» с измеренными числами из шага 6; в таблице «Статус» сменить состояние фазы 2c и назвать следующую (3. Дизайн); в разделе «Где мы сейчас» заменить пункт «График стоимости пуст» на то, что измерено; проверить попутный долг — пункт про двойную запись правила «числовой ключ снимка» стал ближе, раз достройка теперь пишет `by_account` тем же способом.

- [ ] **Step 10: Прогнать всё**

```bash
cd backend && uv run pytest -q
cd ../frontend && pnpm exec vitest run && pnpm run build
```

Expected: бэкенд и фронтенд зелёные, сборка без ошибок типов.

- [ ] **Step 11: Коммит**

```bash
git add README.md docs/roadmap.md
git commit -m "docs: итоги фазы 2c на живых данных"
```

---

## Самопроверка плана

**Покрытие дизайна.** Раздел 4.1 (источники истории) — задачи 1, 2, 4, 5, 6. Раздел 4.2 (маршрут и символ) — задача 3. Раздел 4.3 (состав на дату) — задача 8. Раздел 4.4 (деньги на дату) — задача 9. Раздел 4.5 (оценка, `prices_as_of` с предельным возрастом) — задачи 7 и 10. Раздел 5 (модель и правило перезаписи) — задачи 11 и 12. Раздел 6 (два прогона) — задачи 13 и 14. Раздел 7 (признак готовности) — задача 17. Раздел 8 (интерфейс) — задачи 15 и 16. Раздел 9 (риски: отказ Yahoo, неверный символ) — закрыт в задачах 5 (проверка валюты), 14 (`--dry-run` и устойчивость к отказу) и 17 (показ сопоставления владельцу). Раздел 10 (что не входит) — задач нет намеренно.

**Согласованность имён.** `prices_as_of` — задачи 7, 10, 13. `value_portfolio` и `Holding` — задачи 10, 13. `holdings_at` — задачи 8, 13. `cash_history` — задачи 9, 13, 17. `store_snapshot` — задачи 12, 13. `ledger_entries` — задачи 8, 13. `priced_at_moex` / `yahoo_symbol` / `moex_isin_filter` — задачи 3, 5, 14. `MoexHistoryPoint` — задачи 1, 5, 6. `YahooHistory` — задачи 2, 5. `SNAPSHOT_LIVE` / `SNAPSHOT_BACKFILL` — задачи 11, 12, 13. `Overview.unpriced` — задачи 10, 12, 13, 15.

**Замеченное при проверке и учтённое в задачах.** В задаче 9 первая редакция кода считала московскую дату операции вычитанием разницы двух моментов — это неверно, и шаг 4 задачи заменяет выражение на явное `astimezone(MOSCOW_TZ).date()`. В задаче 7 предельный возраст цены меняет поведение живого дашборда, поэтому в неё добавлен отдельный шаг с проверкой на живых данных и указанием остановиться, если проверка покажет отсечение. В задаче 17 шаг 6 оговаривает, что замер 7.2 надо снимать до достройки: правило перезаписи перебивает живой снимок с неизвестным покрытием, и после прогона сравнивать будет уже не с чем.
