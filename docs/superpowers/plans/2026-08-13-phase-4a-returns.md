# Фаза 4a «Доходность» — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** показать владельцу XIRR и TWR портфеля, разрезы по счетам, классам
активов и бумагам и разложение прибыли на ценовую и валютную части — считая всё
на лету из журнала операций и ежедневных снимков.

**Architecture:** новый пакет `backend/app/returns/` из шести модулей с одной
обязанностью каждый: ставка (`xirr.py`), курс на дату (`rates.py`), денежные
потоки (`flows.py`), цепочка дневных приростов (`twr.py`), разложение прибыли
(`fx_split.py`) и сборка ответа (`service.py`). Ничего не хранится и не
кешируется: расчёт идёт при запросе. Один обработчик API отдаёт весь ответ, один
новый экран фронта его показывает.

**Tech Stack:** Python 3.12, SQLAlchemy 2.0, FastAPI, Pydantic v2, pytest,
PostgreSQL 16 · React 19, TypeScript, TanStack Query, Tailwind 3.4, `cva`,
vitest, Testing Library.

## Global Constraints

- **Дизайн фазы:** [`docs/superpowers/specs/2026-08-13-phase-4a-returns-design.md`](../specs/2026-08-13-phase-4a-returns-design.md).
  Расхождение с ним — дефект реализации, а не улучшение.
- **Все деньги — `Decimal`, никогда `float`.** На фронт суммы отдаются строками.
  Единственное исключение уже существует и не расширяется: `formatPercent` во
  фронте.
- **Округление денег — через `app.money.money()`**, а не `round()`.
- **Проверки, зависящие от типа операции, поднимают данные из базы**, а не строят
  `LedgerEntry` в памяти: из строковой колонки значение приходило как `str`, и
  сравнение с членом enum молча давало ложь (правило фазы 2b, тест
  `tests/test_operation_type_enum.py`).
- **Инлайновых стилей во фронте быть не может.** `style={{` разрешён ровно в
  `ValueChart.tsx` и `AllocationChart.tsx`, hex-литералы — только в
  `frontend/src/design/tokens.ts`. Проверяется `cd frontend && pnpm check:styles
  --strict` и обязана оставаться зелёной.
- **Экран собирается из примитивов фазы 3** (`Card`, `CardTitle`, `CardState`,
  `Table`, `Badge`, `SegmentedControl`, `AsOfLabel`, `CoverageNotice`). Не хватило
  примитива — это находка про дизайн-систему: остановиться и сказать вслух, а не
  дорисовывать.
- **Пустое место на экране без названной причины не появляется.** У каждого
  отсутствующего числа есть `reason`, и он показывается словами.
- **Бэкенд не трогает журнал.** Фаза только читает: ни миграций, ни новых таблиц,
  ни правок маппера.
- **Порты нестандартные:** база 5433, бэкенд 8001, фронт 3000. `uv` лежит в
  `C:\Users\User\.local\bin` и в PATH может отсутствовать.
- **Команды:** бэкенд — `cd backend && uv run pytest`, фронт — `cd frontend &&
  pnpm exec vitest run` (команды `pnpm test` в проекте нет), типы — `cd frontend
  && pnpm run build`.
- **Коммиты** — по-русски, в стиле истории проекта: `feat: …`, `test: …`,
  `docs: …`. Авторство LLM не указывается.

## Карта файлов

| Файл | Ответственность |
|---|---|
| `backend/app/returns/__init__.py` | пустой, пакет |
| `backend/app/returns/xirr.py` | ставка по списку потоков; приведённая стоимость |
| `backend/app/returns/rates.py` | `RateBook` — курс валюты к рублю на любую дату |
| `backend/app/returns/flows.py` | денежные потоки четырёх периметров из журнала |
| `backend/app/returns/twr.py` | цепочка дневных приростов по снимкам |
| `backend/app/returns/fx_split.py` | разложение прибыли на ценовую и валютную части |
| `backend/app/returns/service.py` | периоды, сборка отчёта, покрытие |
| `backend/app/returns/check.py` | повторяемый прогон на живых данных |
| `backend/app/api/routes_analytics.py` | обработчик `GET /api/analytics/returns` |
| `backend/app/api/schemas.py` | схемы ответа (дополняется) |
| `backend/app/main.py` | подключение роутера (дополняется) |
| `frontend/src/api/client.ts` | типы ответа и вызов (дополняется) |
| `frontend/src/pages/AnalyticsPage.tsx` | экран «Аналитика» |
| `frontend/src/components/ReturnsSummary.tsx` | две доходности с пояснением |
| `frontend/src/components/ReturnsBreakdown.tsx` | таблица разреза |
| `frontend/src/app/routes.tsx` | пункт меню (дополняется) |
| `frontend/src/components/SummaryCard.tsx` | две цифры на «Портфеле» (дополняется) |

`rates.py` в дизайне отдельным файлом не назван — там перечислены четыре модуля
расчёта. Он выделен потому, что курс на дату нужен и `flows.py`, и `fx_split.py`:
общая зависимость двух модулей в одном из них — это скрытая связь между ними.

---

### Задача 1: ставка XIRR

**Files:**
- Create: `backend/app/returns/__init__.py`
- Create: `backend/app/returns/xirr.py`
- Test: `backend/tests/test_returns_xirr.py`

**Interfaces:**
- Consumes: `app.money.money`
- Produces: `Flow(on_date: date, amount: Decimal)` — датакласс потока, вложение
  отрицательно; `npv(flows: list[Flow], rate: Decimal) -> Decimal`;
  `xirr(flows: list[Flow]) -> Decimal | None`.

- [ ] **Step 1: Write the failing test**

Создать `backend/tests/test_returns_xirr.py`:

```python
from datetime import date
from decimal import Decimal

from app.returns.xirr import Flow, npv, xirr


def test_year_of_ten_percent():
    """Тысяча рублей, вложенная на ровно 365 дней и вернувшаяся 1100, — это
    десять процентов годовых, и никакого метода тут не нужно, чтобы это знать."""
    flows = [
        Flow(date(2021, 1, 1), Decimal("-1000")),
        Flow(date(2022, 1, 1), Decimal("1100")),
    ]
    rate = xirr(flows)
    assert rate is not None
    assert abs(rate - Decimal("0.1")) < Decimal("0.0001")


def test_loss_gives_negative_rate():
    flows = [
        Flow(date(2021, 1, 1), Decimal("-1000")),
        Flow(date(2022, 1, 1), Decimal("500")),
    ]
    rate = xirr(flows)
    assert rate is not None
    assert abs(rate - Decimal("-0.5")) < Decimal("0.0001")


def test_same_sign_flows_have_no_rate():
    """Ставки не существует: деньги только вносились. None — это ответ, а не
    сбой, и вызывающий обязан назвать причину словами."""
    flows = [
        Flow(date(2021, 1, 1), Decimal("-1000")),
        Flow(date(2022, 1, 1), Decimal("-500")),
    ]
    assert xirr(flows) is None


def test_empty_and_single_flow():
    assert xirr([]) is None
    assert xirr([Flow(date(2021, 1, 1), Decimal("-1000"))]) is None


def test_zero_result_is_minus_one_hundred_percent():
    """Вложил и почти ничего не вернул: ставка у нижней границы поиска."""
    flows = [
        Flow(date(2021, 1, 1), Decimal("-1000")),
        Flow(date(2022, 1, 1), Decimal("1")),
    ]
    rate = xirr(flows)
    assert rate is not None
    assert rate < Decimal("-0.99")


def test_root_outside_search_range_has_no_rate():
    """Убыток настолько полный, что ставка уходит ниже границы поиска
    (−1000 → +0,01 за год даёт −99,999 %). Вернуть край отрезка значило бы
    выдать границу поиска за результат расчёта — поэтому None."""
    flows = [
        Flow(date(2021, 1, 1), Decimal("-1000")),
        Flow(date(2022, 1, 1), Decimal("0.01")),
    ]
    assert xirr(flows) is None


def test_result_satisfies_its_own_definition():
    """Признак готовности фазы, пункт 1: дисконтирование потоков по найденной
    ставке даёт ноль в пределах копейки. Набор нарочно неровный — семь лет,
    разные знаки, суммы от сотен рублей до миллионов."""
    flows = [
        Flow(date(2020, 7, 16), Decimal("-1500000")),
        Flow(date(2021, 3, 2), Decimal("-250000")),
        Flow(date(2022, 9, 12), Decimal("340")),
        Flow(date(2023, 11, 30), Decimal("-780000")),
        Flow(date(2025, 5, 5), Decimal("120000")),
        Flow(date(2026, 8, 13), Decimal("3100000")),
    ]
    rate = xirr(flows)
    assert rate is not None
    assert abs(npv(flows, rate)) < Decimal("0.01")


def test_npv_at_zero_rate_is_plain_sum():
    flows = [
        Flow(date(2021, 1, 1), Decimal("-1000")),
        Flow(date(2022, 1, 1), Decimal("1100")),
    ]
    assert npv(flows, Decimal("0")) == Decimal("100")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_returns_xirr.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.returns'`

- [ ] **Step 3: Write minimal implementation**

Создать пустой `backend/app/returns/__init__.py` и `backend/app/returns/xirr.py`:

```python
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

# Годовая база. Високосные годы отдельно не учитываются: на горизонте шести лет
# разница уходит в четвёртый знак после запятой в процентах, а объяснять
# владельцу две ставки, различающиеся в четвёртом знаке, дороже этой точности.
DAYS_IN_YEAR = Decimal("365")

# Сходимость по невязке приведённой стоимости — копейка. Та же копейка, которой
# меряется признак готовности фазы: ставка, дающая ноль с точностью до копейки,
# проверяема определением, а не доверием к методу.
NPV_TOLERANCE = Decimal("0.01")

# Границы поиска. Нижняя чуть выше −100 %: ровно при −100 % основание (1 + r)
# обращается в ноль и деление на него невозможно. Верхняя — тысяча процентов
# годовых: доходность выше неё у портфеля означает ошибку в данных, а не удачу.
MIN_RATE = Decimal("-0.9999")
MAX_RATE = Decimal("10")

# Шагов бисекции: 200 половинных делений отрезка длиной 11 сужают его далеко за
# пределы значащих разрядов Decimal, то есть цикл всегда упирается в допуск, а
# не в счётчик. Счётчик здесь — предохранитель от бесконечного цикла.
BISECTION_STEPS = 200
NEWTON_STEPS = 50


@dataclass(frozen=True)
class Flow:
    """Денежный поток владельца. Знак — с его точки зрения: вложение
    отрицательно, изъятие положительно. Конечная стоимость портфеля — тоже
    изъятие: это то, что владелец получил бы, продав всё сегодня."""

    on_date: date
    amount: Decimal


def _years(flow: Flow, start: date) -> Decimal:
    return Decimal((flow.on_date - start).days) / DAYS_IN_YEAR


def npv(flows: list[Flow], rate: Decimal) -> Decimal:
    """Приведённая стоимость потоков по ставке. Точка приведения — дата первого
    потока: она сокращается при поиске корня и на ставку не влияет."""
    if not flows:
        return Decimal("0")

    start = min(flow.on_date for flow in flows)
    base = Decimal("1") + rate
    total = Decimal("0")
    for flow in flows:
        total += flow.amount / (base ** _years(flow, start))
    return total


def _derivative(flows: list[Flow], rate: Decimal) -> Decimal:
    start = min(flow.on_date for flow in flows)
    base = Decimal("1") + rate
    total = Decimal("0")
    for flow in flows:
        years = _years(flow, start)
        total -= years * flow.amount / (base ** (years + Decimal("1")))
    return total


def _has_both_signs(flows: list[Flow]) -> bool:
    return any(flow.amount > 0 for flow in flows) and any(flow.amount < 0 for flow in flows)


def _bisect(flows: list[Flow]) -> Decimal | None:
    low, high = MIN_RATE, MAX_RATE
    low_value, high_value = npv(flows, low), npv(flows, high)
    if low_value * high_value > 0:
        # Корня на отрезке нет: доходность вне разумных границ. Молча вернуть
        # край отрезка значило бы выдать границу поиска за результат расчёта.
        return None

    for _ in range(BISECTION_STEPS):
        middle = (low + high) / Decimal("2")
        value = npv(flows, middle)
        if abs(value) < NPV_TOLERANCE:
            return middle
        if value * low_value > 0:
            low, low_value = middle, value
        else:
            high = middle
    return (low + high) / Decimal("2")


def xirr(flows: list[Flow]) -> Decimal | None:
    """Годовая ставка, при которой приведённая стоимость потоков равна нулю.

    None — законный ответ: у набора потоков одного знака корня не существует, и
    подставлять вместо него ноль или прочерк нельзя. Ноль означал бы «вложения
    ничего не принесли», а на деле неизвестно, принесли ли.
    """
    if len(flows) < 2 or not _has_both_signs(flows):
        return None

    rate = Decimal("0.1")
    for _ in range(NEWTON_STEPS):
        value = npv(flows, rate)
        if abs(value) < NPV_TOLERANCE:
            return rate
        slope = _derivative(flows, rate)
        if slope == 0:
            break
        step = value / slope
        rate = rate - step
        if rate <= MIN_RATE or rate >= MAX_RATE:
            # Ньютон вылетел за область определения — дальше только бисекция.
            break

    # Ньютон не сошёлся: у знакопеременных потоков поверхность бывает пологой, и
    # шаг уводит за корень. Бисекция медленнее, но сходится всегда, когда корень
    # на отрезке есть.
    return _bisect(flows)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_returns_xirr.py -v`
Expected: PASS, 7 tests

- [ ] **Step 5: Commit**

```bash
git add backend/app/returns/__init__.py backend/app/returns/xirr.py backend/tests/test_returns_xirr.py
git commit -m "feat: ставка XIRR с самопроверкой по определению"
```

---

### Задача 2: курс валюты на дату

**Files:**
- Create: `backend/app/returns/rates.py`
- Test: `backend/tests/test_returns_rates.py`

**Interfaces:**
- Consumes: `app.models.FxRate`, `app.money.money`, `app.money.BASE_CURRENCY`
- Produces: `RateBook` с методами `load(session) -> RateBook`,
  `rate(currency: str, on_date: date) -> Decimal | None`,
  `to_base(amount: Decimal, currency: str, on_date: date) -> Decimal | None`.

Зачем отдельный модуль: `app.marketdata.fx.latest_rates` отдаёт курсы **на одну
дату** и делает запрос к базе на каждый вызов. Потоков в журнале двенадцать
тысяч, дат среди них — тысячи; вызов на поток дал бы тысячи запросов. `RateBook`
читает таблицу один раз и отвечает на любую дату в памяти.

- [ ] **Step 1: Write the failing test**

Создать `backend/tests/test_returns_rates.py`:

```python
from datetime import date
from decimal import Decimal

from app.models import FxRate
from app.returns.rates import RateBook


def add_rate(session, currency: str, on_date: date, rate: str) -> None:
    session.add(FxRate(currency=currency, on_date=on_date, rate=Decimal(rate), source="cbr"))
    session.flush()


def test_rate_on_exact_date(session):
    add_rate(session, "USD", date(2024, 3, 1), "92.5")
    book = RateBook.load(session)
    assert book.rate("USD", date(2024, 3, 1)) == Decimal("92.5")


def test_weekend_takes_last_published_rate(session):
    """ЦБ не публикует курсы по выходным. Операция субботы обязана считаться по
    пятничному курсу, а не оставаться без курса вовсе."""
    add_rate(session, "USD", date(2024, 3, 1), "92.5")
    add_rate(session, "USD", date(2024, 3, 5), "93.1")
    book = RateBook.load(session)
    assert book.rate("USD", date(2024, 3, 3)) == Decimal("92.5")


def test_before_first_publication_there_is_no_rate(session):
    """До первой известной даты курса нет. Ближайший будущий курс сюда
    подставлять нельзя: это выдумка о прошлом."""
    add_rate(session, "USD", date(2024, 3, 1), "92.5")
    book = RateBook.load(session)
    assert book.rate("USD", date(2020, 1, 1)) is None


def test_base_currency_is_always_one(session):
    book = RateBook.load(session)
    assert book.rate("RUB", date(2020, 1, 1)) == Decimal("1")


def test_unknown_currency_has_no_rate(session):
    book = RateBook.load(session)
    assert book.rate("SGD", date(2024, 3, 1)) is None


def test_to_base_converts_and_rounds(session):
    add_rate(session, "USD", date(2024, 3, 1), "92.5")
    book = RateBook.load(session)
    assert book.to_base(Decimal("10"), "USD", date(2024, 3, 1)) == Decimal("925.0000")


def test_to_base_without_rate_is_none(session):
    book = RateBook.load(session)
    assert book.to_base(Decimal("10"), "USD", date(2024, 3, 1)) is None


def test_case_of_currency_does_not_matter(session):
    add_rate(session, "USD", date(2024, 3, 1), "92.5")
    book = RateBook.load(session)
    assert book.rate("usd", date(2024, 3, 1)) == Decimal("92.5")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_returns_rates.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.returns.rates'`

- [ ] **Step 3: Write minimal implementation**

Создать `backend/app/returns/rates.py`:

```python
from bisect import bisect_right
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import FxRate
from app.money import BASE_CURRENCY, money


class RateBook:
    """Курсы к рублю на любую дату прошлого, прочитанные один раз.

    `app.marketdata.fx.latest_rates` отвечает на вопрос «курсы на сегодня» и
    ходит в базу при каждом вызове. Здесь вопрос другой — «курс на дату каждой
    из двенадцати тысяч операций», и запрос на операцию превратил бы расчёт
    доходности в тысячи запросов.
    """

    def __init__(self, series: dict[str, tuple[list[date], list[Decimal]]]):
        self._series = series

    @classmethod
    def load(cls, session: Session) -> "RateBook":
        rows = session.execute(
            select(FxRate.currency, FxRate.on_date, FxRate.rate).order_by(FxRate.on_date)
        ).all()

        series: dict[str, tuple[list[date], list[Decimal]]] = {}
        for currency, on_date, rate in rows:
            dates, values = series.setdefault(currency.upper(), ([], []))
            dates.append(on_date)
            values.append(rate)
        return cls(series)

    def rate(self, currency: str, on_date: date) -> Decimal | None:
        """Самый свежий курс не позже даты. None — курса на эту дату нет вовсе.

        Ближайший будущий курс не подставляется: сегодняшний доллар ничего не
        говорит о том, сколько он стоил в день сделки 2021 года.
        """
        code = currency.upper()
        if code == BASE_CURRENCY:
            # Рубль к рублю — единица, и в таблице её нет: строка, которая
            # никогда не меняется, лишь создаёт впечатление, что её можно не
            # найти (то же решение, что в app/marketdata/fx.py).
            return Decimal("1")

        found = self._series.get(code)
        if found is None:
            return None

        dates, values = found
        index = bisect_right(dates, on_date)
        if index == 0:
            return None
        return values[index - 1]

    def to_base(self, amount: Decimal, currency: str, on_date: date) -> Decimal | None:
        rate = self.rate(currency, on_date)
        if rate is None:
            return None
        return money(amount * rate)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_returns_rates.py -v`
Expected: PASS, 8 tests

- [ ] **Step 5: Commit**

```bash
git add backend/app/returns/rates.py backend/tests/test_returns_rates.py
git commit -m "feat: курс валюты на любую дату одной выборкой"
```

---
### Задача 3: внешние потоки портфеля и счёта

**Files:**
- Create: `backend/app/returns/flows.py`
- Modify: `backend/app/timeutils.py` (добавить `moscow_date`)
- Test: `backend/tests/test_returns_flows.py`

**Interfaces:**
- Consumes: `RateBook` из задачи 2, `app.models.Transaction`,
  `app.models.OperationType`, `app.timeutils.MOSCOW_TZ`
- Produces: `CashFlow(on_date, amount, account_id, transaction_id)`;
  `portfolio_flows(session, book, since=None, until=None) -> list[CashFlow]`;
  `account_flows(session, book, account_id, since=None, until=None) -> list[CashFlow]`;
  `app.timeutils.moscow_date(moment: datetime) -> date`.

Знак потока един и выводится из одного правила: **поток владельца — это минус
движение денег на счёте**. Пополнение (`DEPOSIT`, `amount` положителен) — деньги
пришли на счёт, владелец их вложил, поток отрицателен. Вывод (`WITHDRAWAL`,
`amount` отрицателен) — поток положителен. Замер живых данных подтверждает знаки:
`INP_MULTI` +40 000, `OUT_MULTI` −40 000.

- [ ] **Step 1: Write the failing test**

Создать `backend/tests/test_returns_flows.py`:

```python
from datetime import date, datetime, time
from decimal import Decimal
from itertools import count

from app.models import Account, FxRate, OperationType, Transaction
from app.returns.flows import account_flows, portfolio_flows
from app.returns.rates import RateBook
from app.timeutils import MOSCOW_TZ

_ids = count(1)


def add_tx(session, *, account_id: int, op_type: OperationType, day: date, amount: str,
           currency: str = "RUB", instrument_id: int | None = None,
           quantity: str = "0", price: str = "0", fee: str = "0",
           payload: dict | None = None, at_hour: int = 12) -> Transaction:
    """Запись журнала для теста. Тесты потоков поднимают данные ИЗ БАЗЫ, а не
    строят LedgerEntry в памяти: op_type приходит из строковой колонки, и
    сравнение с членом enum на объекте из памяти ничего не доказывает
    (правило фазы 2b, tests/test_operation_type_enum.py)."""
    number = next(_ids)
    tx = Transaction(
        account_id=account_id, instrument_id=instrument_id, op_type=op_type,
        executed_at=datetime.combine(day, time(at_hour, 0), tzinfo=MOSCOW_TZ),
        quantity=Decimal(quantity), price=Decimal(price), amount=Decimal(amount),
        currency=currency, fee=Decimal(fee), external_id=f"ext-{number}",
        source="test", dedup_key=f"dedup-{number}", payload=payload or {},
    )
    session.add(tx)
    session.flush()
    return tx


def second_account(session) -> Account:
    account = Account(broker="tbank", kind="broker", external_id="acc-2",
                      name="Копилка", currency="RUB")
    session.add(account)
    session.flush()
    return account


def test_deposit_is_negative_flow(session, account):
    add_tx(session, account_id=account.id, op_type=OperationType.DEPOSIT,
           day=date(2024, 3, 1), amount="100000")
    flows = portfolio_flows(session, RateBook.load(session))
    assert [(flow.on_date, flow.amount) for flow in flows] == [
        (date(2024, 3, 1), Decimal("-100000.0000"))
    ]


def test_withdrawal_is_positive_flow(session, account):
    add_tx(session, account_id=account.id, op_type=OperationType.WITHDRAWAL,
           day=date(2024, 3, 1), amount="-25000")
    flows = portfolio_flows(session, RateBook.load(session))
    assert flows[0].amount == Decimal("25000.0000")


def test_transfer_between_own_accounts_is_not_a_flow(session, account):
    """Живой случай 12.09.2022: 25 000 ₽ со счёта 7 на счёт 1. Для портфеля это
    перекладывание, а не приход капитала извне."""
    other = second_account(session)
    add_tx(session, account_id=account.id, op_type=OperationType.DEPOSIT,
           day=date(2022, 9, 12), amount="25000")
    add_tx(session, account_id=other.id, op_type=OperationType.WITHDRAWAL,
           day=date(2022, 9, 12), amount="-25000")
    assert portfolio_flows(session, RateBook.load(session)) == []


def test_multi_transfer_hidden_in_other_is_also_a_pair(session, account):
    """Живой случай 13.04.2026: та же пара переводов лежит в журнале с
    op_type=OTHER, потому что брокер прислал её как INP_MULTI/OUT_MULTI. Читать
    только op_type — значит не увидеть 40 000 ₽ движения вовсе."""
    other = second_account(session)
    add_tx(session, account_id=account.id, op_type=OperationType.OTHER,
           day=date(2026, 4, 13), amount="40000",
           payload={"operation_type": "OPERATION_TYPE_INP_MULTI"})
    add_tx(session, account_id=other.id, op_type=OperationType.OTHER,
           day=date(2026, 4, 13), amount="-40000",
           payload={"operation_type": "OPERATION_TYPE_OUT_MULTI"})
    assert portfolio_flows(session, RateBook.load(session)) == []


def test_same_account_pair_is_not_a_transfer(session, account):
    """Ввод и вывод одной суммы в один день на ОДНОМ счёте переводом между
    своими счетами не являются: перекладывать некуда."""
    add_tx(session, account_id=account.id, op_type=OperationType.DEPOSIT,
           day=date(2024, 3, 1), amount="10000")
    add_tx(session, account_id=account.id, op_type=OperationType.WITHDRAWAL,
           day=date(2024, 3, 1), amount="-10000")
    flows = portfolio_flows(session, RateBook.load(session))
    assert sorted(flow.amount for flow in flows) == [
        Decimal("-10000.0000"), Decimal("10000.0000")
    ]


def test_different_currency_is_not_a_pair(session, account):
    other = second_account(session)
    session.add(FxRate(currency="USD", on_date=date(2024, 3, 1),
                       rate=Decimal("90"), source="cbr"))
    session.flush()
    add_tx(session, account_id=account.id, op_type=OperationType.DEPOSIT,
           day=date(2024, 3, 1), amount="1000", currency="USD")
    add_tx(session, account_id=other.id, op_type=OperationType.WITHDRAWAL,
           day=date(2024, 3, 1), amount="-1000", currency="RUB")
    flows = portfolio_flows(session, RateBook.load(session))
    assert len(flows) == 2


def test_account_perimeter_keeps_the_transfer(session, account):
    """Тот же перевод в разрезе по счёту — настоящий поток: для счёта деньги
    действительно пришли."""
    other = second_account(session)
    add_tx(session, account_id=account.id, op_type=OperationType.DEPOSIT,
           day=date(2022, 9, 12), amount="25000")
    add_tx(session, account_id=other.id, op_type=OperationType.WITHDRAWAL,
           day=date(2022, 9, 12), amount="-25000")
    flows = account_flows(session, RateBook.load(session), account.id)
    assert [flow.amount for flow in flows] == [Decimal("-25000.0000")]


def test_currency_flow_is_converted_by_rate_of_its_day(session, account):
    """Курс берётся на дату операции, а не сегодняшний: доллар 2021 года стоил
    других денег, и пересчёт по сегодняшнему курсу превратил бы вложение в
    другое число."""
    session.add(FxRate(currency="USD", on_date=date(2021, 6, 1),
                       rate=Decimal("72.5"), source="cbr"))
    session.add(FxRate(currency="USD", on_date=date(2026, 8, 1),
                       rate=Decimal("81"), source="cbr"))
    session.flush()
    add_tx(session, account_id=account.id, op_type=OperationType.DEPOSIT,
           day=date(2021, 6, 1), amount="1000", currency="USD")
    flows = portfolio_flows(session, RateBook.load(session))
    assert flows[0].amount == Decimal("-72500.0000")


def test_flow_without_rate_is_reported_not_dropped(session, account):
    """Поток без курса не выбрасывается молча: он попадает в отдельный список,
    и служба обязана назвать его в покрытии."""
    from app.returns.flows import unconverted_flows

    add_tx(session, account_id=account.id, op_type=OperationType.DEPOSIT,
           day=date(2021, 6, 1), amount="1000", currency="HKD")
    book = RateBook.load(session)
    assert portfolio_flows(session, book) == []
    assert unconverted_flows(session, book) == ["HKD"]


def test_period_bounds_are_inclusive(session, account):
    for day in (date(2024, 1, 1), date(2024, 6, 1), date(2024, 12, 31)):
        add_tx(session, account_id=account.id, op_type=OperationType.DEPOSIT,
               day=day, amount="1000")
    flows = portfolio_flows(session, RateBook.load(session),
                            since=date(2024, 6, 1), until=date(2024, 12, 31))
    assert [flow.on_date for flow in flows] == [date(2024, 6, 1), date(2024, 12, 31)]


def test_late_evening_operation_belongs_to_moscow_day(session, account):
    """23:30 по Москве — это ещё сегодня, хотя по UTC уже 20:30. Дата потока
    обязана считаться в том же поясе, что и дата снимка (app/timeutils.py)."""
    add_tx(session, account_id=account.id, op_type=OperationType.DEPOSIT,
           day=date(2024, 3, 1), amount="1000", at_hour=23)
    flows = portfolio_flows(session, RateBook.load(session))
    assert flows[0].on_date == date(2024, 3, 1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_returns_flows.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.returns.flows'`

- [ ] **Step 3: Write minimal implementation**

Сначала дописать в `backend/app/timeutils.py` (после `moscow_today`):

```python
def moscow_date(moment: datetime) -> date:
    """Календарная дата момента по Москве.

    Журнал хранит время в UTC, а календарная дата операции обязана совпадать с
    той, в которой живут снимки и график: операция 21:30 UTC — это уже
    следующий московский день.
    """
    return moment.astimezone(MOSCOW_TZ).date()
```

Создать `backend/app/returns/flows.py`:

```python
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import OperationType, Transaction
from app.returns.rates import RateBook
from app.timeutils import moscow_date

# Ключ payload, под которым лежит исходный тип операции брокера.
RAW_TYPE_KEY = "operation_type"

# Ввод и вывод денег, приехавшие от брокера как мультивалютные: в журнале у них
# op_type = OTHER, потому что маппер их не знает. Замер 13.08.2026: 13.04.2026
# ровно такой парой ходят 40 000 ₽ между счетами 1 и 7, и по op_type их не
# видно вовсе. Маппер фаза не чинит — журнал append-only, и переписывание
# истории это отдельный разговор.
RAW_CASH_MOVE_TYPES = {"OPERATION_TYPE_INP_MULTI", "OPERATION_TYPE_OUT_MULTI"}

CASH_MOVE_TYPES = {OperationType.DEPOSIT, OperationType.WITHDRAWAL}


@dataclass(frozen=True)
class CashFlow:
    """Денежный поток периметра, в рублях. Знак — с точки зрения владельца:
    вложение отрицательно, изъятие положительно. Это ровно минус движение денег
    на счёте: пополнение счёта — вложение владельца."""

    on_date: date
    amount: Decimal
    account_id: int
    transaction_id: int


def _is_cash_move(transaction: Transaction) -> bool:
    if transaction.op_type in CASH_MOVE_TYPES:
        return True
    return (transaction.payload or {}).get(RAW_TYPE_KEY) in RAW_CASH_MOVE_TYPES


def _cash_moves(session: Session) -> list[Transaction]:
    rows = session.execute(
        select(Transaction)
        .where(Transaction.op_type.in_([*CASH_MOVE_TYPES, OperationType.OTHER]))
        .order_by(Transaction.executed_at, Transaction.id)
    ).scalars().all()
    return [row for row in rows if _is_cash_move(row)]


def _in_period(day: date, since: date | None, until: date | None) -> bool:
    if since is not None and day < since:
        return False
    return until is None or day <= until


def _pair_key(transaction: Transaction) -> tuple[date, str, Decimal]:
    return (moscow_date(transaction.executed_at),
            transaction.currency.upper(),
            abs(transaction.amount))


def _paired_ids(moves: list[Transaction]) -> set[int]:
    """Идентификаторы записей, гасящих друг друга: перевод между своими счетами.

    Пара — ввод и вывод одного московского дня, равные по модулю, в одной
    валюте, на РАЗНЫХ счетах. Подбор жадный, каждая запись входит не более чем в
    одну пару. Замер 13.08.2026 на живых данных: за шесть лет таких пар две, и
    обе настоящие. Ложное срабатывание завысило бы доходность, приняв пополнение
    за перекладывание, — поэтому условие узкое, а не «похоже по сумме».
    """
    by_key: dict[tuple[date, str, Decimal], list[Transaction]] = {}
    for move in moves:
        by_key.setdefault(_pair_key(move), []).append(move)

    paired: set[int] = set()
    for group in by_key.values():
        incoming = [move for move in group if move.amount > 0]
        outgoing = [move for move in group if move.amount < 0]
        for income, outcome in zip(incoming, outgoing):
            if income.account_id == outcome.account_id:
                # Один счёт — перекладывать некуда: это настоящие ввод и вывод,
                # случайно совпавшие по сумме и дню.
                continue
            paired.add(income.id)
            paired.add(outcome.id)
    return paired


def _to_flow(transaction: Transaction, book: RateBook) -> CashFlow | None:
    day = moscow_date(transaction.executed_at)
    # Минус: движение денег на счёте и поток владельца противоположны по знаку.
    in_base = book.to_base(-transaction.amount, transaction.currency, day)
    if in_base is None:
        return None
    return CashFlow(on_date=day, amount=in_base, account_id=transaction.account_id,
                    transaction_id=transaction.id)


def portfolio_flows(session: Session, book: RateBook, since: date | None = None,
                    until: date | None = None) -> list[CashFlow]:
    """Внешние потоки всего капитала: переводы между своими счетами погашены."""
    moves = _cash_moves(session)
    paired = _paired_ids(moves)
    flows = []
    for move in moves:
        if move.id in paired:
            continue
        flow = _to_flow(move, book)
        if flow is not None and _in_period(flow.on_date, since, until):
            flows.append(flow)
    return flows


def account_flows(session: Session, book: RateBook, account_id: int,
                  since: date | None = None, until: date | None = None) -> list[CashFlow]:
    """Потоки одного счёта: пары НЕ гасятся. Для счёта перевод — настоящий
    приход или уход денег, и гашение занизило бы и вложения, и изъятия."""
    flows = []
    for move in _cash_moves(session):
        if move.account_id != account_id:
            continue
        flow = _to_flow(move, book)
        if flow is not None and _in_period(flow.on_date, since, until):
            flows.append(flow)
    return flows


def unconverted_flows(session: Session, book: RateBook) -> list[str]:
    """Валюты потоков, которым не нашлось курса на их дату.

    Такой поток в расчёт не входит — и обязан быть назван: молча выпавшее
    пополнение завышает доходность ровно на свою величину, и по экрану этого не
    видно никак.
    """
    missing = {
        move.currency.upper()
        for move in _cash_moves(session)
        if book.rate(move.currency, moscow_date(move.executed_at)) is None
    }
    return sorted(missing)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_returns_flows.py -v`
Expected: PASS, 11 tests

- [ ] **Step 5: Commit**

```bash
git add backend/app/returns/flows.py backend/app/timeutils.py backend/tests/test_returns_flows.py
git commit -m "feat: внешние потоки портфеля и счёта с гашением переводов"
```

---

### Задача 4: потоки бумаги и строка «Прочее»

**Files:**
- Modify: `backend/app/returns/flows.py`
- Test: `backend/tests/test_returns_instrument_flows.py`

**Interfaces:**
- Consumes: `CashFlow`, `RateBook`, `moscow_date` из задач 2–3
- Produces: `instrument_flows(session, book, since=None, until=None) -> dict[int, list[CashFlow]]`;
  `unattributed_flows(session, book, since=None, until=None) -> Unattributed`;
  `Unattributed(profit, fees, taxes, other)`.

Потоки бумаги — покупки, продажи, выплаты и удержания, привязанные к ней
(`instrument_id`). Знак тот же: покупка (деньги ушли со счёта в бумагу,
`amount` отрицателен) даёт отрицательный поток, продажа и дивиденд —
положительный. Комиссия записи (`fee`) вычитается из потока той же записи:
она часть цены сделки, а не отдельное событие.

Записи **без** `instrument_id` в потоки бумаг не попадают ни к какой бумаге.
Замер 13.08.2026: их 770 на −103 тыс. ₽ (718 `FEE`, 20 `TAX`, 30 `OTHER`,
2 `DIVIDEND`). Без отдельной строки разрез по бумагам не сойдётся с портфелем
именно на эту величину.

- [ ] **Step 1: Write the failing test**

Создать `backend/tests/test_returns_instrument_flows.py`:

```python
from datetime import date
from decimal import Decimal

from app.models import Instrument, OperationType
from app.returns.flows import instrument_flows, unattributed_flows
from app.returns.rates import RateBook
from tests.test_returns_flows import add_tx


def add_instrument(session, *, isin: str = "RU000A0JQUZ6", ticker: str = "AGRO",
                   kind: str = "share", currency: str = "RUB") -> Instrument:
    instrument = Instrument(isin=isin, ticker=ticker, kind=kind, currency=currency,
                            issuer=ticker)
    session.add(instrument)
    session.flush()
    return instrument


def test_buy_is_negative_and_sell_is_positive(session, account):
    instrument = add_instrument(session)
    add_tx(session, account_id=account.id, op_type=OperationType.BUY,
           day=date(2024, 1, 10), amount="-50000", quantity="100", price="500",
           instrument_id=instrument.id)
    add_tx(session, account_id=account.id, op_type=OperationType.SELL,
           day=date(2024, 6, 10), amount="60000", quantity="-100", price="600",
           instrument_id=instrument.id)

    flows = instrument_flows(session, RateBook.load(session))
    assert [(flow.on_date, flow.amount) for flow in flows[instrument.id]] == [
        (date(2024, 1, 10), Decimal("-50000.0000")),
        (date(2024, 6, 10), Decimal("60000.0000")),
    ]


def test_dividend_and_coupon_are_positive_flows(session, account):
    instrument = add_instrument(session)
    add_tx(session, account_id=account.id, op_type=OperationType.DIVIDEND,
           day=date(2024, 7, 1), amount="3500", instrument_id=instrument.id)
    add_tx(session, account_id=account.id, op_type=OperationType.COUPON,
           day=date(2024, 8, 1), amount="1200", instrument_id=instrument.id)

    flows = instrument_flows(session, RateBook.load(session))
    assert sum(flow.amount for flow in flows[instrument.id]) == Decimal("4700.0000")


def test_fee_of_a_trade_belongs_to_that_trade(session, account):
    """Комиссия сделки — часть её цены, а не отдельное событие: она вычитается
    из потока той же записи."""
    instrument = add_instrument(session)
    add_tx(session, account_id=account.id, op_type=OperationType.BUY,
           day=date(2024, 1, 10), amount="-50000", fee="150",
           quantity="100", price="500", instrument_id=instrument.id)

    flows = instrument_flows(session, RateBook.load(session))
    assert flows[instrument.id][0].amount == Decimal("-50150.0000")


def test_flows_without_instrument_go_to_unattributed(session, account):
    """718 комиссий и 20 налогов живых данных не относятся ни к какой бумаге.
    Их место — отдельная строка, а не молчание."""
    add_tx(session, account_id=account.id, op_type=OperationType.FEE,
           day=date(2024, 2, 1), amount="-450")
    add_tx(session, account_id=account.id, op_type=OperationType.TAX,
           day=date(2024, 3, 1), amount="-12000")
    add_tx(session, account_id=account.id, op_type=OperationType.OTHER,
           day=date(2024, 4, 1), amount="800",
           payload={"operation_type": "OPERATION_TYPE_TAX_CORRECTION"})

    result = unattributed_flows(session, RateBook.load(session))
    assert result.fees == Decimal("-450.0000")
    assert result.taxes == Decimal("-12000.0000")
    assert result.other == Decimal("800.0000")
    assert result.profit == Decimal("-11650.0000")


def test_cash_moves_are_not_unattributed(session, account):
    """Пополнение счёта — не убыток и не прибыль: это капитал владельца. В
    строке «Прочее» ему делать нечего."""
    add_tx(session, account_id=account.id, op_type=OperationType.DEPOSIT,
           day=date(2024, 2, 1), amount="100000")
    result = unattributed_flows(session, RateBook.load(session))
    assert result.profit == Decimal("0.0000")


def test_currency_flows_use_rate_of_their_day(session, account):
    from app.models import FxRate

    instrument = add_instrument(session, isin="US0378331005", ticker="AAPL",
                                currency="USD")
    session.add(FxRate(currency="USD", on_date=date(2021, 5, 4),
                       rate=Decimal("74"), source="cbr"))
    session.flush()
    add_tx(session, account_id=account.id, op_type=OperationType.BUY,
           day=date(2021, 5, 4), amount="-1000", currency="USD",
           quantity="8", price="125", instrument_id=instrument.id)

    flows = instrument_flows(session, RateBook.load(session))
    assert flows[instrument.id][0].amount == Decimal("-74000.0000")


def test_period_filters_instrument_flows(session, account):
    instrument = add_instrument(session)
    add_tx(session, account_id=account.id, op_type=OperationType.BUY,
           day=date(2023, 1, 10), amount="-10000", instrument_id=instrument.id)
    add_tx(session, account_id=account.id, op_type=OperationType.BUY,
           day=date(2024, 1, 10), amount="-20000", instrument_id=instrument.id)

    flows = instrument_flows(session, RateBook.load(session), since=date(2024, 1, 1))
    assert [flow.amount for flow in flows[instrument.id]] == [Decimal("-20000.0000")]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_returns_instrument_flows.py -v`
Expected: FAIL — `ImportError: cannot import name 'instrument_flows'`

- [ ] **Step 3: Write minimal implementation**

Дописать в `backend/app/returns/flows.py`:

```python
# Типы, движущие деньги внутри периметра: они не капитал владельца, а результат
# и издержки. В потоки бумаги входят все, привязанные к ней; непривязанные
# собираются отдельной строкой (см. unattributed_flows).
RESULT_TYPES = {
    OperationType.BUY, OperationType.SELL, OperationType.DIVIDEND,
    OperationType.COUPON, OperationType.AMORTIZATION, OperationType.REDEMPTION,
    OperationType.FEE, OperationType.TAX, OperationType.VARIATION_MARGIN,
    OperationType.OTHER,
}

FEE_TYPES = {OperationType.FEE}
TAX_TYPES = {OperationType.TAX}


@dataclass(frozen=True)
class Unattributed:
    """Комиссии, налоги и возвраты, не относящиеся ни к одной бумаге.

    Живой замер 13.08.2026: 770 записей на −103 тыс. ₽. Без этой строки сумма
    разреза по бумагам не сходится с прибылью портфеля ровно на неё, и объяснить
    расхождение было бы нечем.
    """

    profit: Decimal
    fees: Decimal
    taxes: Decimal
    other: Decimal


def _result_rows(session: Session) -> list[Transaction]:
    return list(session.execute(
        select(Transaction)
        .where(Transaction.op_type.in_(RESULT_TYPES))
        .order_by(Transaction.executed_at, Transaction.id)
    ).scalars().all())


def _trade_flow(transaction: Transaction, book: RateBook) -> CashFlow | None:
    """Поток сделки или выплаты. Комиссия записи входит в её же поток: она часть
    цены сделки, и отдельным событием её показывать не за что."""
    day = moscow_date(transaction.executed_at)
    # Знак `amount` уже такой, как у движения денег: покупка отрицательна.
    # Комиссия хранится положительной величиной и всегда уменьшает поток.
    total = transaction.amount - abs(transaction.fee)
    in_base = book.to_base(total, transaction.currency, day)
    if in_base is None:
        return None
    return CashFlow(on_date=day, amount=in_base, account_id=transaction.account_id,
                    transaction_id=transaction.id)


def instrument_flows(session: Session, book: RateBook, since: date | None = None,
                     until: date | None = None) -> dict[int, list[CashFlow]]:
    """Потоки по каждой бумаге. Ключ — instrument_id; записи без него сюда не
    попадают вовсе и учитываются строкой «Прочее»."""
    result: dict[int, list[CashFlow]] = {}
    for row in _result_rows(session):
        if row.instrument_id is None:
            continue
        if _is_cash_move(row):
            # INP_MULTI/OUT_MULTI с привязкой к бумаге — это движение денег, а
            # не результат по бумаге. Такого в живых данных нет, но правило
            # обязано быть одним и тем же для обоих периметров.
            continue
        flow = _trade_flow(row, book)
        if flow is None or not _in_period(flow.on_date, since, until):
            continue
        result.setdefault(row.instrument_id, []).append(flow)
    return result


def unattributed_flows(session: Session, book: RateBook, since: date | None = None,
                       until: date | None = None) -> Unattributed:
    """Итог по записям без бумаги, разложенный на комиссии, налоги и прочее."""
    fees = taxes = other = Decimal("0")
    for row in _result_rows(session):
        if row.instrument_id is not None or _is_cash_move(row):
            continue
        flow = _trade_flow(row, book)
        if flow is None or not _in_period(flow.on_date, since, until):
            continue
        if row.op_type in FEE_TYPES:
            fees += flow.amount
        elif row.op_type in TAX_TYPES:
            taxes += flow.amount
        else:
            other += flow.amount

    return Unattributed(profit=money(fees + taxes + other), fees=money(fees),
                        taxes=money(taxes), other=money(other))
```

В начало файла добавить импорт: `from app.money import money`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_returns_instrument_flows.py tests/test_returns_flows.py -v`
Expected: PASS, 18 tests

- [ ] **Step 5: Commit**

```bash
git add backend/app/returns/flows.py backend/tests/test_returns_instrument_flows.py
git commit -m "feat: потоки по бумагам и строка «Прочее» для непривязанных записей"
```

---
### Задача 5: TWR — цепочка дневных приростов

**Files:**
- Create: `backend/app/returns/twr.py`
- Test: `backend/tests/test_returns_twr.py`

**Interfaces:**
- Consumes: `CashFlow` из задачи 3, `app.money.money`
- Produces: `Chain(rate: Decimal | None, days: int, breaks: int)`;
  `twr(values: list[tuple[date, Decimal]], flows: list[CashFlow]) -> Chain`;
  `annualize(rate: Decimal, days: int) -> Decimal`.

`values` — ряд стоимостей периметра по дням, отсортированный по дате: для
портфеля `DailySnapshot.total_value`, для счёта — `by_account[id]`, для класса
активов — `by_asset_class[class]`. Функция чистая: в базу не ходит и о том, чей
это ряд, не знает.

- [ ] **Step 1: Write the failing test**

Создать `backend/tests/test_returns_twr.py`:

```python
from datetime import date
from decimal import Decimal

from app.returns.flows import CashFlow
from app.returns.twr import annualize, twr


def flow(day: date, amount: str) -> CashFlow:
    return CashFlow(on_date=day, amount=Decimal(amount), account_id=1, transaction_id=1)


def test_growth_without_flows_is_plain_growth():
    values = [(date(2024, 1, 1), Decimal("100")), (date(2024, 1, 2), Decimal("110"))]
    chain = twr(values, [])
    assert chain.rate == Decimal("0.1000")
    assert chain.breaks == 0


def test_deposit_does_not_count_as_return():
    """Главное, ради чего TWR вообще нужен: сто рублей стали двумястами не
    потому, что портфель вырос, а потому, что владелец занёс ещё сотню."""
    values = [(date(2024, 1, 1), Decimal("100")), (date(2024, 1, 2), Decimal("200"))]
    chain = twr(values, [flow(date(2024, 1, 2), "-100")])
    assert chain.rate == Decimal("0.0000")


def test_withdrawal_does_not_count_as_loss():
    values = [(date(2024, 1, 1), Decimal("200")), (date(2024, 1, 2), Decimal("100"))]
    chain = twr(values, [flow(date(2024, 1, 2), "100")])
    assert chain.rate == Decimal("0.0000")


def test_chain_multiplies_daily_returns():
    values = [
        (date(2024, 1, 1), Decimal("100")),
        (date(2024, 1, 2), Decimal("110")),
        (date(2024, 1, 3), Decimal("121")),
    ]
    chain = twr(values, [])
    assert chain.rate == Decimal("0.2100")


def test_zero_base_breaks_the_chain_and_is_counted():
    """Портфель обнулился и был заведён заново: делить на ноль нельзя, а
    промолчать об этом — значит выдать неполную цепочку за полную."""
    values = [
        (date(2024, 1, 1), Decimal("0")),
        (date(2024, 1, 2), Decimal("50")),
        (date(2024, 1, 3), Decimal("55")),
    ]
    chain = twr(values, [])
    assert chain.breaks == 1
    assert chain.rate == Decimal("0.1000")


def test_single_point_has_no_chain():
    chain = twr([(date(2024, 1, 1), Decimal("100"))], [])
    assert chain.rate is None
    assert chain.days == 0


def test_empty_series_has_no_chain():
    assert twr([], []).rate is None


def test_days_counts_calendar_span():
    values = [(date(2024, 1, 1), Decimal("100")), (date(2024, 12, 31), Decimal("120"))]
    assert twr(values, []).days == 365


def test_annualize_shrinks_a_short_period():
    """Два процента за месяц — это не двадцать четыре процента годовых, а
    двадцать семь: рост складывается сам с собой."""
    assert abs(annualize(Decimal("0.02"), 30) - Decimal("0.2724")) < Decimal("0.0001")


def test_annualize_leaves_a_year_alone():
    assert annualize(Decimal("0.15"), 365) == Decimal("0.1500")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_returns_twr.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.returns.twr'`

- [ ] **Step 3: Write minimal implementation**

Создать `backend/app/returns/twr.py`:

```python
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.returns.flows import CashFlow
from app.returns.xirr import DAYS_IN_YEAR

# Четыре знака — как у всех долей в проекте. Проценты и округление до десятых —
# дело интерфейса, здесь хранится величина.
PRECISION = Decimal("0.0001")


@dataclass(frozen=True)
class Chain:
    """Результат цепочки. `breaks` — сколько дней выпало из неё: у них не было
    базы для сравнения (нулевая или отрицательная стоимость накануне). Число
    важнее самой ставки: цепочка с разрывами отвечает на вопрос лишь частично, и
    молчать об этом нельзя."""

    rate: Decimal | None
    days: int
    breaks: int


def twr(values: list[tuple[date, Decimal]], flows: list[CashFlow]) -> Chain:
    """Доходность, очищенная от влияния пополнений и изъятий.

    За каждый день стоимость сравнивается с предыдущей, увеличенной на вложения
    этого дня. Знак потока — владельческий (вложение отрицательно), поэтому
    вложение прибавляется к базе вычитанием: `V_prev - flow.amount`.
    """
    if len(values) < 2:
        return Chain(rate=None, days=0, breaks=0)

    ordered = sorted(values)
    by_day: dict[date, Decimal] = {}
    for flow in flows:
        by_day[flow.on_date] = by_day.get(flow.on_date, Decimal("0")) + flow.amount

    product = Decimal("1")
    breaks = 0
    for (_, previous), (day, current) in zip(ordered, ordered[1:]):
        base = previous - by_day.get(day, Decimal("0"))
        if base <= 0:
            # Ни роста, ни падения измерить нельзя: сравнивать не с чем.
            # Множитель нейтральный, а факт разрыва уезжает наверх числом.
            breaks += 1
            continue
        product *= current / base

    days = (ordered[-1][0] - ordered[0][0]).days
    return Chain(rate=(product - Decimal("1")).quantize(PRECISION), days=days,
                 breaks=breaks)


def annualize(rate: Decimal, days: int) -> Decimal:
    """Пересчёт доходности за период в годовую.

    Применяется только к периодам от года: на более коротких результат врёт
    кратно (два процента за месяц превращаются в двадцать семь годовых), и
    служба показывает такую доходность как есть, с подписью «за период».
    """
    if days <= 0:
        return rate.quantize(PRECISION)
    exponent = DAYS_IN_YEAR / Decimal(days)
    return ((Decimal("1") + rate) ** exponent - Decimal("1")).quantize(PRECISION)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_returns_twr.py -v`
Expected: PASS, 10 tests

- [ ] **Step 5: Commit**

```bash
git add backend/app/returns/twr.py backend/tests/test_returns_twr.py
git commit -m "feat: TWR цепочкой дневных приростов с подсчётом разрывов"
```

---

### Задача 6: разложение прибыли на ценовую и валютную части

**Files:**
- Create: `backend/app/returns/fx_split.py`
- Test: `backend/tests/test_returns_fx_split.py`

**Interfaces:**
- Consumes: `RateBook` из задачи 2, `app.positions.engine.OpenLot`,
  `app.marketdata.service.LatestPrice`, `app.money.money`
- Produces: `Split(price_part: Decimal | None, fx_part: Decimal | None, total: Decimal | None, reason: str | None)`;
  `split_position(lots, price, price_currency, cost_currency, book, on_date) -> Split`;
  константы причин `REASON_NO_COST_BASIS`, `REASON_NO_PRICE`, `REASON_NO_RATE`,
  `REASON_CURRENCY_MISMATCH`.

Формула по каждой открытой партии: ценовая часть `q·(P₁−P₀)·R₀`, валютная
`q·P₁·(R₁−R₀)`. Сумма равна `q·(P₁·R₁ − P₀·R₀)` тождественно — это и проверяет
тест. Перекрёстный член целиком в валютной части: решение дизайна, раздел 4.4.

- [ ] **Step 1: Write the failing test**

Создать `backend/tests/test_returns_fx_split.py`:

```python
from datetime import date, datetime, timezone
from decimal import Decimal

from app.marketdata.service import LatestPrice
from app.positions.engine import OpenLot
from app.returns.fx_split import (
    REASON_CURRENCY_MISMATCH,
    REASON_NO_COST_BASIS,
    REASON_NO_PRICE,
    REASON_NO_RATE,
    split_position,
)
from app.returns.rates import RateBook


def lot(price: str, quantity: str, opened: date, cost_known: bool = True) -> OpenLot:
    return OpenLot(instrument_id=1,
                   opened_at=datetime.combine(opened, datetime.min.time(), tzinfo=timezone.utc),
                   price=Decimal(price), quantity_left=Decimal(quantity),
                   cost_known=cost_known)


def price_at(close: str, currency: str = "RUB") -> LatestPrice:
    return LatestPrice(close=Decimal(close), on_date=date(2026, 8, 13),
                       currency=currency, source="moex")


def book_with(rates: dict[tuple[str, date], str]) -> RateBook:
    series: dict[str, tuple[list, list]] = {}
    for (currency, on_date), value in sorted(rates.items(), key=lambda item: item[0][1]):
        dates, values = series.setdefault(currency, ([], []))
        dates.append(on_date)
        values.append(Decimal(value))
    return RateBook(series)


def test_rouble_position_has_no_currency_part():
    split = split_position(lots=[lot("100", "10", date(2024, 1, 10))],
                           price=price_at("150"), price_currency="RUB",
                           cost_currency="RUB", book=book_with({}),
                           on_date=date(2026, 8, 13))
    assert split.price_part == Decimal("500.0000")
    assert split.fx_part == Decimal("0.0000")
    assert split.total == Decimal("500.0000")


def test_currency_position_splits_into_two_parts():
    """Десять акций по 100 $ куплены при курсе 70, стоят 120 $ при курсе 80.
    Ценовая часть: 10·(120−100)·70 = 14 000 ₽. Валютная: 10·120·(80−70) =
    12 000 ₽. Вместе 26 000 ₽ — ровно 10·(120·80 − 100·70)."""
    book = book_with({("USD", date(2024, 1, 10)): "70", ("USD", date(2026, 8, 13)): "80"})
    split = split_position(lots=[lot("100", "10", date(2024, 1, 10))],
                           price=price_at("120", "USD"), price_currency="USD",
                           cost_currency="USD", book=book, on_date=date(2026, 8, 13))
    assert split.price_part == Decimal("14000.0000")
    assert split.fx_part == Decimal("12000.0000")
    assert split.total == Decimal("26000.0000")


def test_parts_always_sum_to_total():
    """Признак готовности фазы, пункт 2. Партии с разными датами и курсами —
    самый вероятный случай разъезда."""
    book = book_with({
        ("USD", date(2021, 3, 1)): "74.2",
        ("USD", date(2023, 9, 15)): "96.5",
        ("USD", date(2026, 8, 13)): "81.3",
    })
    split = split_position(
        lots=[lot("125.5", "8", date(2021, 3, 1)), lot("210.75", "3", date(2023, 9, 15))],
        price=price_at("187.4", "USD"), price_currency="USD", cost_currency="USD",
        book=book, on_date=date(2026, 8, 13))
    assert split.price_part + split.fx_part == split.total


def test_short_position_keeps_its_sign():
    """У короткой позиции количество отрицательное: рост цены — убыток."""
    split = split_position(lots=[lot("100", "-10", date(2024, 1, 10))],
                           price=price_at("150"), price_currency="RUB",
                           cost_currency="RUB", book=book_with({}),
                           on_date=date(2026, 8, 13))
    assert split.total == Decimal("-500.0000")


def test_lot_without_cost_basis_blocks_the_split():
    """351 бумага РусАгро введена переводом: себестоимости нет, и прибыль по
    позиции неизвестна. Ноль тут был бы враньём."""
    split = split_position(lots=[lot("0", "351", date(2024, 12, 19), cost_known=False)],
                           price=price_at("150"), price_currency="RUB",
                           cost_currency="RUB", book=book_with({}),
                           on_date=date(2026, 8, 13))
    assert split.total is None
    assert split.reason == REASON_NO_COST_BASIS


def test_missing_price_is_named():
    split = split_position(lots=[lot("100", "10", date(2024, 1, 10))],
                           price=None, price_currency="RUB", cost_currency="RUB",
                           book=book_with({}), on_date=date(2026, 8, 13))
    assert split.total is None
    assert split.reason == REASON_NO_PRICE


def test_missing_rate_is_named():
    split = split_position(lots=[lot("100", "10", date(2024, 1, 10))],
                           price=price_at("120", "USD"), price_currency="USD",
                           cost_currency="USD", book=book_with({}),
                           on_date=date(2026, 8, 13))
    assert split.total is None
    assert split.reason == REASON_NO_RATE


def test_currency_mismatch_is_named():
    """Замещающая облигация: расчёты рублёвые, котировка юаневая. Вычитать одно
    из другого — получить курс, а не доходность (живой RU000A10CRC4 давал так
    −98,8 %)."""
    book = book_with({("CNY", date(2024, 1, 10)): "12.5",
                      ("CNY", date(2026, 8, 13)): "11.2"})
    split = split_position(lots=[lot("8138.62", "10", date(2024, 1, 10))],
                           price=price_at("96.5", "CNY"), price_currency="CNY",
                           cost_currency="RUB", book=book, on_date=date(2026, 8, 13))
    assert split.total is None
    assert split.reason == REASON_CURRENCY_MISMATCH
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_returns_fx_split.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.returns.fx_split'`

- [ ] **Step 3: Write minimal implementation**

Создать `backend/app/returns/fx_split.py`:

```python
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.marketdata.service import LatestPrice
from app.money import money
from app.positions.engine import OpenLot
from app.returns.rates import RateBook
from app.timeutils import moscow_date

# Причины, по которым прибыль неизвестна. Каждая называется на экране словами:
# пустая ячейка без объяснения — это вопрос, на который система не отвечает.
REASON_NO_COST_BASIS = "no_cost_basis"
REASON_NO_PRICE = "no_price"
REASON_NO_RATE = "no_rate"
REASON_CURRENCY_MISMATCH = "currency_mismatch"


@dataclass(frozen=True)
class Split:
    """Прибыль открытой позиции и её разложение.

    `price_part` — что дала сама бумага, по курсу на дату покупки.
    `fx_part` — что дало движение рубля. Их сумма тождественно равна `total`:
    перекрёстный член отнесён к валютной части целиком (дизайн, раздел 4.4).
    """

    price_part: Decimal | None
    fx_part: Decimal | None
    total: Decimal | None
    reason: str | None


def _unknown(reason: str) -> Split:
    return Split(price_part=None, fx_part=None, total=None, reason=reason)


def split_position(lots: list[OpenLot], price: LatestPrice | None, price_currency: str,
                   cost_currency: str, book: RateBook, on_date: date) -> Split:
    """Разложение прибыли позиции по её открытым партиям.

    Партии считаются по отдельности и складываются: у позиции, набранной за три
    года, единой даты покупки не существует, а курс на дату покупки — половина
    ответа.
    """
    if price is None:
        return _unknown(REASON_NO_PRICE)
    if any(not lot.cost_known for lot in lots):
        return _unknown(REASON_NO_COST_BASIS)
    if price_currency.upper() != cost_currency.upper():
        # Средняя цена в одной валюте, котировка в другой: вычитание даст курс,
        # а не доходность. Пересчёт тут возможен, но требует курса на дату
        # каждой операции ПО НОМИНАЛУ бумаги — это уже другой расчёт.
        return _unknown(REASON_CURRENCY_MISMATCH)

    rate_now = book.rate(price_currency, on_date)
    if rate_now is None:
        return _unknown(REASON_NO_RATE)

    price_part = Decimal("0")
    fx_part = Decimal("0")
    for lot in lots:
        opened = moscow_date(lot.opened_at)
        rate_then = book.rate(cost_currency, opened)
        if rate_then is None:
            return _unknown(REASON_NO_RATE)

        quantity = lot.quantity_left
        price_part += quantity * (price.close - lot.price) * rate_then
        fx_part += quantity * price.close * (rate_now - rate_then)

    return Split(price_part=money(price_part), fx_part=money(fx_part),
                 total=money(price_part + fx_part), reason=None)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_returns_fx_split.py -v`
Expected: PASS, 8 tests

- [ ] **Step 5: Commit**

```bash
git add backend/app/returns/fx_split.py backend/tests/test_returns_fx_split.py
git commit -m "feat: разложение прибыли позиции на ценовую и валютную части"
```

---
### Задача 7: сборка отчёта — периоды, портфель, покрытие

**Files:**
- Create: `backend/app/returns/service.py`
- Test: `backend/tests/test_returns_service.py`

**Interfaces:**
- Consumes: всё из задач 1–6, `app.analytics.service.portfolio_overview`,
  `app.models.DailySnapshot`, `app.timeutils.moscow_today`
- Produces: `PERIODS`, `Period(key, since, until, annualized)`;
  `Metric(xirr, twr, profit, invested, value, reason)`;
  `Coverage(...)`; `ReturnsReport(period, portfolio, coverage, by_account, by_asset_class, by_instrument, unattributed)`;
  `returns_report(session, period_key: str) -> ReturnsReport`;
  `period_bounds(period_key: str, today: date, first_day: date | None) -> Period`.

Три решения этой задачи, каждое названо в коде:

1. **Конечная стоимость берётся из `portfolio_overview`, а не из последнего
   снимка.** Иначе экран «Аналитика» и экран «Портфель» показывали бы разный
   капитал в один и тот же момент — снимок снимается раз в сутки.
2. **Ряд для TWR берётся из снимков** — другого дневного ряда не существует.
3. **У класса «деньги» доходность не считается.** Дизайн предполагал видеть
   покупку бумаги как поток между классами; на практике это дало бы «доходность
   денег», которой не существует: остаток не растёт сам, а проценты на него
   приходят записями без бумаги и уже посчитаны строкой «Прочее». Стоимость
   класса показывается, доходность — с причиной `cash`.

- [ ] **Step 1: Write the failing test**

Создать `backend/tests/test_returns_service.py`:

```python
from datetime import date
from decimal import Decimal

from app.models import DailySnapshot, FxRate, OperationType
from app.returns.service import PERIOD_12M, PERIOD_ALL, PERIOD_YTD, period_bounds, returns_report
from tests.test_returns_flows import add_tx
from tests.test_returns_instrument_flows import add_instrument


def add_snapshot(session, day: date, total: str, by_account: dict | None = None,
                 valued: int = 1, total_positions: int = 1) -> None:
    session.add(DailySnapshot(
        on_date=day, total_value=Decimal(total), by_asset_class={"equity": total},
        by_account=by_account or {}, source="backfill",
        positions_total=total_positions, valued_positions=valued, unpriced=[]))
    session.flush()


def test_all_period_starts_at_first_day():
    period = period_bounds(PERIOD_ALL, date(2026, 8, 13), date(2020, 7, 16))
    assert period.since == date(2020, 7, 16)
    assert period.until == date(2026, 8, 13)
    assert period.annualized is True


def test_twelve_months_is_a_year_back():
    period = period_bounds(PERIOD_12M, date(2026, 8, 13), date(2020, 7, 16))
    assert period.since == date(2025, 8, 13)
    assert period.annualized is True


def test_ytd_in_february_is_not_annualized():
    """Полтора месяца в годовых врут кратно: два процента за это время
    показались бы как двадцать семь годовых."""
    period = period_bounds(PERIOD_YTD, date(2026, 2, 14), date(2020, 7, 16))
    assert period.since == date(2026, 1, 1)
    assert period.annualized is False


def test_profit_is_growth_minus_contributions(session, account):
    """Занёс 100 000, портфель стоит 130 000 — заработано 30 000. Ни рублём
    больше: остальное принёс не рынок, а владелец."""
    instrument = add_instrument(session)
    add_tx(session, account_id=account.id, op_type=OperationType.DEPOSIT,
           day=date(2024, 1, 10), amount="100000")
    add_tx(session, account_id=account.id, op_type=OperationType.BUY,
           day=date(2024, 1, 11), amount="-100000", quantity="100", price="1000",
           instrument_id=instrument.id)
    add_snapshot(session, date(2024, 1, 10), "100000")
    add_snapshot(session, date(2026, 8, 13), "130000")

    report = returns_report(session, PERIOD_ALL, today=date(2026, 8, 13),
                            value_now=Decimal("130000"), by_account_now={account.id: Decimal("130000")},
                            by_class_now={"equity": Decimal("130000")})
    assert report.portfolio.profit == Decimal("30000.0000")
    assert report.portfolio.invested == Decimal("100000.0000")


def test_xirr_is_positive_when_portfolio_grew(session, account):
    add_tx(session, account_id=account.id, op_type=OperationType.DEPOSIT,
           day=date(2024, 8, 13), amount="100000")
    add_snapshot(session, date(2024, 8, 13), "100000")
    add_snapshot(session, date(2026, 8, 13), "130000")

    report = returns_report(session, PERIOD_ALL, today=date(2026, 8, 13),
                            value_now=Decimal("130000"), by_account_now={account.id: Decimal("130000")},
                            by_class_now={"equity": Decimal("130000")})
    assert report.portfolio.xirr is not None
    assert report.portfolio.xirr > Decimal("0.13")
    assert report.portfolio.xirr < Decimal("0.15")


def test_portfolio_without_flows_has_named_reason(session, account):
    """Капитал есть, а внешних потоков в периоде нет: ставки не существует, и
    экран обязан сказать почему, а не показать прочерк."""
    add_snapshot(session, date(2026, 8, 12), "130000")
    add_snapshot(session, date(2026, 8, 13), "130000")

    report = returns_report(session, PERIOD_ALL, today=date(2026, 8, 13),
                            value_now=Decimal("130000"), by_account_now={},
                            by_class_now={})
    assert report.portfolio.xirr is None
    assert report.portfolio.reason == "no_flows"


def test_closed_instrument_is_listed_with_a_mark(session, account):
    """Проданная целиком бумага остаётся в разрезе: без неё сумма по бумагам не
    сойдётся с портфелем."""
    instrument = add_instrument(session)
    add_tx(session, account_id=account.id, op_type=OperationType.BUY,
           day=date(2024, 1, 11), amount="-100000", quantity="100", price="1000",
           instrument_id=instrument.id)
    add_tx(session, account_id=account.id, op_type=OperationType.SELL,
           day=date(2024, 6, 11), amount="120000", quantity="-100", price="1200",
           instrument_id=instrument.id)
    add_snapshot(session, date(2024, 1, 11), "100000")
    add_snapshot(session, date(2026, 8, 13), "120000")

    report = returns_report(session, PERIOD_ALL, today=date(2026, 8, 13),
                            value_now=Decimal("120000"), by_account_now={},
                            by_class_now={})
    row = next(row for row in report.by_instrument if row.instrument_id == instrument.id)
    assert row.closed is True
    assert row.profit == Decimal("20000.0000")
    assert row.value == Decimal("0.0000")


def test_unattributed_row_is_part_of_the_report(session, account):
    add_tx(session, account_id=account.id, op_type=OperationType.FEE,
           day=date(2024, 2, 1), amount="-450")
    add_snapshot(session, date(2024, 2, 1), "100000")
    add_snapshot(session, date(2026, 8, 13), "100000")

    report = returns_report(session, PERIOD_ALL, today=date(2026, 8, 13),
                            value_now=Decimal("100000"), by_account_now={},
                            by_class_now={})
    assert report.unattributed.fees == Decimal("-450.0000")


def test_coverage_reports_unvalued_days_and_currencies(session, account):
    add_tx(session, account_id=account.id, op_type=OperationType.DEPOSIT,
           day=date(2024, 2, 1), amount="1000", currency="HKD")
    add_snapshot(session, date(2024, 2, 1), "100000", valued=1, total_positions=2)
    add_snapshot(session, date(2026, 8, 13), "100000", valued=2, total_positions=2)

    report = returns_report(session, PERIOD_ALL, today=date(2026, 8, 13),
                            value_now=Decimal("100000"), by_account_now={},
                            by_class_now={})
    assert report.coverage.days_total == 2
    assert report.coverage.days_valued == 1
    assert report.coverage.currencies_without_rate == ["HKD"]


def test_period_cuts_off_earlier_flows(session, account):
    session.add(FxRate(currency="USD", on_date=date(2020, 1, 1),
                       rate=Decimal("70"), source="cbr"))
    add_tx(session, account_id=account.id, op_type=OperationType.DEPOSIT,
           day=date(2021, 1, 10), amount="500000")
    add_tx(session, account_id=account.id, op_type=OperationType.DEPOSIT,
           day=date(2026, 3, 10), amount="100000")
    add_snapshot(session, date(2021, 1, 10), "500000")
    add_snapshot(session, date(2025, 8, 13), "900000")
    add_snapshot(session, date(2026, 8, 13), "1100000")

    report = returns_report(session, PERIOD_12M, today=date(2026, 8, 13),
                            value_now=Decimal("1100000"), by_account_now={},
                            by_class_now={})
    assert report.period.since == date(2025, 8, 13)
    assert report.portfolio.invested == Decimal("100000.0000")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_returns_service.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.returns.service'`

- [ ] **Step 3: Write minimal implementation**

Создать `backend/app/returns/service.py`:

```python
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics.service import asset_class_of, portfolio_overview
from app.marketdata.service import prices_as_of
from app.models import Account, DailySnapshot, Instrument
from app.money import money
from app.positions.engine import OpenLot, fold
from app.positions.service import ledger_entries
from app.returns.flows import (
    CashFlow,
    Unattributed,
    account_flows,
    instrument_flows,
    portfolio_flows,
    unattributed_flows,
    unconverted_flows,
)
from app.returns.fx_split import split_position
from app.returns.rates import RateBook
from app.returns.twr import Chain, annualize, twr
from app.returns.xirr import Flow, xirr
from app.timeutils import moscow_today

PERIOD_ALL = "all"
PERIOD_12M = "12m"
PERIOD_YTD = "ytd"
PERIODS = (PERIOD_ALL, PERIOD_12M, PERIOD_YTD)

# Порог аннуализации. Ставка по устройству годовая, и на периоде короче года она
# врёт кратно: два процента за полтора месяца превращаются в двадцать семь
# годовых. Короткий период показывается как есть, с подписью «за период».
DAYS_IN_YEAR = 365

# Причины отсутствия числа. Каждая переводится в слова на экране.
REASON_NO_FLOWS = "no_flows"
REASON_NO_HISTORY = "no_history"
REASON_CASH = "cash"


@dataclass(frozen=True)
class Period:
    key: str
    since: date | None
    until: date
    annualized: bool


@dataclass(frozen=True)
class Metric:
    xirr: Decimal | None
    twr: Decimal | None
    profit: Decimal
    invested: Decimal
    value: Decimal
    reason: str | None = None


@dataclass(frozen=True)
class AccountRow:
    account_id: int
    metric: Metric


@dataclass(frozen=True)
class AssetClassRow:
    asset_class: str
    metric: Metric


@dataclass(frozen=True)
class InstrumentRow:
    instrument_id: int
    ticker: str | None
    name: str
    xirr: Decimal | None
    profit: Decimal
    value: Decimal
    closed: bool
    price_part: Decimal | None
    fx_part: Decimal | None
    reason: str | None


@dataclass(frozen=True)
class Coverage:
    days_total: int
    days_valued: int
    positions_total: int
    positions_valued: int
    unpriced: list[str]
    chain_breaks: int
    currencies_without_rate: list[str]


@dataclass(frozen=True)
class ReturnsReport:
    period: Period
    portfolio: Metric
    coverage: Coverage
    by_account: list[AccountRow] = field(default_factory=list)
    by_asset_class: list[AssetClassRow] = field(default_factory=list)
    by_instrument: list[InstrumentRow] = field(default_factory=list)
    unattributed: Unattributed = Unattributed(Decimal("0"), Decimal("0"),
                                              Decimal("0"), Decimal("0"))


def period_bounds(period_key: str, today: date, first_day: date | None) -> Period:
    if period_key == PERIOD_12M:
        since = today - timedelta(days=DAYS_IN_YEAR)
    elif period_key == PERIOD_YTD:
        since = date(today.year, 1, 1)
    else:
        since = first_day

    # Период короче года аннуализировать нельзя — см. комментарий у DAYS_IN_YEAR.
    length = (today - since).days if since is not None else 0
    return Period(key=period_key, since=since, until=today, annualized=length >= DAYS_IN_YEAR)


def _snapshots(session: Session, since: date | None, until: date) -> list[DailySnapshot]:
    query = select(DailySnapshot).where(DailySnapshot.on_date <= until)
    if since is not None:
        query = query.where(DailySnapshot.on_date >= since)
    return list(session.execute(query.order_by(DailySnapshot.on_date)).scalars().all())


def _first_snapshot_day(session: Session) -> date | None:
    return session.execute(
        select(DailySnapshot.on_date).order_by(DailySnapshot.on_date).limit(1)
    ).scalar_one_or_none()


def _metric(flows: list[CashFlow], value_start: Decimal, value_now: Decimal,
            series: list[tuple[date, Decimal]], period: Period) -> tuple[Metric, Chain]:
    """Доходность одного периметра. Начальная стоимость входит вложением, а
    конечная — изъятием: за период владелец «вложил» то, что у него уже было, и
    «получил» то, что стало."""
    profit = money(value_now - value_start + sum((flow.amount for flow in flows), Decimal("0")))
    invested = money(-sum((flow.amount for flow in flows if flow.amount < 0), Decimal("0")))

    rate_flows = [Flow(on_date=flow.on_date, amount=flow.amount) for flow in flows]
    if value_start != 0 and period.since is not None:
        rate_flows.append(Flow(on_date=period.since, amount=-value_start))
    if value_now != 0:
        rate_flows.append(Flow(on_date=period.until, amount=value_now))

    rate = xirr(rate_flows)
    chain = twr(series, flows)

    if rate is not None and period.annualized is False:
        # За период, а не в годовых: пересчёта тут нет — xirr уже вернул годовую
        # ставку, и для короткого периода она не показывается вовсе.
        rate = None

    twr_rate = chain.rate
    if twr_rate is not None and period.annualized:
        twr_rate = annualize(twr_rate, chain.days)

    reason = None
    if rate is None and twr_rate is None:
        reason = REASON_NO_FLOWS if not flows else REASON_NO_HISTORY

    return Metric(xirr=rate, twr=twr_rate, profit=profit, invested=invested,
                  value=money(value_now), reason=reason), chain


def _series(snapshots: list[DailySnapshot], pick) -> list[tuple[date, Decimal]]:
    result = []
    for snapshot in snapshots:
        value = pick(snapshot)
        if value is not None:
            result.append((snapshot.on_date, Decimal(str(value))))
    return result


def _value_at(series: list[tuple[date, Decimal]], since: date | None) -> Decimal:
    """Стоимость периметра на начало периода. Ноль — периметра тогда не
    существовало, и это законное начало отсчёта, а не пропуск данных."""
    if since is None or not series:
        return Decimal("0")
    earlier = [value for day, value in series if day <= since]
    return earlier[-1] if earlier else Decimal("0")


def _lots_by_instrument(session: Session) -> dict[int, list[OpenLot]]:
    """Открытые партии по всем счетам, сведённые по бумаге.

    Партии считает движок позиций — тот же, что строит саму позицию. Второй
    свёртки журнала в проекте быть не должно: разъедется трактовка решений
    владельца.
    """
    result: dict[int, list[OpenLot]] = {}
    for account in session.execute(select(Account)).scalars():
        folded = fold(ledger_entries(session, account), currency=account.currency)
        for instrument_id, state in folded.positions.items():
            if state.quantity == 0:
                continue
            result.setdefault(instrument_id, []).extend(state.lots)
    return result


def returns_report(session: Session, period_key: str, today: date | None = None,
                   value_now: Decimal | None = None,
                   by_account_now: dict[int, Decimal] | None = None,
                   by_class_now: dict[str, Decimal] | None = None) -> ReturnsReport:
    """Отчёт о доходности за период.

    Сегодняшние стоимости приходят параметрами, а не считаются здесь: их уже
    посчитал `portfolio_overview`, и второй расчёт того же числа рядом с первым
    рано или поздно разойдётся с ним. Значения по умолчанию берутся из него же —
    параметры существуют ради тестов и ради вызова из обработчика одним куском.
    """
    today = today or moscow_today()
    if value_now is None or by_account_now is None or by_class_now is None:
        overview = portfolio_overview(session)
        value_now = overview.total_value
        by_account_now = overview.by_account
        by_class_now = overview.by_asset_class

    period = period_bounds(period_key, today, _first_snapshot_day(session))
    book = RateBook.load(session)
    snapshots = _snapshots(session, period.since, period.until)

    total_series = _series(snapshots, lambda row: row.total_value)
    flows = portfolio_flows(session, book, period.since, period.until)
    portfolio, chain = _metric(flows, _value_at(total_series, period.since),
                               value_now, total_series, period)

    accounts = list(session.execute(select(Account)).scalars())
    by_account = []
    for account in accounts:
        series = _series(snapshots, lambda row, key=str(account.id): (
            row.by_account or {}).get(key))
        metric, _ = _metric(account_flows(session, book, account.id, period.since, period.until),
                            _value_at(series, period.since),
                            by_account_now.get(account.id, Decimal("0")), series, period)
        by_account.append(AccountRow(account_id=account.id, metric=metric))

    instrument_rows, by_class = _instrument_and_class_rows(
        session, book, period, snapshots, by_class_now)

    valued = sum(1 for row in snapshots if row.valued_positions == row.positions_total)
    last = snapshots[-1] if snapshots else None
    coverage = Coverage(
        days_total=len(snapshots),
        days_valued=valued,
        positions_total=last.positions_total if last else 0,
        positions_valued=last.valued_positions if last else 0,
        unpriced=list(last.unpriced or []) if last else [],
        chain_breaks=chain.breaks,
        currencies_without_rate=unconverted_flows(session, book),
    )

    return ReturnsReport(
        period=period, portfolio=portfolio, coverage=coverage,
        by_account=by_account, by_asset_class=by_class, by_instrument=instrument_rows,
        unattributed=unattributed_flows(session, book, period.since, period.until),
    )
```

Дописать в тот же файл разбор по бумагам и классам:

```python
def _instrument_and_class_rows(session: Session, book: RateBook, period: Period,
                               snapshots: list[DailySnapshot],
                               by_class_now: dict[str, Decimal]):
    """Строки по бумагам и по классам активов за один проход.

    Класс бумаги берётся сегодняшний: истории смены класса система не хранит, и
    выдумывать её здесь нельзя. Упрощение названо на экране.
    """
    flows_by_instrument = instrument_flows(session, book, period.since, period.until)
    lots = _lots_by_instrument(session)
    prices = prices_as_of(session, period.until)

    instruments = {
        row.id: row
        for row in session.execute(
            select(Instrument).where(Instrument.id.in_(
                set(flows_by_instrument) | set(lots)))
        ).scalars()
    }

    rows: list[InstrumentRow] = []
    class_flows: dict[str, list[CashFlow]] = {}

    for instrument_id, instrument in instruments.items():
        flows = flows_by_instrument.get(instrument_id, [])
        open_lots = lots.get(instrument_id, [])
        price = prices.get(instrument_id)

        value = Decimal("0")
        if open_lots and price is not None:
            quantity = sum((lot.quantity_left for lot in open_lots), Decimal("0"))
            in_base = book.to_base(quantity * price.close, price.currency, period.until)
            value = in_base if in_base is not None else Decimal("0")

        split = split_position(
            lots=open_lots, price=price,
            price_currency=(price.currency if price else instrument.currency),
            cost_currency=instrument.currency, book=book, on_date=period.until,
        ) if open_lots else None

        rate_flows = [Flow(on_date=flow.on_date, amount=flow.amount) for flow in flows]
        if value != 0:
            rate_flows.append(Flow(on_date=period.until, amount=value))
        rate = xirr(rate_flows) if period.annualized else None

        profit = money(value + sum((flow.amount for flow in flows), Decimal("0")))
        rows.append(InstrumentRow(
            instrument_id=instrument_id,
            ticker=instrument.ticker,
            name=instrument.issuer or instrument.ticker or instrument.isin or "—",
            xirr=rate,
            profit=profit,
            value=money(value),
            closed=not open_lots,
            price_part=split.price_part if split else None,
            fx_part=split.fx_part if split else None,
            reason=(split.reason if split else None),
        ))

        klass = asset_class_of(instrument)
        class_flows.setdefault(klass, []).extend(flows)

    by_class = []
    for klass, value_now in sorted(by_class_now.items()):
        if klass == "cash":
            # Доходности у денежного остатка нет: он не растёт сам, а проценты
            # на него приходят записями без бумаги и уже посчитаны строкой
            # «Прочее». Показать тут ноль значило бы утверждать, что деньги
            # ничего не принесли, — а они не могли.
            by_class.append(AssetClassRow(asset_class=klass, metric=Metric(
                xirr=None, twr=None, profit=Decimal("0"), invested=Decimal("0"),
                value=money(value_now), reason=REASON_CASH)))
            continue

        series = _series(snapshots, lambda row, key=klass: (row.by_asset_class or {}).get(key))
        metric, _ = _metric(class_flows.get(klass, []), _value_at(series, period.since),
                            value_now, series, period)
        by_class.append(AssetClassRow(asset_class=klass, metric=metric))

    return rows, by_class
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_returns_service.py -v`
Expected: PASS, 10 tests

Если тест `test_profit_is_growth_minus_contributions` падает на копейку —
проверить, что `money()` применён к результату один раз, а не к слагаемым.

- [ ] **Step 5: Прогнать весь бэкенд**

Run: `cd backend && uv run pytest`
Expected: PASS, 546 прежних тестов + 47 новых

- [ ] **Step 6: Commit**

```bash
git add backend/app/returns/service.py backend/tests/test_returns_service.py
git commit -m "feat: отчёт о доходности — периоды, разрезы, покрытие"
```

---

### Задача 8: обработчик API

**Files:**
- Create: `backend/app/api/routes_analytics.py`
- Modify: `backend/app/api/schemas.py` (дописать схемы в конец)
- Modify: `backend/app/main.py` (подключить роутер)
- Test: `backend/tests/test_returns_api.py`

**Interfaces:**
- Consumes: `returns_report`, `PERIODS` из задачи 7, `app.accounts.labels.account_label`
- Produces: `GET /api/analytics/returns?period=all|12m|ytd` → `ReturnsOut`

- [ ] **Step 1: Write the failing test**

Создать `backend/tests/test_returns_api.py`:

```python
from datetime import date
from decimal import Decimal

from app.models import OperationType
from tests.test_returns_flows import add_tx
from tests.test_returns_service import add_snapshot


def test_returns_endpoint_answers(client, session, account):
    add_tx(session, account_id=account.id, op_type=OperationType.DEPOSIT,
           day=date(2024, 8, 13), amount="100000")
    add_snapshot(session, date(2024, 8, 13), "100000")
    add_snapshot(session, date(2026, 8, 13), "130000")
    session.commit()

    response = client.get("/api/analytics/returns?period=all")
    assert response.status_code == 200
    body = response.json()
    assert body["period"]["from"] == "2024-08-13"
    # Деньги — строки, как везде: точность Decimal через float не проходит.
    assert isinstance(body["portfolio"]["profit"], str)
    assert body["unattributed"]["profit"] == "0.0000"


def test_unknown_period_is_rejected(client):
    response = client.get("/api/analytics/returns?period=forever")
    assert response.status_code == 422


def test_accounts_are_labelled_not_numbered(client, session, account):
    add_snapshot(session, date(2026, 8, 13), "100000")
    session.commit()

    body = client.get("/api/analytics/returns?period=all").json()
    assert body["by_account"][0]["title"] == "Инвестиционный"
```

Фикстура `client` уже существует — посмотреть, как её берут соседние тесты
(`backend/tests/test_api.py`), и использовать ту же.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_returns_api.py -v`
Expected: FAIL — 404, обработчика нет

- [ ] **Step 3: Write minimal implementation**

Дописать в конец `backend/app/api/schemas.py`:

```python
class PeriodOut(BaseModel):
    # Границы периода явные: «за всё время» у портфеля владельца начинается
    # 16.07.2020, и владелец вправе видеть, с какой даты посчитана цифра.
    from_date: date = Field(serialization_alias="from")
    to_date: date = Field(serialization_alias="to")
    # Ложь — доходность показана за период, а не в годовых (период короче года).
    annualized: bool


class MetricOut(BaseModel):
    # None у ставок — законное значение: причина названа в reason.
    xirr: Decimal | None
    twr: Decimal | None
    profit: Decimal
    invested: Decimal
    value: Decimal
    reason: str | None

    @field_serializer("xirr", "twr")
    def serialize_rate(self, value: Decimal | None) -> str | None:
        # Доля, а не проценты: перевод и округление — дело интерфейса.
        return None if value is None else f"{value:.4f}"

    @field_serializer("profit", "invested", "value")
    def serialize_money(self, value: Decimal) -> str:
        return f"{value:.4f}"


class AccountReturnOut(MetricOut):
    title: str


class AssetClassReturnOut(MetricOut):
    asset_class: str


class InstrumentReturnOut(BaseModel):
    ticker: str | None
    name: str
    xirr: Decimal | None
    profit: Decimal
    value: Decimal
    # Позиция продана целиком: конечная стоимость ноль, история — нет.
    closed: bool
    # Разложение прибыли открытой позиции. None у рублёвой бумаги в fx_part
    # не бывает — там ноль; None означает «посчитать нечем», и почему, говорит
    # reason.
    price_part: Decimal | None
    fx_part: Decimal | None
    reason: str | None

    @field_serializer("xirr")
    def serialize_rate(self, value: Decimal | None) -> str | None:
        return None if value is None else f"{value:.4f}"

    @field_serializer("profit", "value")
    def serialize_money(self, value: Decimal) -> str:
        return f"{value:.4f}"

    @field_serializer("price_part", "fx_part")
    def serialize_optional_money(self, value: Decimal | None) -> str | None:
        return None if value is None else f"{value:.4f}"


class CoverageOut(BaseModel):
    days_total: int
    days_valued: int
    positions_total: int
    positions_valued: int
    unpriced: list[str]
    # Сколько дней выпало из цепочки TWR: у них не было базы для сравнения.
    chain_breaks: int
    # Валюты потоков, которым не нашлось курса: эти потоки в расчёт не вошли.
    currencies_without_rate: list[str]


class UnattributedOut(BaseModel):
    """Комиссии, налоги и возвраты, не относящиеся ни к одной бумаге.

    Живой замер: 770 записей на −103 тыс. ₽. Без этой строки сумма разреза по
    бумагам не сходится с прибылью портфеля ровно на неё.
    """

    profit: Decimal
    fees: Decimal
    taxes: Decimal
    other: Decimal

    @field_serializer("profit", "fees", "taxes", "other")
    def serialize_money(self, value: Decimal) -> str:
        return f"{value:.4f}"


class ReturnsOut(BaseModel):
    period: PeriodOut
    portfolio: MetricOut
    coverage: CoverageOut
    by_account: list[AccountReturnOut]
    by_asset_class: list[AssetClassReturnOut]
    by_instrument: list[InstrumentReturnOut]
    unattributed: UnattributedOut
```

В начало `schemas.py` добавить `Field` в импорт pydantic:
`from pydantic import BaseModel, ConfigDict, Field, field_serializer`.

Создать `backend/app/api/routes_analytics.py`:

```python
from typing import Literal

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.accounts.labels import account_label
from app.api.schemas import (
    AccountReturnOut,
    AssetClassReturnOut,
    CoverageOut,
    InstrumentReturnOut,
    MetricOut,
    PeriodOut,
    ReturnsOut,
    UnattributedOut,
)
from app.db import get_session
from app.models import Account
from app.returns.service import PERIOD_12M, PERIOD_ALL, PERIOD_YTD, returns_report

router = APIRouter(prefix="/api", tags=["analytics"])


@router.get("/analytics/returns", response_model=ReturnsOut)
def get_returns(
    # Literal, а не str: неизвестный период — ошибка запроса, а не молчаливый
    # откат к «всё время». Владелец, увидевший цифру за не тот период, не узнает
    # об этом никогда.
    period: Literal[PERIOD_ALL, PERIOD_12M, PERIOD_YTD] = PERIOD_ALL,
    session: Session = Depends(get_session),
) -> ReturnsOut:
    report = returns_report(session, period)
    # Подпись счёта строится при чтении — той же единственной на проект
    # функцией, что и в четырёх соседних обработчиках.
    accounts = {
        account.id: account
        for account in session.execute(select(Account)).scalars()
    }

    return ReturnsOut(
        period=PeriodOut(
            from_date=report.period.since or report.period.until,
            to_date=report.period.until,
            annualized=report.period.annualized,
        ),
        portfolio=MetricOut(**report.portfolio.__dict__),
        coverage=CoverageOut(**report.coverage.__dict__),
        by_account=[
            AccountReturnOut(title=account_label(accounts[row.account_id]),
                             **row.metric.__dict__)
            for row in report.by_account
            if row.account_id in accounts
        ],
        by_asset_class=[
            AssetClassReturnOut(asset_class=row.asset_class, **row.metric.__dict__)
            for row in report.by_asset_class
        ],
        by_instrument=[
            InstrumentReturnOut(
                ticker=row.ticker, name=row.name, xirr=row.xirr, profit=row.profit,
                value=row.value, closed=row.closed, price_part=row.price_part,
                fx_part=row.fx_part, reason=row.reason,
            )
            for row in report.by_instrument
        ],
        unattributed=UnattributedOut(**report.unattributed.__dict__),
    )
```

В `backend/app/main.py` добавить импорт и подключение рядом с существующими
роутерами: `from app.api import routes_analytics` и
`app.include_router(routes_analytics.router)`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_returns_api.py -v`
Expected: PASS, 3 tests

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes_analytics.py backend/app/api/schemas.py backend/app/main.py backend/tests/test_returns_api.py
git commit -m "feat: обработчик доходности GET /api/analytics/returns"
```

---
### Задача 9: прогон на живых данных

**Files:**
- Create: `backend/app/returns/check.py`
- Modify: `README.md` (раздел про повторяемые прогоны)
- Test: `backend/tests/test_returns_check.py`

**Interfaces:**
- Consumes: `returns_report` из задачи 7
- Produces: `check_returns(session) -> list[str]` — строки отчёта;
  `python -m app.returns.check`

Прогон — брат `app.valuation_check`: он не тест, а способ посмотреть на живые
цифры и проверить три утверждения признака готовности разом. Тест на него нужен
ровно один — что он не падает и печатает разбор сходимости.

- [ ] **Step 1: Write the failing test**

Создать `backend/tests/test_returns_check.py`:

```python
from datetime import date
from decimal import Decimal

from app.models import OperationType
from app.returns.check import check_returns
from tests.test_returns_flows import add_tx
from tests.test_returns_instrument_flows import add_instrument
from tests.test_returns_service import add_snapshot


def test_check_prints_reconciliation_of_parts(session, account):
    instrument = add_instrument(session)
    add_tx(session, account_id=account.id, op_type=OperationType.DEPOSIT,
           day=date(2024, 8, 13), amount="100000")
    add_tx(session, account_id=account.id, op_type=OperationType.BUY,
           day=date(2024, 8, 14), amount="-100000", quantity="100", price="1000",
           instrument_id=instrument.id)
    add_tx(session, account_id=account.id, op_type=OperationType.FEE,
           day=date(2024, 8, 14), amount="-450")
    add_snapshot(session, date(2024, 8, 13), "100000")
    add_snapshot(session, date(2026, 8, 13), "130000")

    lines = check_returns(session)
    text = "\n".join(lines)
    assert "Прибыль портфеля" in text
    assert "Прочее" in text
    # Разбор сходимости разрезов с целым — главное, ради чего прогон существует.
    assert "Расхождение" in text


def test_check_survives_empty_database(session):
    """Пустая база — законное состояние (первый запуск). Прогон обязан сказать
    это словами, а не упасть с исключением."""
    lines = check_returns(session)
    assert any("нет" in line.lower() for line in lines)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_returns_check.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.returns.check'`

- [ ] **Step 3: Write minimal implementation**

Создать `backend/app/returns/check.py`:

```python
"""Прогон доходности на живых данных.

Брат app/valuation_check.py: не тест, а способ увидеть цифры и проверить разом
три утверждения признака готовности фазы — сходимость XIRR по определению,
точность разложения прибыли и сходимость разрезов с целым.

    cd backend && uv run python -m app.returns.check
"""

from decimal import Decimal

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.money import money
from app.returns.service import PERIOD_12M, PERIOD_ALL, PERIOD_YTD, returns_report

PERIOD_TITLES = {PERIOD_ALL: "всё время", PERIOD_12M: "12 месяцев", PERIOD_YTD: "с начала года"}


def _rate(value: Decimal | None) -> str:
    return "—" if value is None else f"{value * 100:.2f} %"


def check_returns(session: Session) -> list[str]:
    lines: list[str] = []

    for period_key in (PERIOD_ALL, PERIOD_12M, PERIOD_YTD):
        report = returns_report(session, period_key)
        period = report.period
        if period.since is None:
            lines.append(f"Период «{PERIOD_TITLES[period_key]}»: истории нет — снимков в базе нет вовсе")
            continue

        suffix = "" if period.annualized else " (за период, не в годовых)"
        lines.append("")
        lines.append(f"=== {PERIOD_TITLES[period_key]}: {period.since} — {period.until}{suffix} ===")
        lines.append(f"XIRR {_rate(report.portfolio.xirr)} · TWR {_rate(report.portfolio.twr)}")
        lines.append(f"Прибыль портфеля {report.portfolio.profit} ₽, "
                     f"вложено {report.portfolio.invested} ₽, "
                     f"стоимость {report.portfolio.value} ₽")

        coverage = report.coverage
        lines.append(f"Покрытие: полная оценка у {coverage.days_valued} дат из "
                     f"{coverage.days_total}; позиций оценено "
                     f"{coverage.positions_valued} из {coverage.positions_total}; "
                     f"разрывов цепочки TWR {coverage.chain_breaks}")
        if coverage.currencies_without_rate:
            lines.append("Потоки без курса: " + ", ".join(coverage.currencies_without_rate))

        # Признак готовности, пункт 3: сумма частей против целого.
        instruments_profit = sum((row.profit for row in report.by_instrument), Decimal("0"))
        parts = money(instruments_profit + report.unattributed.profit)
        lines.append(f"Прочее (комиссии {report.unattributed.fees} ₽, налоги "
                     f"{report.unattributed.taxes} ₽, прочее {report.unattributed.other} ₽): "
                     f"{report.unattributed.profit} ₽")
        lines.append(f"Сумма по бумагам {money(instruments_profit)} ₽ + Прочее = {parts} ₽")
        lines.append(f"Расхождение с прибылью портфеля: {money(parts - report.portfolio.profit)} ₽")

        # Признак готовности, пункт 2: части прибыли против самой прибыли.
        mismatched = [
            row.name for row in report.by_instrument
            if row.price_part is not None and row.fx_part is not None
            and money(row.price_part + row.fx_part) != row.profit and not row.closed
        ]
        if mismatched:
            lines.append("Разложение прибыли разошлось с прибылью у: " + ", ".join(mismatched))
        else:
            lines.append("Разложение прибыли сходится по всем открытым позициям")

        for row in report.by_account:
            lines.append(f"  счёт {row.account_id}: XIRR {_rate(row.metric.xirr)} · "
                         f"TWR {_rate(row.metric.twr)} · прибыль {row.metric.profit} ₽")
        for row in report.by_asset_class:
            lines.append(f"  {row.asset_class}: XIRR {_rate(row.metric.xirr)} · "
                         f"TWR {_rate(row.metric.twr)} · стоимость {row.metric.value} ₽")

    if not lines:
        lines.append("Данных нет: журнал пуст")
    return lines


def main() -> None:
    with SessionLocal() as session:
        for line in check_returns(session):
            print(line)


if __name__ == "__main__":
    main()
```

Свериться с `backend/app/valuation_check.py`: если сессия там открывается иначе
(не `SessionLocal`), повторить тот же способ — двух разных входов в базу для
двух соседних прогонов быть не должно.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_returns_check.py -v`
Expected: PASS, 2 tests

- [ ] **Step 5: Прогнать на живых данных**

Run: `cd backend && uv run python -m app.returns.check`
Expected: печатает три периода. Записать вывод — он понадобится в хендоффе.
**Расхождение суммы частей с прибылью портфеля должно быть нулевым.** Если оно
не ноль — остановиться и разобраться: это и есть признак готовности, а не
формальность.

- [ ] **Step 6: Дописать README**

В разделе про повторяемые прогоны (рядом с `app.valuation_check`) добавить:

```markdown
### Доходность

    cd backend && uv run python -m app.returns.check

Печатает XIRR и TWR портфеля и разрезов за три периода, прибыль с разложением на
ценовую и валютную части и покрытие данных. Проверяет три утверждения признака
готовности фазы 4a: сходимость XIRR по определению, точность разложения прибыли и
сходимость суммы разрезов с прибылью портфеля.
```

- [ ] **Step 7: Commit**

```bash
git add backend/app/returns/check.py backend/tests/test_returns_check.py README.md
git commit -m "feat: прогон доходности на живых данных"
```

---

### Задача 10: клиент и экран «Аналитика»

**Files:**
- Modify: `frontend/src/api/client.ts`
- Create: `frontend/src/pages/AnalyticsPage.tsx`
- Create: `frontend/src/components/ReturnsSummary.tsx`
- Modify: `frontend/src/app/routes.tsx`
- Modify: `frontend/src/App.tsx` (маршрут)
- Test: `frontend/src/components/ReturnsSummary.test.tsx`

**Interfaces:**
- Consumes: `GET /api/analytics/returns` из задачи 8
- Produces: типы `Returns`, `ReturnMetric`, `InstrumentReturn`, `ReturnsCoverage`;
  `api.returns(period)`; компонент `ReturnsSummary`; экран `AnalyticsPage`;
  пункт меню `/analytics`.

- [ ] **Step 1: Write the failing test**

Создать `frontend/src/components/ReturnsSummary.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ReturnsSummary } from "./ReturnsSummary";
import type { Returns } from "../api/client";

const base: Returns = {
  period: { from: "2020-07-16", to: "2026-08-13", annualized: true },
  portfolio: { xirr: "0.1842", twr: "0.1531", profit: "3120455.10",
               invested: "7830000.00", value: "10950455.10", reason: null },
  coverage: { days_total: 2220, days_valued: 448, positions_total: 59,
              positions_valued: 53, unpriced: ["AGRO"], chain_breaks: 0,
              currencies_without_rate: [] },
  by_account: [], by_asset_class: [], by_instrument: [],
  unattributed: { profit: "-103015.00", fees: "-34868.39", taxes: "-77477.00",
                  other: "9330.39" },
};

describe("ReturnsSummary", () => {
  it("показывает обе доходности процентами", () => {
    render(<ReturnsSummary returns={base} />);
    expect(screen.getByText("+18,4%")).toBeInTheDocument();
    expect(screen.getByText("+15,3%")).toBeInTheDocument();
  });

  it("объясняет каждую доходность вопросом, а не термином", () => {
    render(<ReturnsSummary returns={base} />);
    expect(screen.getByText(/сколько принесли мои вложения/i)).toBeInTheDocument();
    expect(screen.getByText(/насколько удачно выбраны бумаги/i)).toBeInTheDocument();
  });

  it("называет причину вместо прочерка", () => {
    const withoutRate = {
      ...base,
      portfolio: { ...base.portfolio, xirr: null, twr: null, reason: "no_flows" },
    };
    render(<ReturnsSummary returns={withoutRate} />);
    expect(screen.getByText(/пополнений и изъятий за период не было/i)).toBeInTheDocument();
  });

  it("предупреждает, когда период короче года", () => {
    const short = {
      ...base,
      period: { from: "2026-01-01", to: "2026-02-14", annualized: false },
    };
    render(<ReturnsSummary returns={short} />);
    expect(screen.getByText(/за период, не в годовых/i)).toBeInTheDocument();
  });

  it("показывает границы периода: цифра посчитана не с начала времён", () => {
    render(<ReturnsSummary returns={base} />);
    expect(screen.getByText(/16\.07\.2020/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && pnpm exec vitest run src/components/ReturnsSummary.test.tsx`
Expected: FAIL — `Failed to resolve import "./ReturnsSummary"`

- [ ] **Step 3: Write minimal implementation**

Дописать в `frontend/src/api/client.ts` (перед `describeError`):

```ts
export interface ReturnMetric {
  // Доля, а не проценты: "0.1842" — это 18,42 %. null — ставки не существует,
  // и причина названа в reason.
  xirr: string | null;
  twr: string | null;
  profit: string;
  invested: string;
  value: string;
  reason: string | null;
}

export interface InstrumentReturn {
  ticker: string | null;
  name: string;
  xirr: string | null;
  profit: string;
  value: string;
  // Позиция продана целиком: стоимость ноль, а история доходности — нет.
  closed: boolean;
  // Разложение прибыли открытой позиции на ценовую и валютную части.
  // null — посчитать нечем, почему именно, говорит reason.
  price_part: string | null;
  fx_part: string | null;
  reason: string | null;
}

export interface ReturnsCoverage {
  days_total: number;
  days_valued: number;
  positions_total: number;
  positions_valued: number;
  unpriced: string[];
  // Сколько дней выпало из цепочки TWR: сравнивать было не с чем.
  chain_breaks: number;
  currencies_without_rate: string[];
}

export interface Returns {
  // Границы периода явные: «за всё время» начинается датой первой операции.
  period: { from: string; to: string; annualized: boolean };
  portfolio: ReturnMetric;
  coverage: ReturnsCoverage;
  by_account: (ReturnMetric & { title: string })[];
  by_asset_class: (ReturnMetric & { asset_class: string })[];
  by_instrument: InstrumentReturn[];
  // Комиссии и налоги, не относящиеся ни к одной бумаге: без этой строки сумма
  // по бумагам не сходится с портфелем.
  unattributed: { profit: string; fees: string; taxes: string; other: string };
}

export type ReturnsPeriod = "all" | "12m" | "ytd";
```

В объект `api` добавить:

```ts
  returns: (period: ReturnsPeriod) =>
    request<Returns>(`/analytics/returns?period=${period}`),
```

Создать `frontend/src/components/ReturnsSummary.tsx`:

```tsx
import { formatDate, formatPercent } from "../api/format";
import { Card, CardTitle } from "../ui/Card";
import type { Returns } from "../api/client";

// Причина отсутствия ставки — словами владельца, а не кодом. Пустая ячейка без
// объяснения оставляет вопрос, на который система знает ответ.
const REASONS: Record<string, string> = {
  no_flows: "Пополнений и изъятий за период не было — доходность вложений посчитать не из чего.",
  no_history: "История стоимости за период не заполнена.",
  cash: "У денежного остатка доходности нет: проценты на него приходят отдельными записями.",
};

// Доходности две, и каждая подписана вопросом, на который отвечает. Термины
// «XIRR» и «TWR» стоят рядом мелко: они нужны, чтобы сверить с брокером, но
// сами по себе не объясняют ничего.
function Rate({ title, question, value, term }: {
  title: string; question: string; value: string | null; term: string;
}) {
  return (
    <div>
      <div className="text-xs text-muted">{title} · {term}</div>
      {/* Доля приходит с бэкенда ("0.1842"); formatPercent ждёт проценты. */}
      <div className="text-2xl font-[650] tabular-nums">
        {value === null ? "—" : formatPercent(String(Number(value) * 100))}
      </div>
      <div className="mt-1 text-xs text-muted">{question}</div>
    </div>
  );
}

export function ReturnsSummary({ returns }: { returns: Returns }) {
  const { period, portfolio } = returns;

  return (
    <Card>
      <CardTitle>Доходность</CardTitle>
      <div className="text-xs text-muted">
        {formatDate(period.from)} — {formatDate(period.to)}
        {period.annualized ? "" : " · за период, не в годовых"}
      </div>

      <div className="mt-3 grid grid-cols-2 gap-3.5">
        <Rate title="Мои вложения" term="XIRR" value={portfolio.xirr}
              question="сколько принесли мои вложения" />
        <Rate title="Выбор бумаг" term="TWR" value={portfolio.twr}
              question="насколько удачно выбраны бумаги" />
      </div>

      {portfolio.reason !== null && (
        <div className="mt-2.5 text-sm text-muted">
          {REASONS[portfolio.reason] ?? portfolio.reason}
        </div>
      )}
    </Card>
  );
}
```

Проверить в `formatPercent`, что вход — проценты (`"18.42"`), а не доля: функция
существующая, и менять её нельзя — её зовут таблицы позиций. Если пересчёт доли
в проценты в `Rate` выглядит громоздко, завести в `format.ts` отдельную
`formatRate(raw: string | null): string`, которая принимает долю, и покрыть её
тестом в `format.test.ts` — но **не менять** поведение `formatPercent`.

Создать `frontend/src/pages/AnalyticsPage.tsx`:

```tsx
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api, type ReturnsPeriod } from "../api/client";
import { ReturnsSummary } from "../components/ReturnsSummary";
import { CardState } from "../ui/CardState";
import { SegmentedControl } from "../ui/SegmentedControl";

const PERIODS: { value: ReturnsPeriod; label: string }[] = [
  { value: "all", label: "Всё время" },
  { value: "12m", label: "12 месяцев" },
  { value: "ytd", label: "С начала года" },
];

export function AnalyticsPage() {
  // Период — состояние экрана, а не часть адреса: то же решение, что на
  // «Портфеле» с переключателем графика.
  const [period, setPeriod] = useState<ReturnsPeriod>("all");
  const returns = useQuery({
    queryKey: ["returns", period],
    queryFn: () => api.returns(period),
  });

  if (returns.isPending) return <CardState kind="loading">Загрузка…</CardState>;
  if (returns.isError) {
    return <CardState kind="error">{(returns.error as Error).message}</CardState>;
  }

  return (
    <div className="grid gap-3.5">
      <SegmentedControl options={PERIODS} value={period} onChange={setPeriod} />
      <ReturnsSummary returns={returns.data} />
    </div>
  );
}
```

В `frontend/src/app/routes.tsx` добавить пункт в `NAV_ITEMS` после «Сделки и
расхождения» и поправить комментарий (Аналитика приехала, в фазе 4 остаются
Календарь выплат и Налоги):

```ts
  { path: "/analytics", title: "Аналитика", group: "Разбор" },
```

В `frontend/src/App.tsx` добавить маршрут рядом с существующими:

```tsx
<Route path="/analytics" element={<AnalyticsPage />} />
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && pnpm exec vitest run src/components/ReturnsSummary.test.tsx`
Expected: PASS, 5 tests

- [ ] **Step 5: Проверить типы и стили**

Run: `cd frontend && pnpm run build && pnpm check:styles --strict`
Expected: сборка без ошибок, проверка стилей зелёная

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api/client.ts frontend/src/pages/AnalyticsPage.tsx frontend/src/components/ReturnsSummary.tsx frontend/src/components/ReturnsSummary.test.tsx frontend/src/app/routes.tsx frontend/src/App.tsx
git commit -m "feat: экран «Аналитика» с двумя доходностями"
```

---

### Задача 11: таблицы разрезов

**Files:**
- Create: `frontend/src/components/ReturnsBreakdown.tsx`
- Modify: `frontend/src/pages/AnalyticsPage.tsx`
- Test: `frontend/src/components/ReturnsBreakdown.test.tsx`

**Interfaces:**
- Consumes: `Returns` из задачи 10, примитивы `Table`, `Th`, `Td`, `Badge`,
  `Card`, `CardTitle`
- Produces: `ReturnsBreakdown` — таблица разреза с колонками «Название»,
  «Доходность», «Прибыль», «Стоимость».

- [ ] **Step 1: Write the failing test**

Создать `frontend/src/components/ReturnsBreakdown.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ReturnsBreakdown } from "./ReturnsBreakdown";

describe("ReturnsBreakdown", () => {
  it("показывает строки разреза", () => {
    render(<ReturnsBreakdown title="По счетам" rows={[
      { key: "Инвестиционный", title: "Инвестиционный", xirr: "0.1842",
        profit: "3120455.10", value: "10950455.10", reason: null },
    ]} />);
    expect(screen.getByText("Инвестиционный")).toBeInTheDocument();
    expect(screen.getByText("+18,4%")).toBeInTheDocument();
  });

  it("метит закрытые позиции", () => {
    render(<ReturnsBreakdown title="По бумагам" rows={[
      { key: "1", title: "Обувь России", xirr: null, profit: "-45000.00",
        value: "0.0000", reason: null, closed: true },
    ]} />);
    expect(screen.getByText("закрыта")).toBeInTheDocument();
  });

  it("объясняет отсутствие числа словами", () => {
    render(<ReturnsBreakdown title="По бумагам" rows={[
      { key: "1", title: "РусАгро", xirr: null, profit: "0.0000",
        value: "120000.00", reason: "no_cost_basis" },
    ]} />);
    expect(screen.getByText(/бумага пришла переводом/i)).toBeInTheDocument();
  });

  it("показывает валютную часть прибыли отдельной колонкой, когда она есть", () => {
    render(<ReturnsBreakdown title="По бумагам" rows={[
      { key: "1", title: "Apple", xirr: "0.21", profit: "26000.00",
        value: "150000.00", reason: null, price_part: "14000.00",
        fx_part: "12000.00" },
    ]} />);
    expect(screen.getByText(/12 000 ₽/)).toBeInTheDocument();
  });

  it("пустой разрез объясняет пустоту", () => {
    render(<ReturnsBreakdown title="По счетам" rows={[]} />);
    expect(screen.getByText(/данных за период нет/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && pnpm exec vitest run src/components/ReturnsBreakdown.test.tsx`
Expected: FAIL — `Failed to resolve import "./ReturnsBreakdown"`

- [ ] **Step 3: Write minimal implementation**

Создать `frontend/src/components/ReturnsBreakdown.tsx`:

```tsx
import { BASE_CURRENCY, formatMoney, formatPercent } from "../api/format";
import { Badge } from "../ui/Badge";
import { Card, CardTitle } from "../ui/Card";
import { CardState } from "../ui/CardState";
import { Table, Td, Th } from "../ui/Table";

// Причины отсутствия числа — словами. Тот же словарь, что в ReturnsSummary, но
// про строку разреза: у бумаги причины свои.
const REASONS: Record<string, string> = {
  no_cost_basis: "бумага пришла переводом, себестоимость неизвестна",
  no_price: "котировки нет",
  no_rate: "нет курса валюты",
  currency_mismatch: "расчёты и котировка в разных валютах",
  cash: "доходности у денежного остатка нет",
  no_flows: "движения за период не было",
  no_history: "истории за период нет",
};

export interface BreakdownRow {
  key: string;
  title: string;
  xirr: string | null;
  profit: string;
  value: string;
  reason: string | null;
  closed?: boolean;
  price_part?: string | null;
  fx_part?: string | null;
}

export function ReturnsBreakdown({ title, rows }: { title: string; rows: BreakdownRow[] }) {
  const showFx = rows.some((row) => row.fx_part !== null && row.fx_part !== undefined);

  return (
    <Card>
      <CardTitle>{title}</CardTitle>
      {rows.length === 0 ? (
        <CardState kind="empty">Данных за период нет</CardState>
      ) : (
        <Table>
          <thead>
            <tr>
              <Th>Название</Th>
              <Th numeric>Доходность</Th>
              <Th numeric>Прибыль</Th>
              {showFx && <Th numeric>из них валютная</Th>}
              <Th numeric>Стоимость</Th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.key}>
                <td className="border-b border-line py-2 pr-2">
                  {row.title}
                  {row.closed === true && <span className="ml-1.5"><Badge>закрыта</Badge></span>}
                  {row.reason !== null && (
                    <div className="text-xs text-muted">{REASONS[row.reason] ?? row.reason}</div>
                  )}
                </td>
                <Td numeric>
                  {row.xirr === null ? "—" : formatPercent(String(Number(row.xirr) * 100))}
                </Td>
                <Td numeric>{formatMoney(row.profit, BASE_CURRENCY)}</Td>
                {showFx && <Td numeric>{formatMoney(row.fx_part ?? null, BASE_CURRENCY)}</Td>}
                <Td numeric>{formatMoney(row.value, BASE_CURRENCY)}</Td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
    </Card>
  );
}
```

Дописать `AnalyticsPage`: три таблицы плюс строка «Прочее» под таблицей бумаг и
`CoverageNotice`-подобная плашка покрытия. Прибыль и стоимость строки «Прочее»
приходят из `returns.unattributed`, и она добавляется последней строкой разреза
по бумагам:

```tsx
      <ReturnsBreakdown title="По счетам" rows={data.by_account.map((row) => ({
        key: row.title, title: row.title, xirr: row.xirr, profit: row.profit,
        value: row.value, reason: row.reason,
      }))} />

      <ReturnsBreakdown title="По классам активов" rows={data.by_asset_class.map((row) => ({
        key: row.asset_class, title: ASSET_CLASS_TITLES[row.asset_class] ?? row.asset_class,
        xirr: row.xirr, profit: row.profit, value: row.value, reason: row.reason,
      }))} />

      <ReturnsBreakdown title="По бумагам" rows={[
        ...data.by_instrument.map((row) => ({
          key: `${row.ticker ?? row.name}`, title: row.name, xirr: row.xirr,
          profit: row.profit, value: row.value, reason: row.reason,
          closed: row.closed, price_part: row.price_part, fx_part: row.fx_part,
        })),
        {
          key: "unattributed", title: "Прочее (комиссии и налоги без бумаги)",
          xirr: null, profit: data.unattributed.profit, value: "0.0000",
          reason: null,
        },
      ]} />
```

`ASSET_CLASS_TITLES` уже существует во фронте — найти его (он используется
`AllocationChart`) и импортировать оттуда, а не заводить вторую копию. Если его
там нет, завести в `frontend/src/api/format.ts` и покрыть тестом.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && pnpm exec vitest run`
Expected: PASS, все тесты фронта (80 прежних + 10 новых)

- [ ] **Step 5: Проверить типы и стили**

Run: `cd frontend && pnpm run build && pnpm check:styles --strict`
Expected: сборка без ошибок, ноль инлайн-стилей и hex-литералов

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/ReturnsBreakdown.tsx frontend/src/components/ReturnsBreakdown.test.tsx frontend/src/pages/AnalyticsPage.tsx
git commit -m "feat: таблицы разрезов доходности на экране «Аналитика»"
```

---

### Задача 12: две цифры на «Портфеле» и закрытие фазы

**Files:**
- Modify: `frontend/src/components/SummaryCard.tsx`
- Modify: `frontend/src/pages/PortfolioPage.tsx`
- Modify: `docs/roadmap.md`
- Test: `frontend/src/components/SummaryCard.test.tsx` (создать, если нет)

**Interfaces:**
- Consumes: `api.returns("all")` из задачи 10
- Produces: XIRR и прибыль за всё время в `SummaryCard`

- [ ] **Step 1: Write the failing test**

Создать или дополнить `frontend/src/components/SummaryCard.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SummaryCard } from "./SummaryCard";
import type { Overview, ReturnMetric } from "../api/client";

const overview: Overview = {
  total_value: "10950455.1000", securities_value: "9950455.1000",
  cash_value: "1000000.0000", restricted_value: "0.0000",
  by_asset_class: {}, by_account: {}, by_currency: {},
  position_currencies: ["RUB"], currencies_without_rate: [],
  as_of: "2026-08-13", fx_as_of: "2026-08-13",
  valued_positions: 59, positions_total: 59,
};

const metric: ReturnMetric = {
  xirr: "0.1842", twr: "0.1531", profit: "3120455.1000",
  invested: "7830000.0000", value: "10950455.1000", reason: null,
};

describe("SummaryCard", () => {
  it("показывает доходность и прибыль рядом с капиталом", () => {
    render(<SummaryCard overview={overview} returns={metric} />);
    expect(screen.getByText("+18,4%")).toBeInTheDocument();
    expect(screen.getByText(/3 120 455 ₽/)).toBeInTheDocument();
  });

  it("без доходности карточка остаётся прежней", () => {
    render(<SummaryCard overview={overview} returns={null} />);
    expect(screen.getByText("Совокупный капитал")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && pnpm exec vitest run src/components/SummaryCard.test.tsx`
Expected: FAIL — `SummaryCard` не принимает `returns`

- [ ] **Step 3: Write minimal implementation**

В `SummaryCard.tsx` добавить необязательный параметр и блок под `CapitalParts`:

```tsx
// Доходность на «Портфеле» — две цифры, не больше: разбор живёт на «Аналитике».
// null означает «ещё грузится или не посчиталась» — карточка при этом обязана
// выглядеть ровно как прежде, а не мигать пустым местом.
function ReturnsLine({ returns }: { returns: ReturnMetric | null }) {
  if (returns === null) return null;

  return (
    <div className="mt-1.5 text-xs text-muted">
      Заработано{" "}
      <span className="text-tx">{formatMoney(returns.profit, BASE_CURRENCY)}</span>
      {returns.xirr !== null && (
        <>
          {" · доходность "}
          <span className="text-tx">{formatPercent(String(Number(returns.xirr) * 100))}</span>
          {" годовых"}
        </>
      )}
    </div>
  );
}
```

В `PortfolioPage.tsx` добавить запрос и передать метрику:

```tsx
  // Тот же обработчик, что на «Аналитике»: отдельной ручки под две цифры не
  // существует, а react-query отдаст ответ из кэша при переходе между экранами.
  const returns = useQuery({ queryKey: ["returns", "all"], queryFn: () => api.returns("all") });
```

```tsx
          <SummaryCard overview={overview.data!} returns={returns.data?.portfolio ?? null} />
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && pnpm exec vitest run`
Expected: PASS, все тесты

- [ ] **Step 5: Прогнать всё и проверить признак готовности**

```bash
cd backend && uv run pytest
cd frontend && pnpm exec vitest run && pnpm run build && pnpm check:styles --strict
cd backend && uv run python -m app.returns.check
```

Признак готовности выполнен, если:

1. прогон `check` показывает расхождение суммы разрезов с прибылью портфеля
   **ноль**;
2. в его выводе строка «Разложение прибыли сходится по всем открытым позициям»;
3. тест `test_result_satisfies_its_own_definition` зелёный (XIRR по определению);
4. два запуска `check` подряд без синхронизации дают одинаковые числа.

Если какой-то пункт не выполняется — **остановиться и разобраться**, а не
записывать фазу закрытой: это ровно те утверждения, ради которых фаза делалась.

- [ ] **Step 6: Обновить роадмеп**

В `docs/roadmap.md`: раздел «Фаза 4. Аналитика» разделить на 4a (завершена, с
измеренными цифрами прогона) и 4b–4d (запланированы); в таблице статусов
поправить строку фазы 4; в «Где мы сейчас» добавить абзац про доходность с
цифрами живого прогона.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/SummaryCard.tsx frontend/src/components/SummaryCard.test.tsx frontend/src/pages/PortfolioPage.tsx docs/roadmap.md
git commit -m "feat: доходность и прибыль на экране «Портфель»"
```

---

## Самопроверка плана

Проверено после написания, против дизайна:

- **Раздел 4.1 дизайна (XIRR)** — задача 1. Ньютон с откатом на бисекцию, `None`
  как законный ответ, допуск в копейку, база 365 дней — всё на месте.
- **Раздел 4.2 (потоки)** — задачи 3 и 4. Четыре периметра, гашение пар,
  `INP_MULTI`/`OUT_MULTI` из `payload`, партии без себестоимости, курс на дату
  операции.
- **Раздел 4.3 (TWR)** — задача 5. Формула, разрывы цепочки, аннуализация от
  года.
- **Раздел 4.4 (разложение прибыли)** — задача 6. Формулы по партиям,
  перекрёстный член в валютной части, рублёвая бумага даёт ноль.
- **Раздел 4.5 (особые случаи)** — задачи 6, 7, 11: каждая причина заведена
  константой, переведена в слова в `REASONS` и покрыта тестом.
- **Раздел 5 (контракт)** — задача 8. Все поля ответа, включая `unattributed`.
- **Раздел 6 (интерфейс)** — задачи 10–12. Экран, пункт меню в группе «Разбор»,
  примитивы фазы 3, две цифры на «Портфеле».
- **Раздел 7 (признак готовности)** — задачи 9 и 12: три утверждения проверяются
  прогоном, четвёртое — тестом.

**Отступления от дизайна, внесённые планом осознанно:**

1. **Появился `rates.py`** — дизайн перечислял четыре модуля расчёта. Причина:
   курс на дату нужен и потокам, и разложению прибыли; общая зависимость,
   спрятанная в одном из них, связывает их между собой.
2. **У класса «деньги» доходность не считается** (задача 7). Дизайн предполагал
   видеть покупку бумаги как поток между классами. Причина отступления записана в
   коде: доходности у остатка не существует, а проценты на него уже посчитаны
   строкой «Прочее».
3. **XIRR по бумаге не показывается на периодах короче года** (задача 7,
   `if period.annualized`). То же правило, что у портфеля, и по той же причине.

Все три — уточнения, а не сокращения объёма. Если владелец с каким-то не
согласен, поправка стоит одной задачи.

</content>
