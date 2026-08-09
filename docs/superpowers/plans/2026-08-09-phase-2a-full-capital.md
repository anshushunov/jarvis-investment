# Фаза 2a «Капитал целиком» — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Совокупный капитал портфеля показывает все активы всех счетов Т-Банка
в рублях — бумаги в любой валюте, денежные остатки и золото, — и сходится с
цифрой брокера; заблокированные бумаги видны отдельно.

**Architecture:** Курсы валют приходят от ЦБ в новую таблицу `fx_rate` и
применяются на границе оценки. Таблица `price` начинает хранить валюту цены и
источник, потому что появляется второй источник: цена самого брокера
(`GetPortfolio.currentPrice`) для того, чего MOEX не котирует. Денежные остатки
и заблокированные количества — снимок брокера в отдельных таблицах
`cash_balance` и `broker_holding`, обновляемый синхронизацией; журнал операций
остаётся источником истины по позициям, снимок брокера — предметом сверки, как
и было.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL 16,
pytest на настоящей базе; React 19 + TypeScript + Vite, Vitest.

## Global Constraints

- Все денежные величины — `Decimal` через `app.money.money()` / `quantity()`,
  нигде не `float`. `money()` квантует до 4 знаков, `quantity()` — до 8.
- Базовая валюта — `app.money.BASE_CURRENCY` (`"RUB"`).
- Комментарии, докстринги, сообщения об ошибках и коммиты — по-русски.
  Авторство LLM в коммитах не указывается.
- Тесты запускаются на настоящем PostgreSQL: `cd backend && uv run pytest`.
  `uv` лежит в `C:\Users\User\.local\bin` и не в PATH —
  `export PATH="$PATH:/c/Users/User/.local/bin"`.
- База разработки — `localhost:5433`, бэкенд — `8001`, фронтенд — `3000`.
  Порты 5432 и 8000 заняты посторонними контейнерами, их не трогать.
- Проверка типа операции, читаемой из БД, покрывается тестом, поднимающим
  данные из базы: `Transaction.op_type` хранится как `String(24)`, и после
  чтения это `str`, а не `OperationType` (перевод на Enum — задача фазы 2b).
- `POST /api/sync/tbank` ходит в живой счёт владельца. Запускать только по
  явному согласию; читающие вызовы брокера (`GetPortfolio`, `GetPositions`) —
  свободно, они ничего не меняют.
- Фронтенд собирается без ошибок типов: `cd frontend && pnpm build`.

## Что установлено разведкой живого API 09.08.2026

Эти факты проверены на настоящем счёте, на них опирается весь план — заново
выяснять не нужно.

- `OperationsService/GetPositions` отдаёт `money` (массив `MoneyValue` по
  валютам), `blocked` (заблокированные деньги, обычно пустой), `securities`
  (`figi`, `balance`, `blocked`, `ticker`, `instrumentType`, `exchangeBlocked`),
  `futures`, `options`.
- `balance + blocked` из `GetPositions.securities` в точности равно `quantity`
  из `GetPortfolio.positions` — проверено на 43 бумагах, расхождений ноль.
  Значит `blocked` — часть общего количества, а не добавка к нему.
- На счёте «Инвестиционный» заблокированы две позиции: `HK0000123577`
  (`balance=0`, `blocked=92`) и `HK0000051877` (`balance=0`, `blocked=79`).
  Обе — те самые, что висят в расхождениях как корпоративные действия.
- `GetPositions` отвечает **404 `Account not found`** для счёта типа
  `ACCOUNT_TYPE_DFA` («Смарт-счет», цифровые финансовые активы). `GetPortfolio`
  для него работает, но `totalAmountPortfolio` не присылает вовсе.
- `GetPortfolio.positions[].currentPrice` — цена одной бумаги **в валюте
  бумаги** (`rub`, `hkd`, `usd`, `cny`), включая облигации: у них это деньги за
  штуку, а не процент от номинала. Рядом есть `currentNkd` — накопленный
  купонный доход, в этой фазе он не используется.
- Денежные остатки приходят в `GetPositions.money` и дублируются в
  `GetPortfolio.positions` псевдо-инструментами (`RUB000UTSTOM`,
  `USD000UTSTOM`, `CNYRUB_TOM_CETS`, `EUR_RUB__TOM_CETS`, `GLDRUB_TOM`).
  Брать нужно **один из двух источников**, иначе деньги удвоятся. План берёт
  `GetPositions.money`.
- Остаток бывает отрицательным: на счёте «Копилка» `rub = -3571.34`.
- Золото приходит в `money` под кодом `xau` (10 — это граммы) и попадает в
  брокерский `totalAmountCurrencies`. Курса золота у ЦБ в `XML_daily` нет;
  берётся цена `GLDRUB_TOM` с MOEX (движок `currency`, рынок `selt`).
- `https://www.cbr.ru/scripts/XML_daily.asp?date_req=DD/MM/YYYY` отдаёт XML в
  `windows-1251`, десятичная запятая, у каждой валюты `CharCode`, `Nominal`,
  `Value`. Атрибут `Date` корня `ValCurs` — дата, на которую курс установлен:
  запрос на воскресенье 09.08.2026 вернул `Date="08.08.2026"`. Курс = `Value / Nominal`.
- Брокерские итоги по счетам на 09.08.2026: Инвестиционный 5 333 989 ₽,
  Копилка 5 431 598 ₽, Лежебока 715 202 ₽, ИИС 4 000 ₽, Казино 0 ₽,
  Смарт-счет без итога. Всего около 11.48 млн ₽ против 6.94 млн ₽, которые
  сейчас показывает дашборд.

## Структура файлов

Создаются:

| Файл | Ответственность |
|---|---|
| `backend/app/models/fx_rate.py` | таблица курсов валют к рублю |
| `backend/app/models/cash_balance.py` | денежные остатки счёта по валютам (снимок брокера) |
| `backend/app/models/broker_holding.py` | снимок бумаг у брокера: количество и заблокированная часть |
| `backend/app/marketdata/cbr.py` | HTTP-клиент ЦБ, разбор `XML_daily` |
| `backend/app/marketdata/fx.py` | загрузка курсов в базу и пересчёт сумм в рубли |
| `backend/app/analytics/valuation.py` | оценка одной позиции: цена → валюта → рубли |
| `backend/app/valuation_check.py` | сверка нашего итога с итогом брокера, запускается вручную |
| `backend/alembic/versions/0010_fx_rate.py` … `0014_instrument_trading_restricted.py` | миграции |
| `backend/tests/test_cbr.py`, `test_fx.py`, `test_valuation.py`, `test_cash.py`, `test_broker_holding.py`, `test_restrictions.py` | тесты новых модулей |
| `frontend/src/components/CashCard.tsx` | денежные остатки по валютам |

Изменяются:

| Файл | Что меняется |
|---|---|
| `backend/app/models/price.py` | колонки `currency` и `source` в ключе уникальности |
| `backend/app/models/instrument.py` | колонка `trading_restricted` |
| `backend/app/connectors/tbank/mapper.py` | флаги торгуемости в payload операции |
| `backend/app/instruments/service.py`, `backfill.py` | перенос флагов в справочник |
| `backend/app/connectors/base.py` | `BrokerPosition.blocked`, новые `BrokerCash` и `BrokerPrice`, расширение протокола |
| `backend/app/connectors/tbank/connector.py` | `fetch_cash`, `fetch_prices`, заполнение `blocked` |
| `backend/app/marketdata/service.py` | валюта цены, приоритет источников в `latest_prices` |
| `backend/app/analytics/service.py` | капитал = бумаги + деньги, всё в рублях |
| `backend/app/sync/service.py` | запись денег и снимка бумаг при синхронизации |
| `backend/app/sync/reconcile.py` | сверка читает снимок из `broker_holding` |
| `backend/app/scheduler.py` | ежедневная загрузка курсов |
| `backend/app/api/schemas.py`, `routes_portfolio.py` | новые поля контракта |
| `frontend/src/api/client.ts`, `components/SummaryCard.tsx`, `AllocationChart.tsx`, `PositionsTable.tsx`, `pages/PortfolioPage.tsx` | показ полного капитала, денег, блокировок |

---

### Task 1: Курсы валют ЦБ

**Files:**
- Create: `backend/app/models/fx_rate.py`
- Create: `backend/app/marketdata/cbr.py`
- Create: `backend/app/marketdata/fx.py`
- Create: `backend/alembic/versions/0010_fx_rate.py`
- Create: `backend/tests/test_cbr.py`
- Create: `backend/tests/test_fx.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/config.py`

**Interfaces:**
- Produces: `FxRate` (модель: `currency: str`, `on_date: date`, `rate: Decimal`,
  `source: str`); `CbrClient.rates(on_date: date) -> tuple[date, dict[str, Decimal]]`
  — возвращает дату, на которую курсы установлены, и отображение код валюты →
  рублей за одну единицу; `refresh_fx_rates(session, client, on_date) -> int`;
  `latest_rates(session, on_date) -> dict[str, Decimal]` — курсы, действующие на
  дату, включая `RUB: 1`; `to_base(amount: Decimal, currency: str, rates: dict[str, Decimal]) -> Decimal | None`.

- [ ] **Step 1: Написать падающий тест разбора ответа ЦБ**

Создать `backend/tests/test_cbr.py`:

```python
from datetime import date
from decimal import Decimal

from app.marketdata.cbr import CbrClient

# Обрезанный настоящий ответ ЦБ: кодировка windows-1251, десятичная запятая,
# номинал не всегда единица (иена — сто). Атрибут Date корня — дата, НА которую
# курс установлен: запрос на воскресенье 09.08.2026 вернул 08.08.2026.
SAMPLE = """<?xml version="1.0" encoding="windows-1251"?>
<ValCurs Date="08.08.2026" name="Foreign Currency Market">
<Valute ID="R01235"><NumCode>840</NumCode><CharCode>USD</CharCode><Nominal>1</Nominal><Name>Доллар США</Name><Value>82,1665</Value><VunitRate>82,1665</VunitRate></Valute>
<Valute ID="R01200"><NumCode>344</NumCode><CharCode>HKD</CharCode><Nominal>1</Nominal><Name>Гонконгских долларов</Name><Value>10,4724</Value><VunitRate>10,4724</VunitRate></Valute>
<Valute ID="R01375"><NumCode>156</NumCode><CharCode>CNY</CharCode><Nominal>1</Nominal><Name>Китайский юань</Name><Value>12,1655</Value><VunitRate>12,1655</VunitRate></Valute>
<Valute ID="R01820"><NumCode>392</NumCode><CharCode>JPY</CharCode><Nominal>100</Nominal><Name>Японских иен</Name><Value>55,7100</Value><VunitRate>0,557100</VunitRate></Valute>
</ValCurs>"""


class FakeTransport:
    def __init__(self, body: str) -> None:
        self.body = body
        self.params: dict[str, str] | None = None

    def __call__(self, url: str, params: dict[str, str], timeout: float) -> bytes:
        self.params = params
        return self.body.encode("windows-1251")


def test_parses_rates_and_effective_date():
    transport = FakeTransport(SAMPLE)
    client = CbrClient(fetch=transport)

    on_date, rates = client.rates(date(2026, 8, 9))

    assert on_date == date(2026, 8, 8)
    assert rates["USD"] == Decimal("82.1665")
    assert rates["HKD"] == Decimal("10.4724")
    assert transport.params == {"date_req": "09/08/2026"}


def test_divides_value_by_nominal():
    """Иена котируется за сотню: без деления на номинал позиция в иенах
    завысилась бы ровно в сто раз."""
    on_date, rates = CbrClient(fetch=FakeTransport(SAMPLE)).rates(date(2026, 8, 9))

    assert rates["JPY"] == Decimal("0.55710000")


def test_rouble_is_not_in_the_answer():
    """Рубль ЦБ не котирует сам к себе; единицу подставляет читающая сторона
    (latest_rates), а не разбор ответа."""
    _, rates = CbrClient(fetch=FakeTransport(SAMPLE)).rates(date(2026, 8, 9))

    assert "RUB" not in rates
```

- [ ] **Step 2: Запустить тест и убедиться, что он падает**

Run: `cd backend && uv run pytest tests/test_cbr.py -v`
Expected: FAIL с `ModuleNotFoundError: No module named 'app.marketdata.cbr'`

- [ ] **Step 3: Написать клиент ЦБ**

Создать `backend/app/marketdata/cbr.py`:

```python
from datetime import date, datetime
from decimal import Decimal
from typing import Callable
from xml.etree import ElementTree

import httpx

from app.config import get_settings

# ЦБ отдаёт XML в windows-1251 и с десятичной запятой. httpx угадывает
# кодировку по заголовку, но полагаться на это не стоит: разбираем байты сами.
ENCODING = "windows-1251"
# Курс к рублю хранится с восемью знаками: у валют с номиналом в сто и тысячу
# (иена, донг) четырёх знаков не хватает — 0.0027 вместо 0.00274523 даёт
# ошибку в проценты.
RATE_EXP = Decimal("0.00000001")


def _http_get(url: str, params: dict[str, str], timeout: float) -> bytes:
    response = httpx.get(url, params=params, timeout=timeout)
    response.raise_for_status()
    return response.content


class CbrClient:
    """Курсы валют Банка России из XML_daily.

    Выбран XML_daily, а не SOAP-сервис DailyInfoWebServ из спеки: тот же набор
    данных отдаётся обычным GET без конверта SOAP, а курсы на дату — ровно то
    единственное, что от ЦБ нужно этой фазе.
    """

    def __init__(
        self,
        base_url: str | None = None,
        timeout: float = 15.0,
        fetch: Callable[[str, dict[str, str], float], bytes] = _http_get,
    ) -> None:
        self.base_url = (base_url or get_settings().cbr_base_url).rstrip("/")
        self.timeout = timeout
        # Внедряемая загрузка: тесты разбирают записанный ответ, не выходя в сеть.
        self._fetch = fetch

    def rates(self, on_date: date) -> tuple[date, dict[str, Decimal]]:
        """Курсы, действующие на `on_date`, и дата, на которую они установлены.

        Эти две даты не совпадают в выходные и праздники: ЦБ не публикует курс
        на каждый календарный день, и на запрос воскресенья отвечает курсом
        пятницы, сообщая это атрибутом Date. Записывать такой курс под
        запрошенной датой значит выдумать публикацию, которой не было; поэтому
        дата возвращается наружу и хранение идёт под ней.
        """
        body = self._fetch(
            f"{self.base_url}/scripts/XML_daily.asp",
            {"date_req": on_date.strftime("%d/%m/%Y")},
            self.timeout,
        )
        root = ElementTree.fromstring(body.decode(ENCODING))
        effective = datetime.strptime(root.attrib["Date"], "%d.%m.%Y").date()

        rates: dict[str, Decimal] = {}
        for valute in root.findall("Valute"):
            code = (valute.findtext("CharCode") or "").upper()
            nominal = valute.findtext("Nominal")
            value = valute.findtext("Value")
            if not code or not nominal or not value:
                continue
            rate = Decimal(value.replace(",", ".")) / Decimal(nominal)
            rates[code] = rate.quantize(RATE_EXP)
        return effective, rates
```

Добавить в `backend/app/config.py` в класс `Settings`, после `moex_base_url`:

```python
    cbr_base_url: str = "https://www.cbr.ru"
```

- [ ] **Step 4: Запустить тест и убедиться, что он проходит**

Run: `cd backend && uv run pytest tests/test_cbr.py -v`
Expected: PASS, 3 теста

- [ ] **Step 5: Написать падающий тест хранения и чтения курсов**

Создать `backend/tests/test_fx.py`:

```python
from datetime import date
from decimal import Decimal

from app.marketdata.fx import latest_rates, refresh_fx_rates, to_base
from app.models import FxRate


class FakeCbr:
    def __init__(self, effective: date, rates: dict[str, Decimal]) -> None:
        self.effective = effective
        self.rates_by_code = rates
        self.calls: list[date] = []

    def rates(self, on_date: date) -> tuple[date, dict[str, Decimal]]:
        self.calls.append(on_date)
        return self.effective, self.rates_by_code


def test_stores_rates_under_effective_date(session):
    client = FakeCbr(date(2026, 8, 8), {"USD": Decimal("82.1665"), "HKD": Decimal("10.4724")})

    written = refresh_fx_rates(session, client, date(2026, 8, 9))

    assert written == 2
    stored = session.query(FxRate).order_by(FxRate.currency).all()
    assert [(r.currency, r.on_date, r.source) for r in stored] == [
        ("HKD", date(2026, 8, 8), "cbr"),
        ("USD", date(2026, 8, 8), "cbr"),
    ]


def test_second_run_updates_instead_of_duplicating(session):
    client = FakeCbr(date(2026, 8, 8), {"USD": Decimal("82.1665")})
    refresh_fx_rates(session, client, date(2026, 8, 9))

    client.rates_by_code = {"USD": Decimal("83.0000")}
    refresh_fx_rates(session, client, date(2026, 8, 9))

    stored = session.query(FxRate).all()
    assert len(stored) == 1
    assert stored[0].rate == Decimal("83.00000000")


def test_latest_rates_take_newest_on_or_before_date(session):
    session.add_all([
        FxRate(currency="USD", on_date=date(2026, 8, 6), rate=Decimal("80"), source="cbr"),
        FxRate(currency="USD", on_date=date(2026, 8, 8), rate=Decimal("82"), source="cbr"),
        FxRate(currency="USD", on_date=date(2026, 8, 12), rate=Decimal("85"), source="cbr"),
    ])
    session.flush()

    rates = latest_rates(session, date(2026, 8, 10))

    assert rates["USD"] == Decimal("82")


def test_rouble_needs_no_stored_rate(session):
    """Единица для рубля подставляется всегда: без неё рублёвые суммы
    оставались бы непересчитанными ровно в тот день, когда ЦБ недоступен."""
    assert latest_rates(session, date(2026, 8, 10))["RUB"] == Decimal("1")


def test_to_base_returns_none_for_unknown_currency(session):
    """Курса нет — честное «оценки нет». Молчаливое «взять как рубли» завысило
    бы гонконгскую позицию в десять раз."""
    rates = {"RUB": Decimal("1")}

    assert to_base(Decimal("100"), "HKD", rates) is None
    assert to_base(Decimal("100"), "RUB", rates) == Decimal("100.0000")
```

- [ ] **Step 6: Запустить тест и убедиться, что он падает**

Run: `cd backend && uv run pytest tests/test_fx.py -v`
Expected: FAIL с `ModuleNotFoundError: No module named 'app.marketdata.fx'`

- [ ] **Step 7: Написать модель, миграцию и сервис курсов**

Создать `backend/app/models/fx_rate.py`:

```python
from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class FxRate(Base):
    """Курс одной единицы валюты к рублю на дату.

    Источник не обязательно ЦБ: золото (`XAU`) приходит с MOEX, потому что в
    XML_daily драгоценных металлов нет, а в денежных остатках Т-Банка золото
    лежит наравне с валютами.
    """

    __tablename__ = "fx_rate"
    __table_args__ = (UniqueConstraint("currency", "on_date", name="uq_fx_rate_currency_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    currency: Mapped[str] = mapped_column(String(3), index=True)
    on_date: Mapped[date] = mapped_column(Date, index=True)
    # Восемь знаков: у валют с номиналом в сто и тысячу четырёх не хватает.
    rate: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    source: Mapped[str] = mapped_column(String(16), default="cbr")
```

Дописать в `backend/app/models/__init__.py` импорт `from app.models.fx_rate import FxRate`
и строку `"FxRate",` в `__all__` (список отсортирован по алфавиту — между `DailySnapshot` и `Instrument`).

Создать `backend/alembic/versions/0010_fx_rate.py`:

```python
"""fx rate

Revision ID: 0010
Revises: 0009

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0010'
down_revision: Union[str, Sequence[str], None] = '0009'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'fx_rate',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('currency', sa.String(length=3), nullable=False),
        sa.Column('on_date', sa.Date(), nullable=False),
        sa.Column('rate', sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column('source', sa.String(length=16), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('currency', 'on_date', name='uq_fx_rate_currency_date'),
    )
    op.create_index(op.f('ix_fx_rate_currency'), 'fx_rate', ['currency'], unique=False)
    op.create_index(op.f('ix_fx_rate_on_date'), 'fx_rate', ['on_date'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_fx_rate_on_date'), table_name='fx_rate')
    op.drop_index(op.f('ix_fx_rate_currency'), table_name='fx_rate')
    op.drop_table('fx_rate')
```

Создать `backend/app/marketdata/fx.py`:

```python
from datetime import date
from decimal import Decimal
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import FxRate
from app.money import BASE_CURRENCY, money

CBR_SOURCE = "cbr"


class RateSource(Protocol):
    def rates(self, on_date: date) -> tuple[date, dict[str, Decimal]]: ...


def refresh_fx_rates(session: Session, client: RateSource, on_date: date) -> int:
    """Загружает курсы, действующие на `on_date`, под датой их установления.

    Пишутся все валюты ответа, а не только встречающиеся в портфеле: запрос
    один и тот же, а список валют портфеля меняется при каждой покупке — искать
    потом, почему у одной позиции курса нет, дороже, чем хранить сорок строк в
    сутки.
    """
    effective, rates = client.rates(on_date)

    for currency, rate in rates.items():
        statement = insert(FxRate).values(
            currency=currency, on_date=effective, rate=rate, source=CBR_SOURCE
        ).on_conflict_do_update(
            index_elements=[FxRate.currency, FxRate.on_date],
            set_={"rate": rate, "source": CBR_SOURCE},
        )
        session.execute(statement)

    session.flush()
    return len(rates)


def latest_rates(session: Session, on_date: date) -> dict[str, Decimal]:
    """Курсы, действующие на дату: по каждой валюте самый свежий курс не позже
    неё. Не «курс ровно на эту дату»: ЦБ не публикует курсы в выходные, и
    оценка портфеля в субботу иначе оставалась бы без валют вовсе."""
    ranked = select(
        FxRate.currency,
        FxRate.rate,
        func.row_number().over(
            partition_by=FxRate.currency, order_by=FxRate.on_date.desc()
        ).label("rn"),
    ).where(FxRate.on_date <= on_date).subquery()

    rows = session.execute(
        select(ranked.c.currency, ranked.c.rate).where(ranked.c.rn == 1)
    ).all()

    result = {currency: rate for currency, rate in rows}
    # Рубль к рублю — единица, и она не хранится: строка в таблице, которая
    # никогда не меняется, лишь создаёт впечатление, что её можно не найти.
    result[BASE_CURRENCY] = Decimal("1")
    return result


def to_base(amount: Decimal, currency: str, rates: dict[str, Decimal]) -> Decimal | None:
    """Сумма в рублях либо None, если курса нет.

    None, а не сумма как есть: неизвестный курс означает неизвестную оценку.
    Подставить рубль вместо гонконгского доллара — занизить позицию вдесятеро и
    показать это как точную цифру.
    """
    rate = rates.get(currency.upper())
    if rate is None:
        return None
    return money(amount * rate)
```

- [ ] **Step 8: Запустить тесты и убедиться, что они проходят**

Run: `cd backend && uv run pytest tests/test_fx.py tests/test_cbr.py tests/test_migrations.py -v`
Expected: PASS

- [ ] **Step 9: Коммит**

```bash
git add backend/app/models/fx_rate.py backend/app/models/__init__.py \
        backend/app/marketdata/cbr.py backend/app/marketdata/fx.py \
        backend/app/config.py backend/alembic/versions/0010_fx_rate.py \
        backend/tests/test_cbr.py backend/tests/test_fx.py
git commit -m "feat: курсы валют ЦБ в таблице fx_rate"
```

---

### Task 2: Курс золота с MOEX

**Files:**
- Modify: `backend/app/marketdata/fx.py`
- Modify: `backend/tests/test_fx.py`

**Interfaces:**
- Consumes: `FxRate`, `refresh_fx_rates` из задачи 1; `MoexClient.quote(secid, market, engine)`
  из `app/marketdata/moex.py` — возвращает `MoexQuote(price, face_value, face_unit)`.
- Produces: `refresh_metal_rates(session, client, on_date) -> int`; константа
  `METAL_SECIDS: dict[str, str]` (код металла → идентификатор MOEX).

- [ ] **Step 1: Написать падающий тест**

Дописать в `backend/tests/test_fx.py`:

```python
from app.marketdata.fx import refresh_metal_rates
from app.marketdata.moex import MoexQuote


class FakeMoexForMetals:
    def __init__(self, prices: dict[str, Decimal | None]) -> None:
        self.prices = prices
        self.calls: list[tuple[str, str, str]] = []

    def quote(self, secid: str, market: str = "shares", engine: str = "stock") -> MoexQuote:
        self.calls.append((secid, engine, market))
        return MoexQuote(price=self.prices.get(secid))


def test_gold_rate_comes_from_moex(session):
    """У ЦБ в XML_daily драгоценных металлов нет, а в денежных остатках
    Т-Банка золото лежит наравне с валютами — 10 граммов под кодом xau."""
    client = FakeMoexForMetals({"GLDRUB_TOM": Decimal("11410")})

    written = refresh_metal_rates(session, client, date(2026, 8, 9))

    assert written == 1
    assert client.calls == [("GLDRUB_TOM", "currency", "selt")]
    assert latest_rates(session, date(2026, 8, 9))["XAU"] == Decimal("11410")
    assert session.query(FxRate).one().source == "moex"


def test_metal_without_quote_is_skipped(session):
    """Нет котировки — нет строки курса. Позиция в золоте останется
    неоценённой, и это честнее нуля."""
    written = refresh_metal_rates(session, FakeMoexForMetals({}), date(2026, 8, 9))

    assert written == 0
    assert "XAU" not in latest_rates(session, date(2026, 8, 9))
```

- [ ] **Step 2: Запустить тест и убедиться, что он падает**

Run: `cd backend && uv run pytest tests/test_fx.py -v -k "metal or gold"`
Expected: FAIL с `ImportError: cannot import name 'refresh_metal_rates'`

- [ ] **Step 3: Реализовать загрузку курсов металлов**

Дописать в `backend/app/marketdata/fx.py`:

```python
MOEX_SOURCE = "moex"

# Металлы в денежных остатках Т-Банка приходят валютными кодами (`xau` — 10 это
# граммы). У ЦБ в XML_daily металлов нет вовсе, поэтому курс берётся с MOEX,
# где GLDRUB_TOM котируется в рублях за грамм. Серебро, платина и палладий
# добавляются сюда же, когда появятся в остатках: пока их нет, заводить
# непроверенные идентификаторы незачем.
METAL_SECIDS = {"XAU": "GLDRUB_TOM"}


class QuoteSource(Protocol):
    def quote(self, secid: str, market: str = ..., engine: str = ...) -> object: ...


def refresh_metal_rates(session: Session, client: QuoteSource, on_date: date) -> int:
    """Курсы металлов на дату, из тех же торгов MOEX, что и валюты (движок
    currency, рынок selt). Пишутся под запрошенной датой, а не под датой
    установления: у биржевой цены нет «даты установления», она торговая."""
    written = 0
    for currency, secid in METAL_SECIDS.items():
        quote = client.quote(secid, market="selt", engine="currency")
        price = getattr(quote, "price", None)
        if price is None:
            continue
        statement = insert(FxRate).values(
            currency=currency, on_date=on_date, rate=price, source=MOEX_SOURCE
        ).on_conflict_do_update(
            index_elements=[FxRate.currency, FxRate.on_date],
            set_={"rate": price, "source": MOEX_SOURCE},
        )
        session.execute(statement)
        written += 1

    session.flush()
    return written
```

- [ ] **Step 4: Запустить тесты и убедиться, что они проходят**

Run: `cd backend && uv run pytest tests/test_fx.py -v`
Expected: PASS, 7 тестов

- [ ] **Step 5: Подключить обе загрузки к планировщику**

В `backend/app/scheduler.py` добавить импорты и задачу:

```python
from app.marketdata.cbr import CbrClient
from app.marketdata.fx import refresh_fx_rates, refresh_metal_rates


def job_refresh_fx() -> None:
    with SessionLocal() as session:
        today = moscow_today()
        # Отказ ЦБ не должен мешать курсу золота и наоборот: это разные
        # источники, и половина курсов лучше, чем ни одного.
        try:
            fiat = refresh_fx_rates(session, CbrClient(), today)
        except Exception:  # noqa: BLE001 — отказ источника не роняет задачу
            logger.warning("Курсы ЦБ недоступны", exc_info=True)
            fiat = 0
        try:
            metals = refresh_metal_rates(session, MoexClient(), today)
        except Exception:  # noqa: BLE001
            logger.warning("Курс металлов с MOEX недоступен", exc_info=True)
            metals = 0
        session.commit()
        logger.info("Курсов обновлено: валют %s, металлов %s", fiat, metals)
```

и зарегистрировать её в `build_scheduler`, перед задачей снимка:

```python
    # Курсы ЦБ на следующий день публикуются днём; 12:00 МСК — время, когда
    # они уже есть, а до вечернего снимка стоимости ещё далеко.
    scheduler.add_job(
        job_refresh_fx,
        CronTrigger(hour="12", minute="10"),
        id="refresh_fx",
    )
```

В `job_daily_snapshot` перед `take_snapshot` добавить те же две загрузки, чтобы
снимок никогда не считался по вчерашним курсам:

```python
def job_daily_snapshot() -> None:
    with SessionLocal() as session:
        today = moscow_today()
        refresh_last_prices(session, MoexClient(), today)
        try:
            refresh_fx_rates(session, CbrClient(), today)
        except Exception:  # noqa: BLE001 — снимок важнее свежести курсов
            logger.warning("Курсы ЦБ недоступны, снимок пойдёт по последним известным", exc_info=True)
        try:
            refresh_metal_rates(session, MoexClient(), today)
        except Exception:  # noqa: BLE001
            logger.warning("Курс металлов недоступен", exc_info=True)
        snapshot = take_snapshot(session, today)
        session.commit()
        logger.info("Снимок за %s: %s", snapshot.on_date, snapshot.total_value)
```

- [ ] **Step 6: Дописать тест планировщика**

В `backend/tests/test_scheduler.py` дописать (рядом с существующими проверками расписания):

```python
def test_fx_job_is_registered():
    scheduler = build_scheduler()
    try:
        assert scheduler.get_job("refresh_fx") is not None
    finally:
        scheduler.shutdown(wait=False)
```

Если `build_scheduler` в существующих тестах вызывается иначе — повторить тот
же способ, что уже используется в файле, а не вводить свой.

- [ ] **Step 7: Запустить тесты**

Run: `cd backend && uv run pytest tests/test_fx.py tests/test_scheduler.py -v`
Expected: PASS

- [ ] **Step 8: Коммит**

```bash
git add backend/app/marketdata/fx.py backend/app/scheduler.py \
        backend/tests/test_fx.py backend/tests/test_scheduler.py
git commit -m "feat: курс золота с MOEX и ежедневная загрузка курсов"
```

---

### Task 3: Валюта и источник в таблице цен

**Files:**
- Modify: `backend/app/models/price.py`
- Create: `backend/alembic/versions/0011_price_currency_source.py`
- Modify: `backend/app/marketdata/service.py`
- Modify: `backend/tests/test_marketdata_service.py`

**Interfaces:**
- Consumes: `MoexQuote(price, face_value, face_unit)` из `app/marketdata/moex.py`.
- Produces: `Price.currency: str`, ключ уникальности `(instrument_id, on_date, source)`;
  `LatestPrice(close: Decimal, on_date: date, currency: str, source: str)`;
  `latest_prices(session) -> dict[int, LatestPrice]` с приоритетом источников;
  константа `TBANK_SOURCE = "tbank"` в `app/marketdata/service.py`.

- [ ] **Step 1: Написать падающий тест**

Дописать в `backend/tests/test_marketdata_service.py`:

```python
from app.marketdata.service import MOEX_SOURCE, TBANK_SOURCE


def test_moex_price_of_share_is_in_roubles(session):
    """MOEX котирует акции и фонды в рублях всегда — валюта цены не зависит от
    валюты инструмента."""
    add_instrument(session, "SBER")
    refresh_last_prices(session, FakeMoex({"SBER": Decimal("314.28")}), date(2026, 3, 12))

    stored = session.query(Price).one()
    assert stored.currency == "RUB"
    assert stored.source == MOEX_SOURCE


def test_bond_with_foreign_face_value_is_priced_in_that_currency(session):
    """Замещающая облигация котируется в процентах от номинала, номинал — в
    юанях. Раньше такая бумага оставалась неоценённой вовсе: пересчитать её без
    курсов было нельзя, а рублёвое число под видом оценки хуже честного «цены
    нет». Курсы теперь есть."""
    add_bond(session, "RU000A1054W1")
    client = FakeMoex({"RU000A1054W1": Decimal("96.92")},
                      face_values={"RU000A1054W1": (Decimal("1000"), "CNY")})

    refresh_last_prices(session, client, date(2026, 8, 9))

    stored = session.query(Price).one()
    assert stored.close == Decimal("969.2000")
    assert stored.currency == "CNY"


def test_two_sources_coexist_for_the_same_day(session):
    """Ключ уникальности включает источник: цена брокера не затирает биржевую,
    иначе выбор между ними зависел бы от того, кто записался последним."""
    instrument = add_instrument(session, "SBER")
    session.add_all([
        Price(instrument_id=instrument.id, on_date=date(2026, 8, 9),
              close=Decimal("314.28"), currency="RUB", source=MOEX_SOURCE),
        Price(instrument_id=instrument.id, on_date=date(2026, 8, 9),
              close=Decimal("315.00"), currency="RUB", source=TBANK_SOURCE),
    ])
    session.flush()

    assert session.query(Price).count() == 2


def test_moex_wins_over_broker_on_the_same_day(session):
    """Биржа — независимый источник, брокер — тот, с кем мы сверяемся. При
    равной свежести берётся биржевая цена."""
    instrument = add_instrument(session, "SBER")
    session.add_all([
        Price(instrument_id=instrument.id, on_date=date(2026, 8, 9),
              close=Decimal("314.28"), currency="RUB", source=MOEX_SOURCE),
        Price(instrument_id=instrument.id, on_date=date(2026, 8, 9),
              close=Decimal("315.00"), currency="RUB", source=TBANK_SOURCE),
    ])
    session.flush()

    latest = latest_prices(session)[instrument.id]

    assert latest.close == Decimal("314.28")
    assert latest.source == MOEX_SOURCE


def test_fresher_broker_price_beats_stale_exchange_price(session):
    """Свежесть важнее происхождения: вчерашняя биржевая цена хуже сегодняшней
    брокерской, потому что оценка отвечает на вопрос «сколько стоит сейчас»."""
    instrument = add_instrument(session, "SBER")
    session.add_all([
        Price(instrument_id=instrument.id, on_date=date(2026, 8, 8),
              close=Decimal("310.00"), currency="RUB", source=MOEX_SOURCE),
        Price(instrument_id=instrument.id, on_date=date(2026, 8, 9),
              close=Decimal("315.00"), currency="RUB", source=TBANK_SOURCE),
    ])
    session.flush()

    latest = latest_prices(session)[instrument.id]

    assert latest.close == Decimal("315.00")
    assert latest.source == TBANK_SOURCE


def test_price_of_foreign_instrument_is_no_longer_filtered_out(session):
    """Раньше цена инструмента, номинированного не в рубле, отбрасывалась при
    чтении: пересчитать её было нечем. Теперь валюта хранится у самой цены и
    пересчёт есть, поэтому отбрасывать нечего."""
    instrument = Instrument(isin="HK0000009866", ticker="9866", secid="9866",
                            kind="share", currency="HKD")
    session.add(instrument)
    session.flush()
    session.add(Price(instrument_id=instrument.id, on_date=date(2026, 8, 9),
                      close=Decimal("36.90"), currency="HKD", source=TBANK_SOURCE))
    session.flush()

    latest = latest_prices(session)[instrument.id]

    assert latest.currency == "HKD"
```

- [ ] **Step 2: Запустить тесты и убедиться, что они падают**

Run: `cd backend && uv run pytest tests/test_marketdata_service.py -v`
Expected: FAIL с `ImportError: cannot import name 'TBANK_SOURCE'`

- [ ] **Step 3: Изменить модель и написать миграцию**

В `backend/app/models/price.py` заменить содержимое класса:

```python
class Price(Base):
    __tablename__ = "price"
    # Источник входит в ключ: биржевая и брокерская цена за один день — две
    # разные величины, и затирать одну другой значит отдать выбор между ними
    # порядку записи.
    __table_args__ = (
        UniqueConstraint("instrument_id", "on_date", "source", name="uq_price_instrument_date_source"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instrument.id"), index=True)
    on_date: Mapped[date] = mapped_column(Date, index=True)
    close: Mapped[Decimal] = mapped_column(Numeric(20, 4))
    # Валюта цены — не то же самое, что валюта инструмента: замещающая
    # облигация номинирована в юанях, а в справочнике брокера числится
    # рублёвой, потому что расчёты по ней рублёвые.
    currency: Mapped[str] = mapped_column(String(3), default="RUB")
    source: Mapped[str] = mapped_column(String(16), default="moex")
```

Создать `backend/alembic/versions/0011_price_currency_source.py`:

```python
"""валюта и источник у цены

Revision ID: 0011
Revises: 0010

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0011'
down_revision: Union[str, Sequence[str], None] = '0010'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Все ранее записанные цены — биржевые и рублёвые: MOEX котирует в рублях,
    # а других источников до сих пор не было.
    op.add_column('price', sa.Column('currency', sa.String(length=3), nullable=False,
                                     server_default='RUB'))
    op.alter_column('price', 'currency', server_default=None)

    # Рублёвые котировки MOEX, записанные для инструментов, чья валюта позже
    # была исправлена по справочнику брокера на иностранную. При оценке они
    # никогда не использовались (отбрасывались фильтром при чтении), но с
    # приходом пересчёта по курсам стали бы применяться как рублёвые — и
    # занизили бы такую позицию в разы. Удаляем: терять нечего.
    op.execute("""
        DELETE FROM price
        WHERE source = 'moex'
          AND instrument_id IN (SELECT id FROM instrument WHERE upper(currency) <> 'RUB')
    """)

    op.drop_constraint('uq_price_instrument_date', 'price', type_='unique')
    op.create_unique_constraint(
        'uq_price_instrument_date_source', 'price', ['instrument_id', 'on_date', 'source']
    )


def downgrade() -> None:
    op.drop_constraint('uq_price_instrument_date_source', 'price', type_='unique')
    op.create_unique_constraint('uq_price_instrument_date', 'price', ['instrument_id', 'on_date'])
    op.drop_column('price', 'currency')
```

- [ ] **Step 4: Переписать сервис котировок**

В `backend/app/marketdata/service.py`:

Добавить рядом с `MOEX_SOURCE`:

```python
# Метка цены, полученной от брокера (GetPortfolio.currentPrice). Заполняется
# задачей 4; здесь объявлена потому, что от неё зависит приоритет источников
# при чтении.
TBANK_SOURCE = "tbank"

# Приоритет при одинаковой дате: биржа важнее брокера. Биржа — независимый
# источник, брокер — тот самый, с чьим снимком мы сверяемся; оценивать портфель
# его же числами можно, но только когда своих нет.
SOURCE_PRIORITY = {MOEX_SOURCE: 0, TBANK_SOURCE: 1}
_UNKNOWN_SOURCE_PRIORITY = 99
```

Заменить `MOEX_RUBLE_FACE_UNIT`, `_priced_in_base_currency` и `_price_in_money` на:

```python
# Коды валют номинала в ответах MOEX отличаются от ISO ровно в одном месте:
# рубль там SUR. Остальные совпадают.
FACE_UNIT_TO_ISO = {"SUR": BASE_CURRENCY}


# У MOEX запрашиваются только инструменты, номинированные в рублях. Дело не в
# пересчёте — он теперь есть, — а в том, что гонконгских и американских бумаг
# на MOEX нет вовсе: запрос по ним гарантированно возвращает пустоту и только
# засоряет журнал предупреждениями. Облигации с валютным номиналом сюда входят:
# в справочнике брокера они числятся рублёвыми (расчёты по ним рублёвые), а
# котирует их MOEX — и валюту номинала сообщает сама.
def _priced_at_moex(column) -> object:
    return func.upper(func.coalesce(column, BASE_CURRENCY)) == BASE_CURRENCY


def _price_in_money(instrument: Instrument, quote: MoexQuote) -> tuple[Decimal, str] | None:
    """Цена одной бумаги и валюта этой цены.

    Акции и фонды MOEX котирует прямо в деньгах и всегда в рублях. Облигации —
    в процентах от номинала, и номинал бывает не рублёвым: замещающие и
    юаневые выпуски. Без пересчёта из процентов облигация с номиналом 1000 ₽
    оценивалась в сотню рублей.

    Накопленный купонный доход в цену не входит: он платится сверх неё и по
    смыслу ближе к начислению, чем к стоимости бумаги.
    """
    if quote.price is None:
        return None
    if instrument.kind != kinds.BOND:
        return quote.price, BASE_CURRENCY
    if not quote.face_value:
        return None
    face_unit = (quote.face_unit or "SUR").upper()
    currency = FACE_UNIT_TO_ISO.get(face_unit, face_unit)
    return money(quote.price / Decimal("100") * quote.face_value), currency
```

В `refresh_last_prices` заменить фильтр и запись:

```python
    instruments = session.execute(
        select(Instrument).where(
            Instrument.secid.is_not(None),
            _priced_at_moex(Instrument.currency),
        )
    ).scalars().all()
```

```python
        priced = _price_in_money(instrument, quote)
        if priced is None:
            continue
        price, currency = priced

        statement = insert(Price).values(
            instrument_id=instrument.id, on_date=on_date, close=price,
            currency=currency, source=MOEX_SOURCE,
        ).on_conflict_do_update(
            index_elements=[Price.instrument_id, Price.on_date, Price.source],
            set_={"close": price, "currency": currency},
        )
```

Заменить `LatestPrice` и `latest_prices`:

```python
@dataclass(frozen=True)
class LatestPrice:
    """Последняя пригодная котировка инструмента: цена, её валюта, дата и
    источник. Всё четыре поля отдаются одним проходом по таблице цен —
    аналитике нужны все, а раздельные запросы за ними означали бы несколько
    одинаковых проходов на каждый показ дашборда."""

    close: Decimal
    on_date: date
    currency: str
    source: str


def latest_prices(session: Session) -> dict[int, LatestPrice]:
    """Самая свежая цена по каждому инструменту.

    Свежесть решает первой, происхождение — вторым: вчерашняя биржевая цена
    хуже сегодняшней брокерской, потому что вопрос стоит «сколько стоит
    сейчас». При равной дате выигрывает биржа (SOURCE_PRIORITY).

    Фильтра по валюте здесь больше нет: валюта хранится у самой цены, и
    пересчёт в рубли делает оценка (app/analytics/valuation.py).
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

Импорт `case` добавить к существующему: `from sqlalchemy import case, func, or_, select`
— и убрать `or_`, если он больше нигде не используется в файле.

- [ ] **Step 5: Запустить тесты**

Run: `cd backend && uv run pytest tests/test_marketdata_service.py tests/test_migrations.py -v`
Expected: PASS. Существующие тесты, проверявшие отбрасывание рублёвых цен у
валютных инструментов, теперь описывают снятое поведение — их нужно заменить
тестом `test_price_of_foreign_instrument_is_no_longer_filtered_out` из шага 1,
а не «починить» подгонкой.

- [ ] **Step 6: Прогнать весь бэкенд**

Run: `cd backend && uv run pytest`
Expected: PASS. Падения ожидаются в тестах аналитики, которые считают, что
валютные позиции не оцениваются, — их правит задача 7. Если падает что-то ещё,
разобраться до коммита.

- [ ] **Step 7: Коммит**

```bash
git add backend/app/models/price.py backend/app/marketdata/service.py \
        backend/alembic/versions/0011_price_currency_source.py \
        backend/tests/test_marketdata_service.py
git commit -m "feat: валюта и источник у котировки, приоритет биржи над брокером"
```

---

### Task 4: Цены брокера как запасной источник

**Files:**
- Modify: `backend/app/connectors/base.py`
- Modify: `backend/app/connectors/tbank/connector.py`
- Create: `backend/app/marketdata/broker_prices.py`
- Modify: `backend/app/sync/service.py`
- Modify: `backend/tests/test_tbank_connector.py`
- Create: `backend/tests/test_broker_prices.py`

**Interfaces:**
- Consumes: `TBankClient.get_portfolio(account_id) -> list[dict]`;
  `to_money`, `to_quantity` из `app/connectors/tbank/quotation.py`;
  `TBANK_SOURCE` из `app/marketdata/service.py`.
- Produces: `BrokerPrice(isin: str, price: Decimal, currency: str)` в
  `app/connectors/base.py`; `BrokerConnector.fetch_prices(account_external_id) -> list[BrokerPrice]`;
  `store_broker_prices(session, prices: list[BrokerPrice], on_date: date) -> int`
  в `app/marketdata/broker_prices.py`.

- [ ] **Step 1: Написать падающий тест коннектора**

Дописать в `backend/tests/test_tbank_connector.py` (использовать тот же фейковый
клиент, что уже есть в файле; если у него нет метода `get_portfolio`, добавить
его по образцу существующих):

```python
def test_fetch_prices_returns_price_in_instrument_currency():
    """GetPortfolio отдаёт currentPrice в валюте бумаги: гонконгская акция — в
    гонконгских долларах, замещающая облигация — в юанях. Это единственный
    источник цены для того, чего MOEX не котирует."""
    client = FakeClient(
        portfolio=[
            {"figi": "BBG015PB0HH9", "instrumentType": "share",
             "quantity": {"units": "40", "nano": 0},
             "currentPrice": {"currency": "hkd", "units": "36", "nano": 900000000}},
        ],
        instruments={"BBG015PB0HH9": {"isin": "HK0000009866", "ticker": "9866",
                                      "currency": "hkd", "name": "Nio"}},
    )
    connector = build_connector(client)

    prices = connector.fetch_prices("acc-1")

    assert prices == [BrokerPrice(isin="HK0000009866", price=Decimal("36.9000"), currency="HKD")]


def test_fetch_prices_skips_position_without_price():
    """Нулевая цена без валюты — то, что брокер присылает по псевдо-позиции
    закрытого счёта. Записать её значит обнулить оценку бумаги."""
    client = FakeClient(
        portfolio=[
            {"figi": "RUB000UTSTOM", "instrumentType": "currency",
             "quantity": {"units": "0", "nano": 0},
             "currentPrice": {"currency": "", "units": "0", "nano": 0}},
        ],
        instruments={},
    )

    assert build_connector(client).fetch_prices("acc-1") == []
```

`build_connector` и `FakeClient` — уже существующие в файле помощники; если их
имена другие, использовать те, что есть, и не заводить дубли.

- [ ] **Step 2: Запустить тест и убедиться, что он падает**

Run: `cd backend && uv run pytest tests/test_tbank_connector.py -v -k fetch_prices`
Expected: FAIL с `AttributeError: 'TBankConnector' object has no attribute 'fetch_prices'`

- [ ] **Step 3: Расширить протокол и коннектор**

В `backend/app/connectors/base.py` добавить после `BrokerPosition`:

```python
@dataclass(frozen=True)
class BrokerPrice:
    """Цена одной бумаги по данным брокера, в валюте бумаги.

    Запасной источник оценки: у брокера есть цена на всё, что у него лежит,
    включая бумаги, которых нет на MOEX. Независимой такая оценка не является —
    брокер тот же, с чьим снимком мы сверяемся, — поэтому источник цены
    хранится вместе с ней и виден на экране.
    """

    isin: str
    price: Decimal
    currency: str
```

и в протокол `BrokerConnector`:

```python
    def fetch_prices(self, account_external_id: str) -> list[BrokerPrice]: ...
```

В `backend/app/connectors/tbank/connector.py` добавить метод после `fetch_positions`:

```python
    def fetch_prices(self, account_external_id: str) -> list[BrokerPrice]:
        """Текущие цены бумаг счёта по данным брокера.

        Берётся из того же GetPortfolio, что и позиции. Цена приходит в валюте
        бумаги (`hkd`, `usd`, `cny`, `rub`), у облигаций — деньгами за штуку, а
        не процентом от номинала, в отличие от MOEX.
        """
        raw_positions = self._client.get_portfolio(account_external_id)
        figis = {item.get("figi") for item in raw_positions if item.get("figi")}
        instruments = self._resolve_instruments(figis)

        prices: list[BrokerPrice] = []
        for item in raw_positions:
            figi = item.get("figi")
            instrument = instruments.get(figi) if figi else None
            if instrument is None or not instrument.isin:
                continue
            raw_price = item.get("currentPrice") or {}
            currency = (raw_price.get("currency") or "").upper()
            price = to_money(raw_price)
            # Пустая валюта — признак псевдо-позиции (рублёвый остаток закрытого
            # счёта приходит именно так), нулевая цена — отсутствие оценки.
            # Записать такое значит обнулить стоимость бумаги.
            if not currency or price == 0:
                continue
            prices.append(BrokerPrice(isin=instrument.isin, price=price, currency=currency))
        return prices
```

Импорт дополнить: `from app.connectors.base import BrokerAccount, BrokerInstrument, BrokerPosition, BrokerPrice`
и `from app.connectors.tbank.quotation import to_money, to_quantity`.

- [ ] **Step 4: Запустить тест коннектора**

Run: `cd backend && uv run pytest tests/test_tbank_connector.py -v`
Expected: PASS

- [ ] **Step 5: Написать падающий тест записи цен**

Создать `backend/tests/test_broker_prices.py`:

```python
from datetime import date
from decimal import Decimal

from app.connectors.base import BrokerPrice
from app.marketdata.broker_prices import store_broker_prices
from app.marketdata.service import MOEX_SOURCE, TBANK_SOURCE
from app.models import Instrument, Price


def add_instrument(session, isin: str, currency: str = "RUB") -> Instrument:
    instrument = Instrument(isin=isin, ticker=isin, secid=isin, kind="share", currency=currency)
    session.add(instrument)
    session.flush()
    return instrument


def test_stores_price_with_broker_source(session):
    add_instrument(session, "HK0000009866", currency="HKD")

    written = store_broker_prices(
        session,
        [BrokerPrice(isin="HK0000009866", price=Decimal("36.90"), currency="HKD")],
        date(2026, 8, 9),
    )

    assert written == 1
    stored = session.query(Price).one()
    assert (stored.close, stored.currency, stored.source) == (Decimal("36.9000"), "HKD", TBANK_SOURCE)


def test_unknown_isin_is_skipped(session):
    """Инструмента нет в справочнике — цену не к чему привязать. Заводить
    инструмент из цены нельзя: справочные сведения о нём приходят с операциями,
    и пустая заготовка навсегда осталась бы «видом неизвестно»."""
    written = store_broker_prices(
        session, [BrokerPrice(isin="XX0000000000", price=Decimal("1"), currency="RUB")],
        date(2026, 8, 9),
    )

    assert written == 0
    assert session.query(Price).count() == 0


def test_repeated_run_updates_the_same_row(session):
    instrument = add_instrument(session, "HK0000009866", currency="HKD")
    store_broker_prices(session, [BrokerPrice(isin="HK0000009866", price=Decimal("36.90"),
                                              currency="HKD")], date(2026, 8, 9))
    store_broker_prices(session, [BrokerPrice(isin="HK0000009866", price=Decimal("37.50"),
                                              currency="HKD")], date(2026, 8, 9))

    stored = session.query(Price).filter(Price.instrument_id == instrument.id).all()
    assert len(stored) == 1
    assert stored[0].close == Decimal("37.5000")


def test_broker_price_does_not_touch_exchange_price(session):
    """Две записи за один день от разных источников сосуществуют — выбор между
    ними делает чтение, а не порядок записи."""
    instrument = add_instrument(session, "RU0009029540")
    session.add(Price(instrument_id=instrument.id, on_date=date(2026, 8, 9),
                      close=Decimal("314.28"), currency="RUB", source=MOEX_SOURCE))
    session.flush()

    store_broker_prices(session, [BrokerPrice(isin="RU0009029540", price=Decimal("315.00"),
                                              currency="RUB")], date(2026, 8, 9))

    assert session.query(Price).count() == 2
```

- [ ] **Step 6: Запустить тест и убедиться, что он падает**

Run: `cd backend && uv run pytest tests/test_broker_prices.py -v`
Expected: FAIL с `ModuleNotFoundError: No module named 'app.marketdata.broker_prices'`

- [ ] **Step 7: Реализовать запись цен брокера**

Создать `backend/app/marketdata/broker_prices.py`:

```python
from datetime import date

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.connectors.base import BrokerPrice
from app.marketdata.service import TBANK_SOURCE
from app.models import Instrument, Price


def store_broker_prices(session: Session, prices: list[BrokerPrice], on_date: date) -> int:
    """Записывает цены брокера в таблицу котировок под источником `tbank`.

    Инструменты ищутся одним запросом по всем ISIN пачки: цен на счёте до
    полусотни, а запрос на каждую превратил бы синхронизацию в сотни round-trip
    к базе.
    """
    if not prices:
        return 0

    isins = {item.isin for item in prices}
    instrument_ids = {
        isin: instrument_id
        for instrument_id, isin in session.execute(
            select(Instrument.id, Instrument.isin).where(Instrument.isin.in_(isins))
        ).all()
    }

    written = 0
    for item in prices:
        instrument_id = instrument_ids.get(item.isin)
        # Инструмента нет в справочнике — привязать цену не к чему. Заводить
        # его здесь нельзя: вид, название и валюта приходят с операциями, и
        # заготовка из одной цены осталась бы навсегда «видом неизвестно».
        if instrument_id is None:
            continue
        statement = insert(Price).values(
            instrument_id=instrument_id, on_date=on_date,
            close=item.price, currency=item.currency, source=TBANK_SOURCE,
        ).on_conflict_do_update(
            index_elements=[Price.instrument_id, Price.on_date, Price.source],
            set_={"close": item.price, "currency": item.currency},
        )
        session.execute(statement)
        written += 1

    session.flush()
    return written
```

- [ ] **Step 8: Подключить к синхронизации**

В `backend/app/sync/service.py` в `sync_broker`, внутри `try`, сразу после
`rebuild_positions(session, account)`:

```python
            # Цены брокера — запасной источник оценки для того, чего нет на
            # MOEX. Пишутся под московской календарной датой, той же, под
            # которой пишутся биржевые котировки и снимок стоимости.
            store_broker_prices(session, connector.fetch_prices(account.external_id), moscow_today())
```

Импорты дополнить: `from app.marketdata.broker_prices import store_broker_prices`
и `from app.timeutils import moscow_today`.

- [ ] **Step 9: Дописать тест синхронизации**

В `backend/tests/test_sync_service.py` — у фейкового коннектора файла добавить
`fetch_prices`, возвращающий пустой список по умолчанию, и тест:

```python
def test_sync_stores_broker_prices(session):
    """Цена брокера доезжает до таблицы котировок тем же прогоном, что и
    операции: иначе новая бумага оставалась бы неоценённой до ближайшего
    обновления котировок."""
    connector = FakeConnector(
        accounts=[BrokerAccount(external_id="acc-1", name="Счёт", kind="brokerage")],
        operations=[...],  # операция по инструменту с ISIN RU0009029540, как в соседних тестах
        positions=[],
        prices=[BrokerPrice(isin="RU0009029540", price=Decimal("315.00"), currency="RUB")],
    )

    sync_broker(session, connector)

    stored = session.query(Price).one()
    assert (stored.close, stored.source) == (Decimal("315.0000"), "tbank")
```

Операцию взять ровно ту же, что уже строят соседние тесты файла, — не
изобретать новую форму.

- [ ] **Step 10: Запустить тесты**

Run: `cd backend && uv run pytest tests/test_broker_prices.py tests/test_sync_service.py tests/test_tbank_connector.py -v`
Expected: PASS

- [ ] **Step 11: Коммит**

```bash
git add backend/app/connectors/base.py backend/app/connectors/tbank/connector.py \
        backend/app/marketdata/broker_prices.py backend/app/sync/service.py \
        backend/tests/test_broker_prices.py backend/tests/test_sync_service.py \
        backend/tests/test_tbank_connector.py
git commit -m "feat: цены брокера как запасной источник оценки"
```

---

### Task 5: Денежные остатки счетов

**Files:**
- Create: `backend/app/models/cash_balance.py`
- Create: `backend/alembic/versions/0012_cash_balance.py`
- Create: `backend/app/accounts/cash.py`
- Create: `backend/tests/test_cash.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/connectors/base.py`
- Modify: `backend/app/connectors/tbank/client.py`
- Modify: `backend/app/connectors/tbank/connector.py`
- Modify: `backend/app/sync/service.py`
- Modify: `backend/tests/test_tbank_connector.py`

**Interfaces:**
- Consumes: `TBankClient._post` (через новый метод `get_positions`).
- Produces: `BrokerCash(currency: str, amount: Decimal, blocked: Decimal)` в
  `app/connectors/base.py`; `BrokerConnector.fetch_cash(account_external_id) -> list[BrokerCash]`;
  модель `CashBalance(account_id, currency, amount, blocked, updated_at)`;
  `store_cash(session, account, balances) -> int` в `app/accounts/cash.py`.

- [ ] **Step 1: Написать падающий тест коннектора**

Дописать в `backend/tests/test_tbank_connector.py`:

```python
def test_fetch_cash_reads_money_and_blocked():
    """Денежные остатки лежат в GetPositions.money по валютам. Золото приходит
    там же валютным кодом xau — граммами, и в брокерский итог по счёту оно
    входит наравне с валютами."""
    client = FakeClient(positions_response={
        "money": [
            {"currency": "rub", "units": "20782", "nano": 270000000},
            {"currency": "usd", "units": "0", "nano": 380000000},
            {"currency": "xau", "units": "10", "nano": 0},
        ],
        "blocked": [{"currency": "rub", "units": "500", "nano": 0}],
        "securities": [],
    })

    cash = build_connector(client).fetch_cash("acc-1")

    assert sorted(cash, key=lambda c: c.currency) == [
        BrokerCash(currency="RUB", amount=Decimal("20782.2700"), blocked=Decimal("500.0000")),
        BrokerCash(currency="USD", amount=Decimal("0.3800"), blocked=Decimal("0")),
        BrokerCash(currency="XAU", amount=Decimal("10.0000"), blocked=Decimal("0")),
    ]


def test_fetch_cash_keeps_negative_balance():
    """Минус на счёте — не ошибка разбора: на «Копилке» владельца рублёвый
    остаток равен −3571,34. Обнулить его значит завысить капитал."""
    client = FakeClient(positions_response={
        "money": [{"currency": "rub", "units": "-3571", "nano": -340000000}],
        "blocked": [], "securities": [],
    })

    assert build_connector(client).fetch_cash("acc-1") == [
        BrokerCash(currency="RUB", amount=Decimal("-3571.3400"), blocked=Decimal("0"))
    ]


def test_fetch_cash_returns_empty_when_account_has_no_positions_endpoint():
    """GetPositions отвечает 404 «Account not found» для счёта типа
    ACCOUNT_TYPE_DFA (у владельца это «Смарт-счет»). Один такой счёт не должен
    ронять синхронизацию остальных — денег на нём просто нет."""
    client = FakeClient(positions_error=httpx.HTTPStatusError(
        "404", request=httpx.Request("POST", "http://x"),
        response=httpx.Response(404, request=httpx.Request("POST", "http://x")),
    ))

    assert build_connector(client).fetch_cash("acc-1") == []
```

- [ ] **Step 2: Запустить тест и убедиться, что он падает**

Run: `cd backend && uv run pytest tests/test_tbank_connector.py -v -k fetch_cash`
Expected: FAIL с `AttributeError: 'TBankConnector' object has no attribute 'fetch_cash'`

- [ ] **Step 3: Реализовать чтение остатков**

В `backend/app/connectors/tbank/client.py` добавить метод после `get_portfolio`:

```python
    def get_positions(self, account_id: str) -> dict:
        """OperationsService/GetPositions — денежные остатки и заблокированные
        количества бумаг.

        Это не то же самое, что GetPortfolio: там позиции с оценкой, здесь
        остатки. Заблокированная часть есть только здесь, а деньги здесь
        приходят массивом по валютам, тогда как в GetPortfolio они размазаны по
        псевдо-инструментам (RUB000UTSTOM и подобным)."""
        return self._post(OPERATIONS_SERVICE, "GetPositions", {"accountId": account_id})
```

В `backend/app/connectors/base.py` добавить:

```python
@dataclass(frozen=True)
class BrokerCash:
    """Денежный остаток счёта в одной валюте.

    `blocked` — часть остатка, недоступная к распоряжению (залог, расчёты по
    сделке). Хранится отдельно, но входит в `amount`: капитал она не покидает,
    а вот распорядиться ею нельзя.

    Валютой брокер называет и драгоценные металлы: золото приходит кодом `XAU`
    и измеряется граммами. Для оценки это такая же валюта, у которой есть курс
    к рублю, — только берётся он не у ЦБ, а с MOEX.
    """

    currency: str
    amount: Decimal
    blocked: Decimal
```

и в протокол `BrokerConnector`:

```python
    def fetch_cash(self, account_external_id: str) -> list[BrokerCash]: ...
```

В `backend/app/connectors/tbank/connector.py`:

```python
# Коды ошибок HTTP, при которых счёт просто не поддерживает вызов, а не сломан.
# GetPositions отвечает 404 «Account not found» для счетов типа
# ACCOUNT_TYPE_DFA (цифровые финансовые активы) — денег и бумаг в привычном
# смысле там нет, и падать из-за этого всей синхронизацией незачем.
_NO_SUCH_ACCOUNT = 404


    def fetch_cash(self, account_external_id: str) -> list[BrokerCash]:
        payload = self._get_positions(account_external_id)
        if payload is None:
            return []

        blocked_by_currency: dict[str, Decimal] = {}
        for item in payload.get("blocked") or []:
            currency = (item.get("currency") or "").upper()
            if currency:
                blocked_by_currency[currency] = to_money(item)

        balances: list[BrokerCash] = []
        for item in payload.get("money") or []:
            currency = (item.get("currency") or "").upper()
            if not currency:
                continue
            balances.append(BrokerCash(
                currency=currency,
                amount=to_money(item),
                blocked=blocked_by_currency.get(currency, money("0")),
            ))
        return balances

    def _get_positions(self, account_external_id: str) -> dict | None:
        """Ответ GetPositions либо None, если счёт этот вызов не поддерживает."""
        try:
            return self._client.get_positions(account_external_id)
        except httpx.HTTPStatusError as error:
            if error.response.status_code != _NO_SUCH_ACCOUNT:
                raise
            logger.info(
                "GetPositions недоступен для счёта %s (счёт особого типа) — "
                "остатки и блокировки по нему не читаются",
                account_external_id,
            )
            return None
```

Импорты дополнить: `from app.connectors.base import ..., BrokerCash` и
`from app.money import money`.

- [ ] **Step 4: Запустить тесты коннектора**

Run: `cd backend && uv run pytest tests/test_tbank_connector.py -v`
Expected: PASS

- [ ] **Step 5: Написать падающий тест хранения остатков**

Создать `backend/tests/test_cash.py`:

```python
from decimal import Decimal

from app.accounts.cash import cash_by_account, store_cash
from app.connectors.base import BrokerCash
from app.models import Account, CashBalance


def add_account(session, external_id: str = "acc-1") -> Account:
    account = Account(broker="tbank", kind="brokerage", external_id=external_id,
                      name="Счёт", currency="RUB")
    session.add(account)
    session.flush()
    return account


def test_stores_balances_per_currency(session):
    account = add_account(session)

    written = store_cash(session, account, [
        BrokerCash(currency="RUB", amount=Decimal("20782.27"), blocked=Decimal("0")),
        BrokerCash(currency="XAU", amount=Decimal("10"), blocked=Decimal("0")),
    ])

    assert written == 2
    stored = session.query(CashBalance).order_by(CashBalance.currency).all()
    assert [(b.currency, b.amount) for b in stored] == [
        ("RUB", Decimal("20782.2700")), ("XAU", Decimal("10.0000"))
    ]


def test_currency_gone_from_broker_is_removed(session):
    """Остаток — снимок, а не журнал: валюта, которой у брокера больше нет,
    обязана исчезнуть, иначе проданная валюта вечно висит в капитале."""
    account = add_account(session)
    store_cash(session, account, [
        BrokerCash(currency="RUB", amount=Decimal("100"), blocked=Decimal("0")),
        BrokerCash(currency="EUR", amount=Decimal("1"), blocked=Decimal("0")),
    ])

    store_cash(session, account, [BrokerCash(currency="RUB", amount=Decimal("100"),
                                             blocked=Decimal("0"))])

    assert [b.currency for b in session.query(CashBalance).all()] == ["RUB"]


def test_balances_of_other_accounts_are_untouched(session):
    first = add_account(session, "acc-1")
    second = add_account(session, "acc-2")
    store_cash(session, first, [BrokerCash(currency="RUB", amount=Decimal("100"),
                                           blocked=Decimal("0"))])
    store_cash(session, second, [BrokerCash(currency="USD", amount=Decimal("5"),
                                            blocked=Decimal("0"))])

    store_cash(session, first, [])

    assert [(b.account_id, b.currency) for b in session.query(CashBalance).all()] == [
        (second.id, "USD")
    ]


def test_cash_by_account_groups_balances(session):
    account = add_account(session)
    store_cash(session, account, [
        BrokerCash(currency="RUB", amount=Decimal("100"), blocked=Decimal("10")),
        BrokerCash(currency="USD", amount=Decimal("5"), blocked=Decimal("0")),
    ])

    grouped = cash_by_account(session)

    assert grouped[account.id] == {"RUB": Decimal("100.0000"), "USD": Decimal("5.0000")}
```

- [ ] **Step 6: Запустить тест и убедиться, что он падает**

Run: `cd backend && uv run pytest tests/test_cash.py -v`
Expected: FAIL с `ModuleNotFoundError: No module named 'app.accounts.cash'`

- [ ] **Step 7: Реализовать модель, миграцию и сервис**

Создать `backend/app/models/cash_balance.py`:

```python
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class CashBalance(Base):
    """Денежный остаток счёта в одной валюте — снимок брокера, не производная
    журнала.

    Журнал остаётся источником истины по позициям, но денег он пока не считает:
    для этого в нём должны быть все до единого движения средств, включая
    пополнения и выводы, а их полноту мы не проверяли. Пока остаток берётся у
    брокера как есть — так же, как берётся его снимок позиций для сверки.
    """

    __tablename__ = "cash_balance"
    __table_args__ = (
        UniqueConstraint("account_id", "currency", name="uq_cash_balance_account_currency"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("account.id"), index=True)
    currency: Mapped[str] = mapped_column(String(3))
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 4))
    # Часть остатка, недоступная к распоряжению. Входит в amount, не прибавляется.
    blocked: Mapped[Decimal] = mapped_column(Numeric(20, 4), default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
```

Дописать в `backend/app/models/__init__.py`: `from app.models.cash_balance import CashBalance`
и `"CashBalance",` в `__all__` (после `"Base"`).

Создать `backend/alembic/versions/0012_cash_balance.py`:

```python
"""cash balance

Revision ID: 0012
Revises: 0011

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0012'
down_revision: Union[str, Sequence[str], None] = '0011'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'cash_balance',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('account_id', sa.Integer(), nullable=False),
        sa.Column('currency', sa.String(length=3), nullable=False),
        sa.Column('amount', sa.Numeric(precision=20, scale=4), nullable=False),
        sa.Column('blocked', sa.Numeric(precision=20, scale=4), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'),
                  nullable=False),
        sa.ForeignKeyConstraint(['account_id'], ['account.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('account_id', 'currency', name='uq_cash_balance_account_currency'),
    )
    op.create_index(op.f('ix_cash_balance_account_id'), 'cash_balance', ['account_id'],
                    unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_cash_balance_account_id'), table_name='cash_balance')
    op.drop_table('cash_balance')
```

Создать `backend/app/accounts/cash.py`:

```python
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.connectors.base import BrokerCash
from app.models import Account, CashBalance


def store_cash(session: Session, account: Account, balances: list[BrokerCash]) -> int:
    """Заменяет остатки счёта присланными брокером.

    Именно заменяет, а не дополняет: остаток — снимок на момент времени.
    Валюта, которой у брокера больше нет, должна исчезнуть, иначе проданные
    доллары вечно висят в капитале. Удаление и вставка идут в транзакции
    вызывающего — как и пересборка позиций, чтобы читатель никогда не увидел
    счёт без денег в середине обновления.
    """
    session.execute(delete(CashBalance).where(CashBalance.account_id == account.id))

    for item in balances:
        session.add(CashBalance(
            account_id=account.id,
            currency=item.currency,
            amount=item.amount,
            blocked=item.blocked,
        ))

    session.flush()
    return len(balances)


def cash_by_account(session: Session) -> dict[int, dict[str, Decimal]]:
    """Остатки всех счетов: идентификатор счёта → валюта → сумма."""
    result: dict[int, dict[str, Decimal]] = {}
    for balance in session.execute(select(CashBalance)).scalars():
        result.setdefault(balance.account_id, {})[balance.currency] = balance.amount
    return result
```

- [ ] **Step 8: Подключить к синхронизации**

В `backend/app/sync/service.py`, в `sync_broker`, сразу после записи цен из
задачи 4:

```python
            store_cash(session, account, connector.fetch_cash(account.external_id))
```

Импорт: `from app.accounts.cash import store_cash`.

- [ ] **Step 9: Запустить тесты**

Run: `cd backend && uv run pytest tests/test_cash.py tests/test_sync_service.py tests/test_migrations.py -v`
Expected: PASS. Фейковый коннектор в `test_sync_service.py` дополнить методом
`fetch_cash`, возвращающим пустой список.

- [ ] **Step 10: Коммит**

```bash
git add backend/app/models/cash_balance.py backend/app/models/__init__.py \
        backend/app/accounts/cash.py backend/alembic/versions/0012_cash_balance.py \
        backend/app/connectors/base.py backend/app/connectors/tbank/client.py \
        backend/app/connectors/tbank/connector.py backend/app/sync/service.py \
        backend/tests/test_cash.py backend/tests/test_tbank_connector.py \
        backend/tests/test_sync_service.py
git commit -m "feat: денежные остатки счетов из GetPositions"
```

---

### Task 6: Заблокированное количество на счёте

**Files:**
- Create: `backend/app/models/broker_holding.py`
- Create: `backend/alembic/versions/0013_broker_holding.py`
- Create: `backend/tests/test_broker_holding.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/connectors/base.py`
- Modify: `backend/app/connectors/tbank/connector.py`
- Modify: `backend/app/sync/service.py`
- Modify: `backend/tests/test_tbank_connector.py`

**Interfaces:**
- Consumes: `BrokerPosition` (расширяется полем `blocked`), `_get_positions`
  из задачи 5.
- Produces: `BrokerPosition(isin, ticker, quantity, blocked)`; модель
  `BrokerHolding(account_id, isin, instrument_id, quantity, blocked, as_of)`;
  `store_holdings(session, account, positions) -> int` и
  `blocked_by_instrument(session) -> dict[tuple[int, int], Decimal]` (ключ —
  пара «счёт, инструмент») в `app/sync/holdings.py`.

- [ ] **Step 1: Написать падающий тест коннектора**

Дописать в `backend/tests/test_tbank_connector.py`:

```python
def test_position_carries_blocked_quantity():
    """У владельца две заблокированные позиции: HK0000123577 с balance=0 и
    blocked=92, HK0000051877 с balance=0 и blocked=79. Проверено на живом API:
    balance + blocked в точности равно quantity из GetPortfolio на всех 43
    бумагах счёта — значит блокировка это часть количества, а не добавка."""
    client = FakeClient(
        portfolio=[{"figi": "TCS000123577", "instrumentType": "etf",
                    "quantity": {"units": "92", "nano": 0},
                    "currentPrice": {"currency": "rub", "units": "100", "nano": 0}}],
        instruments={"TCS000123577": {"isin": "HK0000123577", "ticker": "HK0000123577",
                                      "currency": "rub", "name": "Фонд"}},
        positions_response={
            "money": [], "blocked": [],
            "securities": [{"figi": "TCS000123577", "balance": "0", "blocked": "92",
                            "ticker": "HK0000123577", "instrumentType": "etf",
                            "exchangeBlocked": False}],
        },
    )

    positions = build_connector(client).fetch_positions("acc-1")

    assert positions == [BrokerPosition(isin="HK0000123577", ticker="HK0000123577",
                                        quantity=Decimal("92"), blocked=Decimal("92"))]


def test_blocked_defaults_to_zero_when_positions_call_unavailable():
    """Счёт типа ACCOUNT_TYPE_DFA не отвечает на GetPositions. Позиции при этом
    читаются из GetPortfolio как раньше — просто без сведений о блокировке."""
    client = FakeClient(
        portfolio=[{"figi": "BBG004730N88", "instrumentType": "share",
                    "quantity": {"units": "10", "nano": 0},
                    "currentPrice": {"currency": "rub", "units": "300", "nano": 0}}],
        instruments={"BBG004730N88": {"isin": "RU0009029540", "ticker": "SBER",
                                      "currency": "rub", "name": "Сбербанк"}},
        positions_error=httpx.HTTPStatusError(
            "404", request=httpx.Request("POST", "http://x"),
            response=httpx.Response(404, request=httpx.Request("POST", "http://x"))),
    )

    assert build_connector(client).fetch_positions("acc-1") == [
        BrokerPosition(isin="RU0009029540", ticker="SBER", quantity=Decimal("10"),
                       blocked=Decimal("0"))
    ]
```

- [ ] **Step 2: Запустить тест и убедиться, что он падает**

Run: `cd backend && uv run pytest tests/test_tbank_connector.py -v -k blocked`
Expected: FAIL — `BrokerPosition` не принимает `blocked`

- [ ] **Step 3: Расширить BrokerPosition и коннектор**

В `backend/app/connectors/base.py`:

```python
@dataclass(frozen=True)
class BrokerPosition:
    isin: str
    ticker: str | None
    quantity: Decimal
    # Часть количества, заблокированная брокером или биржей: заморозка после
    # 2022 года, залог, расчёты по сделке. Это доля от quantity, а не добавка к
    # нему — проверено на живом API: balance + blocked из GetPositions в
    # точности равно quantity из GetPortfolio. Ноль, если брокер сведений о
    # блокировках не даёт.
    blocked: Decimal = Decimal("0")
```

В `backend/app/connectors/tbank/connector.py` переписать `fetch_positions`:

```python
    def fetch_positions(self, account_external_id: str) -> list[BrokerPosition]:
        raw_positions = self._client.get_portfolio(account_external_id)
        figis = {item.get("figi") for item in raw_positions if item.get("figi")}
        instruments = self._resolve_instruments(figis)
        blocked_by_figi = self._blocked_by_figi(account_external_id)

        positions = []
        for item in raw_positions:
            figi = item.get("figi")
            if not figi:
                continue
            qty = to_quantity(item.get("quantity"))
            if qty is None:
                # Отсутствующий или битый объект количества — пропускаем именно
                # эту позицию, а не роняем весь вызов: остальные позиции счёта
                # валидны и должны дойти до журнала.
                continue
            instrument = instruments.get(figi)
            if instrument is None or not instrument.isin:
                continue
            ticker = item.get("ticker") or instrument.ticker
            positions.append(BrokerPosition(
                isin=instrument.isin, ticker=ticker, quantity=qty,
                blocked=blocked_by_figi.get(figi, quantity("0")),
            ))
        return positions

    def _blocked_by_figi(self, account_external_id: str) -> dict[str, Decimal]:
        """Заблокированные количества бумаг счёта, ключ — FIGI.

        Сведения есть только в GetPositions; счёт, который этого вызова не
        поддерживает, отдаёт пустое отображение, и позиции читаются как раньше,
        просто без блокировок."""
        payload = self._get_positions(account_external_id)
        if payload is None:
            return {}

        result: dict[str, Decimal] = {}
        for item in payload.get("securities") or []:
            figi = item.get("figi")
            raw_blocked = item.get("blocked")
            if not figi or raw_blocked in (None, "", "0"):
                continue
            result[figi] = quantity(str(raw_blocked))
        return result
```

Импорт дополнить: `from app.money import money, quantity`.

- [ ] **Step 4: Запустить тесты коннектора**

Run: `cd backend && uv run pytest tests/test_tbank_connector.py -v`
Expected: PASS

- [ ] **Step 5: Написать падающий тест хранения снимка**

Создать `backend/tests/test_broker_holding.py`:

```python
from decimal import Decimal

from app.connectors.base import BrokerPosition
from app.models import Account, BrokerHolding, Instrument
from app.sync.holdings import blocked_by_instrument, store_holdings


def add_account(session) -> Account:
    account = Account(broker="tbank", kind="brokerage", external_id="acc-1",
                      name="Счёт", currency="RUB")
    session.add(account)
    session.flush()
    return account


def add_instrument(session, isin: str) -> Instrument:
    instrument = Instrument(isin=isin, ticker=isin, secid=isin, kind="etf", currency="RUB")
    session.add(instrument)
    session.flush()
    return instrument


def test_stores_snapshot_with_blocked_part(session):
    account = add_account(session)
    instrument = add_instrument(session, "HK0000123577")

    written = store_holdings(session, account, [
        BrokerPosition(isin="HK0000123577", ticker="HK0000123577",
                       quantity=Decimal("92"), blocked=Decimal("92")),
    ])

    assert written == 1
    holding = session.query(BrokerHolding).one()
    assert (holding.quantity, holding.blocked, holding.instrument_id) == (
        Decimal("92.00000000"), Decimal("92.00000000"), instrument.id
    )


def test_holding_of_unknown_instrument_is_kept_without_link(session):
    """Заблокированный фонд под новым ISIN в справочнике может отсутствовать —
    он появился у брокера в результате конвертации, а в журнале его нет. Сумму
    и факт блокировки терять нельзя: именно они объясняют расхождение."""
    account = add_account(session)

    store_holdings(session, account, [
        BrokerPosition(isin="HK0000051877", ticker="HK0000051877",
                       quantity=Decimal("79"), blocked=Decimal("79")),
    ])

    holding = session.query(BrokerHolding).one()
    assert holding.instrument_id is None
    assert holding.isin == "HK0000051877"


def test_snapshot_replaces_previous_one(session):
    account = add_account(session)
    add_instrument(session, "RU0009029540")
    store_holdings(session, account, [
        BrokerPosition(isin="RU0009029540", ticker="SBER", quantity=Decimal("10"),
                       blocked=Decimal("0")),
    ])

    store_holdings(session, account, [])

    assert session.query(BrokerHolding).count() == 0


def test_blocked_by_instrument_skips_unlinked_and_zero(session):
    account = add_account(session)
    linked = add_instrument(session, "HK0000123577")
    add_instrument(session, "RU0009029540")
    store_holdings(session, account, [
        BrokerPosition(isin="HK0000123577", ticker="x", quantity=Decimal("92"),
                       blocked=Decimal("92")),
        BrokerPosition(isin="RU0009029540", ticker="SBER", quantity=Decimal("10"),
                       blocked=Decimal("0")),
        BrokerPosition(isin="HK0000051877", ticker="y", quantity=Decimal("79"),
                       blocked=Decimal("79")),
    ])

    assert blocked_by_instrument(session) == {(account.id, linked.id): Decimal("92.00000000")}
```

- [ ] **Step 6: Запустить тест и убедиться, что он падает**

Run: `cd backend && uv run pytest tests/test_broker_holding.py -v`
Expected: FAIL с `ImportError: cannot import name 'BrokerHolding'`

- [ ] **Step 7: Реализовать модель, миграцию и сервис**

Создать `backend/app/models/broker_holding.py`:

```python
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class BrokerHolding(Base):
    """Снимок бумаг счёта у брокера: сколько есть и сколько из этого
    заблокировано.

    Раньше снимок брокера жил только внутри одного вызова сверки и нигде не
    сохранялся. Хранить его нужно по двум причинам: заблокированная часть
    известна только брокеру и должна быть видна на экране, а сама сверка
    перестаёт зависеть от того, дошёл ли до неё сетевой вызов в этот раз.

    `instrument_id` необязателен: у брокера может лежать бумага, которой нет в
    нашем справочнике — например, появившаяся в результате конвертации, о
    которой в журнале нет ни одной операции. Терять такую строку нельзя, именно
    она объясняет расхождение.
    """

    __tablename__ = "broker_holding"
    __table_args__ = (
        UniqueConstraint("account_id", "isin", name="uq_broker_holding_account_isin"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("account.id"), index=True)
    instrument_id: Mapped[int | None] = mapped_column(ForeignKey("instrument.id"), index=True)
    isin: Mapped[str] = mapped_column(String(12), index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    # Часть quantity, заблокированная брокером или биржей. Не добавка к нему.
    blocked: Mapped[Decimal] = mapped_column(Numeric(20, 8), default=0)
    as_of: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
```

Дописать в `backend/app/models/__init__.py`: `from app.models.broker_holding import BrokerHolding`
и `"BrokerHolding",` в `__all__` (после `"Base"`).

Создать `backend/alembic/versions/0013_broker_holding.py`:

```python
"""broker holding snapshot

Revision ID: 0013
Revises: 0012

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0013'
down_revision: Union[str, Sequence[str], None] = '0012'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'broker_holding',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('account_id', sa.Integer(), nullable=False),
        sa.Column('instrument_id', sa.Integer(), nullable=True),
        sa.Column('isin', sa.String(length=12), nullable=False),
        sa.Column('quantity', sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column('blocked', sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column('as_of', sa.DateTime(timezone=True), server_default=sa.text('now()'),
                  nullable=False),
        sa.ForeignKeyConstraint(['account_id'], ['account.id']),
        sa.ForeignKeyConstraint(['instrument_id'], ['instrument.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('account_id', 'isin', name='uq_broker_holding_account_isin'),
    )
    op.create_index(op.f('ix_broker_holding_account_id'), 'broker_holding', ['account_id'],
                    unique=False)
    op.create_index(op.f('ix_broker_holding_instrument_id'), 'broker_holding', ['instrument_id'],
                    unique=False)
    op.create_index(op.f('ix_broker_holding_isin'), 'broker_holding', ['isin'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_broker_holding_isin'), table_name='broker_holding')
    op.drop_index(op.f('ix_broker_holding_instrument_id'), table_name='broker_holding')
    op.drop_index(op.f('ix_broker_holding_account_id'), table_name='broker_holding')
    op.drop_table('broker_holding')
```

Создать `backend/app/sync/holdings.py`:

```python
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.connectors.base import BrokerPosition
from app.models import Account, BrokerHolding, Instrument


def store_holdings(session: Session, account: Account, positions: list[BrokerPosition]) -> int:
    """Заменяет снимок бумаг счёта присланным брокером.

    Замена, а не дополнение: снимок описывает состояние на момент времени, и
    бумага, которой у брокера больше нет, обязана исчезнуть.
    """
    session.execute(delete(BrokerHolding).where(BrokerHolding.account_id == account.id))

    if not positions:
        session.flush()
        return 0

    instrument_ids = {
        isin: instrument_id
        for instrument_id, isin in session.execute(
            select(Instrument.id, Instrument.isin).where(
                Instrument.isin.in_({item.isin for item in positions})
            )
        ).all()
    }

    for item in positions:
        session.add(BrokerHolding(
            account_id=account.id,
            instrument_id=instrument_ids.get(item.isin),
            isin=item.isin,
            quantity=item.quantity,
            blocked=item.blocked,
        ))

    session.flush()
    return len(positions)


def blocked_by_instrument(session: Session) -> dict[tuple[int, int], Decimal]:
    """Заблокированные количества по парам «счёт, инструмент».

    Строки без связи с инструментом и с нулевой блокировкой пропускаются: у
    первых нечего показывать в таблице позиций, вторые ничего не сообщают.
    """
    rows = session.execute(
        select(BrokerHolding.account_id, BrokerHolding.instrument_id, BrokerHolding.blocked)
        .where(BrokerHolding.instrument_id.is_not(None), BrokerHolding.blocked != 0)
    ).all()
    return {(account_id, instrument_id): blocked
            for account_id, instrument_id, blocked in rows}
```

- [ ] **Step 8: Записывать снимок при синхронизации**

В `backend/app/sync/service.py` заменить строки получения позиций и сверки:

```python
            broker_positions = connector.fetch_positions(account.external_id)
            store_holdings(session, account, broker_positions)
            findings = reconcile_account(session, account, broker_positions)
            run.mismatches = len(findings)
```

Импорт: `from app.sync.holdings import store_holdings`.

Сверка остаётся на списке из вызова, а не читает таблицу: она сверяет журнал с
тем, что брокер сказал именно в этом прогоне, и промежуточная запись в базу
между двумя шагами ничего к этому не добавляет.

- [ ] **Step 9: Запустить тесты**

Run: `cd backend && uv run pytest tests/test_broker_holding.py tests/test_sync_service.py tests/test_reconcile.py tests/test_migrations.py -v`
Expected: PASS

- [ ] **Step 10: Коммит**

```bash
git add backend/app/models/broker_holding.py backend/app/models/__init__.py \
        backend/app/sync/holdings.py backend/alembic/versions/0013_broker_holding.py \
        backend/app/connectors/base.py backend/app/connectors/tbank/connector.py \
        backend/app/sync/service.py backend/tests/test_broker_holding.py \
        backend/tests/test_tbank_connector.py backend/tests/test_sync_service.py
git commit -m "feat: снимок бумаг брокера с заблокированной частью"
```

---

### Task 7: Признак ограничения в обороте

Задача 6 закрыла блокировку в узком смысле — поле `blocked` у брокера. Владелец
имеет в виду более широкое: бумага, которой нельзя распорядиться. Таких в
портфеле гораздо больше двух, и признак у них другой.

**Files:**
- Modify: `backend/app/models/instrument.py`
- Create: `backend/alembic/versions/0014_instrument_trading_restricted.py`
- Modify: `backend/app/connectors/base.py`
- Modify: `backend/app/connectors/tbank/connector.py`
- Modify: `backend/app/connectors/tbank/mapper.py`
- Modify: `backend/app/instruments/service.py`
- Modify: `backend/app/instruments/backfill.py`
- Create: `backend/tests/test_restrictions.py`
- Modify: `backend/tests/test_tbank_mapper.py`

**Interfaces:**
- Consumes: `BrokerInstrument` и `apply_reference` в том виде, в каком они есть
  до этой задачи; `_reference_from(op)` из `app/instruments/service.py`.
- Produces: `BrokerInstrument.buy_available: bool | None` и `sell_available: bool | None`;
  колонка `Instrument.trading_restricted: bool`;
  `apply_reference(instrument, kind, name, currency=None, restricted=None) -> bool`;
  ключи payload `instrument_buy_available` и `instrument_sell_available`.

**Что установлено разведкой.** `tradingStatus` для этого не годится: он
описывает текущую сессию, и в выходной день `NOT_AVAILABLE_FOR_TRADING` стоит
даже у обычных рублёвых облигаций и у фонда EQMX. Разделяет пара флагов
`buyAvailableFlag`/`sellAvailableFlag` — оба `false` ровно у того, чем нельзя
распорядиться:

| Инструменты счёта | buy/sell |
|---|---|
| Рублёвые акции, облигации, фонды: X5, OZON, YDEX, T, DOMRF, EQMX, TMOS@, все выпуски RU000… | `true/true` |
| Гонконгские: 9866, 700, 3690, 939, 9618, 9868, 288, 9988, 2015, 3988, 9888, 3067 | `false/false` |
| Американские: XYZ, TDOC, U, MELI | `false/false` |
| Внебиржевые US30303M1027, US69608A1088 | `false/false`, плюс `blockedTcaFlag=true` |
| Конвертированные AGRO и FIVE | `false/false` |
| `HK0000051877` | `false/false` |
| `HK0000123577` | `true/true` — ловится только полем `blocked` из задачи 6 |

Последняя строка и есть причина, по которой признака нужно два: справочник и
снимок остатков знают о разном, и ни один из них не покрывает оба случая.
Флаги приходят и в списочных методах справочника (проверено на `Etfs` и
`Currencies`), то есть доезжают обычной синхронизацией, а не только поштучным
разрешением по FIGI.

- [ ] **Step 1: Написать падающий тест переноса флагов через границу коннектора**

Создать `backend/tests/test_restrictions.py`:

```python
from decimal import Decimal

from app.connectors.base import BrokerInstrument
from app.instruments.service import apply_reference
from app.models import Instrument


def add_instrument(session, isin: str, restricted: bool = False) -> Instrument:
    instrument = Instrument(isin=isin, ticker=isin, secid=isin, kind="share",
                            currency="RUB", trading_restricted=restricted)
    session.add(instrument)
    session.flush()
    return instrument


def test_instrument_is_restricted_when_neither_buy_nor_sell_available(session):
    """Гонконгская акция: купить нельзя, продать нельзя. Именно так выглядят в
    справочнике все иностранные бумаги портфеля."""
    instrument = add_instrument(session, "HK0000009866")

    changed = apply_reference(instrument, "share", "Nio", "HKD", restricted=True)

    assert changed is True
    assert instrument.trading_restricted is True


def test_restriction_is_lifted_when_broker_says_so(session):
    """False — законное значение, а не «сведений нет». Если бумагу разблокируют,
    признак обязан сняться сам, без ручной правки базы."""
    instrument = add_instrument(session, "RU0009029540", restricted=True)

    changed = apply_reference(instrument, "share", "Сбербанк", "RUB", restricted=False)

    assert changed is True
    assert instrument.trading_restricted is False


def test_unknown_restriction_does_not_touch_the_flag(session):
    """Справочник флагов не дал — прежнее значение сохраняется. Так приходят
    операции, записанные до появления флагов в payload."""
    instrument = add_instrument(session, "RU0009029540", restricted=True)

    apply_reference(instrument, "share", "Сбербанк", "RUB", restricted=None)

    assert instrument.trading_restricted is True


def test_broker_instrument_carries_availability_flags():
    """Флаги едут через границу коннектора отдельными полями, а не одним уже
    вычисленным признаком: решение «оба false значит нельзя распорядиться» —
    доменное, и принимать его коннектору не положено."""
    instrument = BrokerInstrument(isin="HK0000009866", ticker="9866", kind="share",
                                  buy_available=False, sell_available=False)

    assert (instrument.buy_available, instrument.sell_available) == (False, False)
```

- [ ] **Step 2: Запустить тест и убедиться, что он падает**

Run: `cd backend && uv run pytest tests/test_restrictions.py -v`
Expected: FAIL — `Instrument` не принимает `trading_restricted`

- [ ] **Step 3: Добавить колонку и миграцию**

В `backend/app/models/instrument.py` дописать в класс:

```python
    # Бумагой нельзя распорядиться: брокер не даёт ни купить, ни продать.
    # Так выглядят все иностранные бумаги портфеля после 2022 года, а также
    # выпуски, снятые с торгов после конвертации (AGRO, FIVE). Это не то же
    # самое, что заблокированное количество в broker_holding: там блокировка
    # конкретных бумаг на конкретном счёте, здесь — свойство самой бумаги.
    trading_restricted: Mapped[bool] = mapped_column(Boolean, default=False,
                                                     server_default=text("false"))
```

Импорты дополнить: `from sqlalchemy import Boolean, Date, Numeric, String, text`.

Создать `backend/alembic/versions/0014_instrument_trading_restricted.py`:

```python
"""признак ограничения в обороте у инструмента

Revision ID: 0014
Revises: 0013

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0014'
down_revision: Union[str, Sequence[str], None] = '0013'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # По умолчанию не ограничен: у большинства бумаг это так, а те, что
    # ограничены, проставит дозаполнение справочника
    # (python -m app.instruments.backfill) — оно же чинит вид и валюту.
    op.add_column('instrument', sa.Column('trading_restricted', sa.Boolean(), nullable=False,
                                          server_default=sa.text('false')))


def downgrade() -> None:
    op.drop_column('instrument', 'trading_restricted')
```

- [ ] **Step 4: Расширить `BrokerInstrument` и разбор справочника**

В `backend/app/connectors/base.py` дописать в `BrokerInstrument`:

```python
    # Доступность операций по данным справочника брокера. Оба флага False
    # означают, что бумагой нельзя распорядиться; вывод из этого делает домен
    # (app/instruments/service.py), а не коннектор. None — брокер сведений не
    # дал: у уже записанных операций этих ключей в payload нет вовсе.
    buy_available: bool | None = None
    sell_available: bool | None = None
```

В `backend/app/connectors/tbank/connector.py` в `_to_broker_instrument`:

```python
    return BrokerInstrument(
        isin=raw.get("isin") or None,
        ticker=raw.get("ticker") or None,
        kind=kind,
        name=raw.get("name") or None,
        currency=currency.upper() if currency else None,
        # Флаги есть и в списочных методах справочника, и в поштучном
        # GetInstrumentBy — оба пути дают их одинаково.
        buy_available=raw.get("buyAvailableFlag"),
        sell_available=raw.get("sellAvailableFlag"),
    )
```

- [ ] **Step 5: Провести флаги через payload операции**

В `backend/app/connectors/tbank/mapper.py` в `_instrument_payload` дописать:

```python
        # Доступность операций: по ней домен решает, ограничена ли бумага в
        # обороте. Едут двумя полями, а не готовым признаком, — вывод доменный.
        "instrument_buy_available": instrument.buy_available,
        "instrument_sell_available": instrument.sell_available,
```

В `backend/tests/test_tbank_mapper.py` дописать тест по образцу существующих
проверок payload:

```python
def test_payload_carries_availability_flags():
    instrument = BrokerInstrument(isin="HK0000009866", ticker="9866", kind="share",
                                  name="Nio", currency="HKD",
                                  buy_available=False, sell_available=False)

    result = map_operation(EXECUTED_BUY_OPERATION, instrument, now=NOW)

    assert result.payload["instrument_buy_available"] is False
    assert result.payload["instrument_sell_available"] is False
```

`EXECUTED_BUY_OPERATION` и `NOW` — уже существующие в файле фикстуры; если они
названы иначе, использовать те, что есть.

- [ ] **Step 6: Научить резолвер инструментов проставлять признак**

В `backend/app/instruments/service.py` расширить `apply_reference`:

```python
def apply_reference(
    instrument: Instrument,
    kind: str | None,
    name: str | None,
    currency: str | None = None,
    restricted: bool | None = None,
) -> bool:
```

и дописать в её тело перед `return changed`:

```python
    # None и False здесь разное: None — «справочник ничего не сказал», и тогда
    # прежнее значение сохраняется; False — «брокер говорит, что операции
    # доступны», и признак обязан сняться. Проверка на истинность, как у
    # остальных полей, склеила бы эти два случая, и разблокированная бумага
    # осталась бы ограниченной навсегда.
    if restricted is not None and instrument.trading_restricted != restricted:
        instrument.trading_restricted = restricted
        changed = True
```

В докстринг `apply_reference` дописать абзац:

```
    Признак ограничения в обороте обновляется в обе стороны, в отличие от
    остальных полей: снятие блокировки — такое же сообщение справочника, как и
    её появление.
```

Расширить `_reference_from`, чтобы она возвращала и признак:

```python
def _reference_from(op: RawOperation) -> tuple[str | None, str | None, str | None, bool | None]:
    """Справочные сведения, положенные коннектором в payload операции (см.
    app/connectors/tbank/mapper.py). Ключей может не быть вовсе — например, у
    операции, записанной в журнал до того, как коннектор научился их класть."""
    kind = op.payload.get("instrument_kind")
    name = op.payload.get("instrument_name")
    currency = op.payload.get("instrument_currency")
    buy = op.payload.get("instrument_buy_available")
    sell = op.payload.get("instrument_sell_available")
    return (
        str(kind) if kind else None,
        str(name) if name else None,
        str(currency).upper() if currency else None,
        _restricted(buy, sell),
    )


def _restricted(buy: object, sell: object) -> bool | None:
    """Ограничена ли бумага в обороте: недоступны обе операции сразу.

    Одного флага мало. Бумага, которую нельзя купить, но можно продать,
    распоряжению поддаётся — именно так выглядят выпуски, закрытые для новых
    покупок, но не замороженные. Ограничением считается только пара.

    Хотя бы один флаг отсутствует — сведений нет, возвращаем None: прежнее
    значение в базе трогать нельзя.
    """
    if not isinstance(buy, bool) or not isinstance(sell, bool):
        return None
    return not buy and not sell
```

Оба места вызова `_reference_from` распаковывают теперь четыре значения:
в `resolve_instrument` это `apply_reference(existing, *_reference_from(op))` —
менять не нужно, распаковка звёздочкой сама передаст четвёртый аргумент;
в `_insert_instrument` строка `kind, name, currency = _reference_from(op)`
превращается в `kind, name, currency, restricted = _reference_from(op)`, поле
`trading_restricted=bool(restricted)` добавляется в конструктор `Instrument`,
а вызов в обработчике гонки становится
`apply_reference(winner, kind, name, currency, restricted)`.

- [ ] **Step 7: Дозаполнять признак по всему справочнику**

В `backend/app/instruments/backfill.py` в `backfill_instruments` заменить строку
применения справочника:

```python
        if found is not None:
            touched |= apply_reference(
                instrument, found.kind, found.name, found.currency,
                _restricted_from(found),
            )
```

и добавить в тот же файл:

```python
def _restricted_from(found: BrokerInstrument) -> bool | None:
    """Ограничение в обороте по флагам справочника. Правило то же, что и для
    операций (app/instruments/service.py): ограничением считается недоступность
    обеих операций сразу, а отсутствие любого из флагов — отсутствие сведений."""
    if not isinstance(found.buy_available, bool) or not isinstance(found.sell_available, bool):
        return None
    return not found.buy_available and not found.sell_available
```

Докстринг `backfill_instruments` дополнить: «вид, название, валюту и признак
ограничения в обороте». Это основной путь для 251 уже записанного инструмента:
операции по бумагам, которые просто лежат в портфеле годами, в окно
синхронизации не попадают никогда.

- [ ] **Step 8: Дописать тест дозаполнения**

В `backend/tests/test_restrictions.py`:

```python
def test_backfill_marks_restricted_instruments(session):
    from app.instruments.backfill import backfill_instruments

    add_instrument(session, "HK0000009866")
    add_instrument(session, "RU0009029540")

    changed = backfill_instruments(session, {
        "HK0000009866": BrokerInstrument(isin="HK0000009866", ticker="9866", kind="share",
                                         name="Nio", currency="HKD",
                                         buy_available=False, sell_available=False),
        "RU0009029540": BrokerInstrument(isin="RU0009029540", ticker="SBER", kind="share",
                                         name="Сбербанк", currency="RUB",
                                         buy_available=True, sell_available=True),
    })

    assert changed == 1
    restricted = {i.isin: i.trading_restricted for i in session.query(Instrument).all()}
    assert restricted == {"HK0000009866": True, "RU0009029540": False}


def test_sell_only_instrument_is_not_restricted(session):
    """Купить нельзя, продать можно — распоряжению поддаётся. Ограничением
    считается только пара недоступных операций."""
    instrument = add_instrument(session, "RU000A1054W1")

    apply_reference(instrument, "bond", "Выпуск", "RUB", restricted=None)
    changed = apply_reference(instrument, "bond", "Выпуск", "RUB", restricted=False)

    assert changed is False
    assert instrument.trading_restricted is False
```

- [ ] **Step 9: Запустить тесты**

Run: `cd backend && uv run pytest tests/test_restrictions.py tests/test_instrument_seam.py tests/test_tbank_mapper.py tests/test_migrations.py -v`
Expected: PASS

- [ ] **Step 10: Прогнать весь бэкенд**

Run: `cd backend && uv run pytest`
Expected: PASS

- [ ] **Step 11: Коммит**

```bash
git add backend/app/models/instrument.py backend/app/connectors/base.py \
        backend/app/connectors/tbank/connector.py backend/app/connectors/tbank/mapper.py \
        backend/app/instruments/service.py backend/app/instruments/backfill.py \
        backend/alembic/versions/0014_instrument_trading_restricted.py \
        backend/tests/test_restrictions.py backend/tests/test_tbank_mapper.py
git commit -m "feat: признак ограничения бумаги в обороте"
```

---

### Task 8: Капитал целиком — оценка в рублях

**Files:**
- Create: `backend/app/analytics/valuation.py`
- Create: `backend/tests/test_valuation.py`
- Modify: `backend/app/analytics/service.py`
- Modify: `backend/tests/test_analytics.py`
- Modify: `backend/app/snapshots/service.py`

**Interfaces:**
- Consumes: `latest_prices` и `LatestPrice` из `app/marketdata/service.py`;
  `latest_rates`, `to_base` из `app/marketdata/fx.py`; `cash_by_account` из
  `app/accounts/cash.py`; `blocked_by_instrument` из `app/sync/holdings.py`;
  `Instrument.trading_restricted` из задачи 7.
- Produces: `ValuedPosition` и `value_position(...)` в `app/analytics/valuation.py`;
  переработанный `Overview` в `app/analytics/service.py` с полями
  `total_value`, `securities_value`, `cash_value`, `restricted_value`,
  `by_asset_class`, `by_account`, `by_currency`, `position_currencies`,
  `as_of`, `fx_as_of`, `valued_positions`, `positions_total`;
  `PositionRow` дополняется полями `value_base: Decimal | None`,
  `blocked: Decimal`, `restricted: bool`, `price_source: str | None`.

**Про две разновидности ограничения.** Задача 6 дала заблокированное количество
на счёте, задача 7 — свойство самой бумаги. Наружу отдаётся одна сумма
`restricted_value`: владельцу важно, какой частью капитала он не может
распорядиться, а не по какой из двух причин. Различие сохраняется в строке
позиции (`blocked` — количество, `restricted` — признак бумаги), чтобы
происхождение можно было увидеть.

- [ ] **Step 1: Написать падающий тест оценки**

Создать `backend/tests/test_valuation.py`:

```python
from datetime import date
from decimal import Decimal

from app.analytics.valuation import value_position
from app.marketdata.service import LatestPrice, TBANK_SOURCE

RATES = {"RUB": Decimal("1"), "HKD": Decimal("10.4724"), "CNY": Decimal("12.1655")}


def test_rouble_position_needs_no_conversion():
    valued = value_position(
        quantity=Decimal("10"),
        price=LatestPrice(close=Decimal("300"), on_date=date(2026, 8, 9),
                          currency="RUB", source="moex"),
        rates=RATES,
    )

    assert valued.value == Decimal("3000.0000")
    assert valued.value_base == Decimal("3000.0000")
    assert valued.currency == "RUB"


def test_foreign_position_is_converted_by_rate():
    """Сорок акций по 36,90 HKD — это 1476 HKD, и по курсу 10,4724 они дают
    15 457,26 ₽. Раньше такая позиция вовсе не попадала в капитал."""
    valued = value_position(
        quantity=Decimal("40"),
        price=LatestPrice(close=Decimal("36.90"), on_date=date(2026, 8, 9),
                          currency="HKD", source=TBANK_SOURCE),
        rates=RATES,
    )

    assert valued.value == Decimal("1476.0000")
    assert valued.value_base == Decimal("15457.2624")


def test_missing_price_gives_no_value():
    valued = value_position(quantity=Decimal("10"), price=None, rates=RATES)

    assert valued.value is None and valued.value_base is None


def test_missing_rate_gives_value_in_own_currency_but_not_in_roubles():
    """Цена есть, курса нет: сумму в валюте показать можно и нужно, а в рублёвый
    итог такая позиция войти не может. Ноль вместо неё занизил бы капитал молча."""
    valued = value_position(
        quantity=Decimal("3"),
        price=LatestPrice(close=Decimal("79.20"), on_date=date(2026, 8, 9),
                          currency="USD", source=TBANK_SOURCE),
        rates=RATES,
    )

    assert valued.value == Decimal("237.6000")
    assert valued.value_base is None


def test_short_position_keeps_negative_value():
    """Короткая позиция стоит отрицательных денег — это обязательство, а не
    ноль. Движок позиций умеет шорты, и оценка обязана их не терять."""
    valued = value_position(
        quantity=Decimal("-15000"),
        price=LatestPrice(close=Decimal("2"), on_date=date(2026, 8, 9),
                          currency="RUB", source="moex"),
        rates=RATES,
    )

    assert valued.value_base == Decimal("-30000.0000")
```

- [ ] **Step 2: Запустить тест и убедиться, что он падает**

Run: `cd backend && uv run pytest tests/test_valuation.py -v`
Expected: FAIL с `ModuleNotFoundError: No module named 'app.analytics.valuation'`

- [ ] **Step 3: Написать модуль оценки**

Создать `backend/app/analytics/valuation.py`:

```python
from dataclasses import dataclass
from decimal import Decimal

from app.marketdata.fx import to_base
from app.marketdata.service import LatestPrice
from app.money import money


@dataclass(frozen=True)
class ValuedPosition:
    """Оценка позиции в двух валютах сразу.

    `value` — в валюте самой бумаги: столько стоит позиция там, где она
    торгуется. `value_base` — то же в рублях, и оно может отсутствовать, когда
    `value` есть: цена известна, а курса на дату нет. Различать эти два случая
    обязательно — иначе валютная позиция без курса тихо выпадет из капитала и
    ничем себя не обнаружит.
    """

    value: Decimal | None
    value_base: Decimal | None
    currency: str | None
    price: Decimal | None
    price_source: str | None


def value_position(
    quantity: Decimal, price: LatestPrice | None, rates: dict[str, Decimal]
) -> ValuedPosition:
    """Стоимость позиции по последней цене и курсам на дату оценки.

    Знак количества сохраняется: короткая позиция стоит отрицательных денег,
    это обязательство, а не ноль.
    """
    if price is None:
        return ValuedPosition(value=None, value_base=None, currency=None,
                              price=None, price_source=None)

    value = money(quantity * price.close)
    return ValuedPosition(
        value=value,
        value_base=to_base(value, price.currency, rates),
        currency=price.currency,
        price=price.close,
        price_source=price.source,
    )
```

- [ ] **Step 4: Запустить тест**

Run: `cd backend && uv run pytest tests/test_valuation.py -v`
Expected: PASS, 5 тестов

- [ ] **Step 5: Написать падающий тест нового обзора**

Дописать в `backend/tests/test_analytics.py` (помощники создания счёта,
инструмента, позиции и цены брать из уже существующих в файле; `add_priced_position`
дополнить параметром `restricted: bool = False`, который проставляется в
`Instrument.trading_restricted`, и параметром `currency`, задающим валюту цены,
а `add_rate` завести новым — он кладёт строку в `fx_rate` за сегодняшнюю
московскую дату):

```python
def test_total_includes_cash(session):
    """Капитал — это бумаги плюс деньги. Раньше денег в системе не было вовсе,
    и главная цифра дашборда была неполна на весь денежный остаток."""
    account = add_account(session)
    add_priced_position(session, account, isin="RU0009029540", quantity=Decimal("10"),
                        price=Decimal("300"), currency="RUB")
    store_cash(session, account, [BrokerCash(currency="RUB", amount=Decimal("20782.27"),
                                             blocked=Decimal("0"))])

    overview = portfolio_overview(session)

    assert overview.securities_value == Decimal("3000.0000")
    assert overview.cash_value == Decimal("20782.2700")
    assert overview.total_value == Decimal("23782.2700")


def test_foreign_position_enters_the_total_by_rate(session):
    """Ровно та поломка, ради которой затевалась фаза: 34 валютные позиции из 59
    не входили в капитал никак."""
    account = add_account(session)
    add_priced_position(session, account, isin="HK0000009866", quantity=Decimal("40"),
                        price=Decimal("36.90"), currency="HKD")
    add_rate(session, "HKD", Decimal("10.4724"))

    overview = portfolio_overview(session)

    assert overview.total_value == Decimal("15457.2624")
    assert overview.by_currency["HKD"] == Decimal("1476.0000")


def test_position_without_rate_is_counted_as_unvalued(session):
    """Цена есть, курса нет — позиция не входит в рублёвый итог и обязана быть
    посчитана как неоценённая, иначе покрытие соврёт «оценены все»."""
    account = add_account(session)
    add_priced_position(session, account, isin="US0000000000", quantity=Decimal("3"),
                        price=Decimal("79.20"), currency="USD")

    overview = portfolio_overview(session)

    assert overview.total_value == Decimal("0.0000")
    assert (overview.valued_positions, overview.positions_total) == (0, 1)


def test_cash_lands_in_its_own_asset_class(session):
    account = add_account(session)
    store_cash(session, account, [BrokerCash(currency="RUB", amount=Decimal("100"),
                                             blocked=Decimal("0"))])

    overview = portfolio_overview(session)

    assert overview.by_asset_class == {"cash": Decimal("100.0000")}


def test_gold_balance_is_valued_as_metal(session):
    """Золото приходит в остатках валютным кодом XAU и граммами; курс к рублю
    берётся с MOEX. В классах активов это металл, а не деньги."""
    account = add_account(session)
    store_cash(session, account, [BrokerCash(currency="XAU", amount=Decimal("10"),
                                             blocked=Decimal("0"))])
    add_rate(session, "XAU", Decimal("11410"))

    overview = portfolio_overview(session)

    assert overview.by_asset_class == {"gold": Decimal("114100.0000")}
    assert overview.total_value == Decimal("114100.0000")


def test_blocked_quantity_counts_as_restricted(session):
    """Заблокированные бумаги никуда не делись и в капитал входят — брокер
    считает их так же. Отдельная цифра нужна, чтобы владелец видел, какой
    частью капитала он не может распоряжаться."""
    account = add_account(session)
    add_priced_position(session, account, isin="HK0000123577", quantity=Decimal("92"),
                        price=Decimal("100"), currency="RUB")
    store_holdings(session, account, [BrokerPosition(isin="HK0000123577", ticker="x",
                                                     quantity=Decimal("92"),
                                                     blocked=Decimal("92"))])

    overview = portfolio_overview(session)

    assert overview.total_value == Decimal("9200.0000")
    assert overview.restricted_value == Decimal("9200.0000")


def test_partially_blocked_position_counts_only_its_blocked_share(session):
    account = add_account(session)
    add_priced_position(session, account, isin="RU0009029540", quantity=Decimal("100"),
                        price=Decimal("300"), currency="RUB")
    store_holdings(session, account, [BrokerPosition(isin="RU0009029540", ticker="SBER",
                                                     quantity=Decimal("100"),
                                                     blocked=Decimal("25"))])

    overview = portfolio_overview(session)

    assert overview.total_value == Decimal("30000.0000")
    assert overview.restricted_value == Decimal("7500.0000")


def test_instrument_restricted_in_trading_counts_whole_position(session):
    """Иностранная акция: брокер не даёт ни купить, ни продать. Заблокированного
    количества у неё при этом нет — недоступна вся позиция, а не её часть.
    Таких в портфеле владельца больше двадцати, и именно они составляют
    основную недоступную часть капитала."""
    account = add_account(session)
    add_priced_position(session, account, isin="HK0000009866", quantity=Decimal("40"),
                        price=Decimal("36.90"), currency="HKD", restricted=True)
    add_rate(session, "HKD", Decimal("10.4724"))

    overview = portfolio_overview(session)

    assert overview.restricted_value == Decimal("15457.2624")


def test_restriction_and_blocking_are_not_added_up(session):
    """Бумага ограничена в обороте и вдобавок заблокирована. Недоступна она
    ровно один раз: сложение дало бы больше стоимости самой позиции."""
    account = add_account(session)
    add_priced_position(session, account, isin="HK0000051877", quantity=Decimal("79"),
                        price=Decimal("100"), currency="RUB", restricted=True)
    store_holdings(session, account, [BrokerPosition(isin="HK0000051877", ticker="y",
                                                     quantity=Decimal("79"),
                                                     blocked=Decimal("79"))])

    overview = portfolio_overview(session)

    assert overview.restricted_value == Decimal("7900.0000")
```

- [ ] **Step 6: Запустить тест и убедиться, что он падает**

Run: `cd backend && uv run pytest tests/test_analytics.py -v`
Expected: FAIL — у `Overview` нет полей `securities_value`, `cash_value`, `restricted_value`

- [ ] **Step 7: Переписать аналитику**

В `backend/app/analytics/service.py`:

Дополнить `CLASS_BY_KIND` и добавить классификацию денег:

```python
# Классы активов для денежных остатков. Драгоценные металлы приходят от брокера
# валютными кодами (XAU — золото в граммах), но деньгами не являются: их место
# в аллокации — металлы, иначе портфель с граммом золота выглядит как портфель
# с наличными.
METAL_CURRENCIES = {"XAU": "gold", "XAG": "silver", "XPT": "platinum", "XPD": "palladium"}
CASH_CLASS = "cash"


def cash_asset_class(currency: str) -> str:
    return METAL_CURRENCIES.get(currency.upper(), CASH_CLASS)
```

Заменить `Overview` целиком:

```python
@dataclass(frozen=True)
class Overview:
    # Весь капитал в рублях: бумаги плюс деньги, всё пересчитано по курсам.
    # Позиция, для которой нет цены или нет курса, в итог не входит и считается
    # неоценённой — см. valued_positions.
    total_value: Decimal
    # Из чего он складывается. Раньше поле под стоимость бумаг было дословным
    # дублем итога и потому убрано из контракта; с приходом денег оно перестало
    # им быть.
    securities_value: Decimal
    cash_value: Decimal
    # Часть капитала, которой нельзя распорядиться: заблокированные брокером
    # количества плюс бумаги, ограниченные в обороте. Входит в total_value, а
    # не вычитается из него — брокер считает так же, и капитал обязан с ним
    # сходиться. Отдельная цифра отвечает на другой вопрос: сколько из этих
    # денег реально доступно.
    restricted_value: Decimal
    by_asset_class: dict[str, Decimal]
    by_account: dict[int, Decimal]
    # Итог по каждой валюте в ней самой, без пересчёта: сколько именно
    # гонконгских долларов в портфеле. Складывать между собой нельзя.
    by_currency: dict[str, Decimal]
    position_currencies: list[str]
    as_of: date | None
    # Дата курсов, по которым сделан пересчёт. Отдельно от as_of: котировки
    # обновляются каждые пятнадцать минут, курсы — раз в сутки, и несвежесть у
    # них разная.
    fx_as_of: date | None
    valued_positions: int
    positions_total: int
```

Переписать `position_rows` и `portfolio_overview`:

```python
def position_rows(session: Session) -> list[PositionRow]:
    prices = latest_prices(session)
    rates = latest_rates(session, moscow_today())
    blocked = blocked_by_instrument(session)
    result: list[PositionRow] = []

    for position, instrument, account in _rows(session):
        valued = value_position(position.quantity, prices.get(instrument.id), rates)
        cost = money(position.quantity * position.average_price)

        if valued.value is None:
            # Не ноль: «0 ₽» и «0,0%» в таблице читаются как «бумага ничего не
            # стоит», хотя на деле котировки просто нет.
            profit = None
            percent = None
        else:
            profit = money(valued.value - cost)
            # По модулю себестоимости: у короткой позиции количество, а с ним и
            # себестоимость отрицательные, и деление на неё как есть перевернуло
            # бы знак доходности — заработок на шорте показывался бы убытком.
            percent = money(profit / abs(cost) * 100) if cost != 0 else money("0")

        result.append(
            PositionRow(
                isin=instrument.isin,
                ticker=instrument.ticker,
                name=instrument.issuer or instrument.ticker or instrument.isin or "—",
                broker=account.broker,
                account_id=account.id,
                # Валюта строки — валюта цены, а не справочника: у замещающей
                # облигации справочник брокера говорит «рубли» (расчёты по ней
                # рублёвые), а котируется она в юанях.
                currency=valued.currency or _currency_of(instrument),
                quantity=position.quantity,
                average_price=position.average_price,
                last_price=valued.price,
                market_value=valued.value,
                value_base=valued.value_base,
                price_source=valued.price_source,
                blocked=blocked.get((account.id, instrument.id), Decimal("0")),
                restricted=instrument.trading_restricted,
                profit=profit,
                profit_percent=percent,
            )
        )
    return result


def portfolio_overview(session: Session) -> Overview:
    prices = latest_prices(session)
    rates = latest_rates(session, moscow_today())
    blocked = blocked_by_instrument(session)

    by_class: dict[str, Decimal] = {}
    by_account_id: dict[int, Decimal] = {}
    by_currency: dict[str, Decimal] = {}
    position_currencies: set[str] = set()
    securities = money("0")
    restricted_value = money("0")
    as_of: date | None = None
    positions_total = 0
    valued_positions = 0

    for position, instrument, account in _rows(session):
        positions_total += 1
        latest = prices.get(instrument.id)
        valued = value_position(position.quantity, latest, rates)
        position_currencies.add(valued.currency or _currency_of(instrument))

        if valued.value is not None and latest is not None:
            currency = valued.currency or _currency_of(instrument)
            by_currency[currency] = money(by_currency.get(currency, money("0")) + valued.value)
            # Дата актуальности — по всем позициям, у которых есть цена,
            # независимо от того, удалось ли перевести её в рубли: она про
            # свежесть котировок.
            if as_of is None or latest.on_date > as_of:
                as_of = latest.on_date

        if valued.value_base is None:
            # Неоценённая позиция не попадает ни в итог, ни в разбивки — но
            # молча выпасть из ответа она не должна: её считает positions_total,
            # и дашборд обязан показать, что оценены не все.
            continue

        valued_positions += 1
        securities = money(securities + valued.value_base)

        klass = asset_class_of(instrument)
        by_class[klass] = money(by_class.get(klass, money("0")) + valued.value_base)
        by_account_id[account.id] = money(
            by_account_id.get(account.id, money("0")) + valued.value_base
        )

        # Недоступная часть позиции. Две причины дают её по-разному: бумага,
        # ограниченная в обороте, недоступна целиком, а заблокированное
        # количество — только своей долей. Когда верно и то и другое,
        # ограничение бумаги поглощает блокировку количества, и складывать их
        # нельзя — получится больше, чем сама позиция.
        blocked_quantity = blocked.get((account.id, instrument.id), Decimal("0"))
        if instrument.trading_restricted:
            restricted_value = money(restricted_value + valued.value_base)
        elif blocked_quantity and position.quantity != 0:
            # Доля по количеству: цена у заблокированной и свободной части одна
            # и та же бумага.
            restricted_value = money(
                restricted_value + valued.value_base * blocked_quantity / position.quantity
            )

    cash_total = money("0")
    for account_id, balances in cash_by_account(session).items():
        for currency, amount in balances.items():
            in_base = to_base(amount, currency, rates)
            if in_base is None:
                # Курса нет — остаток в капитал не входит, но в разбивке по
                # валютам виден: иначе он исчезает бесследно.
                by_currency[currency] = money(by_currency.get(currency, money("0")) + amount)
                continue
            cash_total = money(cash_total + in_base)
            by_currency[currency] = money(by_currency.get(currency, money("0")) + amount)
            klass = cash_asset_class(currency)
            by_class[klass] = money(by_class.get(klass, money("0")) + in_base)
            by_account_id[account_id] = money(
                by_account_id.get(account_id, money("0")) + in_base
            )

    return Overview(
        total_value=money(securities + cash_total),
        securities_value=securities,
        cash_value=cash_total,
        restricted_value=restricted_value,
        by_asset_class=by_class,
        by_account=dict(sorted(by_account_id.items())),
        by_currency=dict(sorted(by_currency.items())),
        position_currencies=sorted(position_currencies),
        as_of=as_of,
        fx_as_of=latest_rate_date(session, moscow_today()),
        valued_positions=valued_positions,
        positions_total=positions_total,
    )
```

Дополнить `PositionRow` полями:

```python
    # Стоимость позиции в рублях. None, когда цена есть, а курса нет: тогда
    # market_value в валюте показать можно, а в рублёвый итог позиция не войдёт.
    value_base: Decimal | None
    # Метка источника цены: биржа или брокер. Оценка по данным брокера не
    # независима — это видно на экране, а не только в базе.
    price_source: str | None
    # Заблокированная часть количества по данным брокера (broker_holding).
    blocked: Decimal
    # Бумагой нельзя распорядиться вовсе: брокер не даёт ни купить, ни продать
    # (Instrument.trading_restricted). Причина другая, чем у blocked, и обе
    # встречаются по отдельности.
    restricted: bool
```

Импорты в начале файла дополнить:

```python
from app.accounts.cash import cash_by_account
from app.analytics.valuation import value_position
from app.marketdata.fx import latest_rate_date, latest_rates, to_base
from app.sync.holdings import blocked_by_instrument
from app.timeutils import moscow_today
```

- [ ] **Step 8: Добавить `latest_rate_date` в модуль курсов**

В `backend/app/marketdata/fx.py`:

```python
def latest_rate_date(session: Session, on_date: date) -> date | None:
    """Дата самых свежих курсов не позже указанной. Нужна интерфейсу: у
    котировок и курсов разная частота обновления, и «данные на» у них разное."""
    return session.execute(
        select(func.max(FxRate.on_date)).where(FxRate.on_date <= on_date)
    ).scalar_one_or_none()
```

Дописать тест в `backend/tests/test_fx.py`:

```python
def test_latest_rate_date_is_none_when_no_rates(session):
    from app.marketdata.fx import latest_rate_date

    assert latest_rate_date(session, date(2026, 8, 10)) is None
```

- [ ] **Step 9: Запустить тесты аналитики**

Run: `cd backend && uv run pytest tests/test_analytics.py tests/test_valuation.py tests/test_fx.py -v`
Expected: PASS. Существующие тесты, утверждавшие, что валютные позиции не
входят в итог, описывают снятое поведение — заменить их тестами из шага 5.

- [ ] **Step 10: Прогнать весь бэкенд**

Run: `cd backend && uv run pytest`
Expected: PASS. Тест снимка (`take_snapshot`) продолжает работать без правок:
он берёт `overview.total_value` и `overview.by_account`, а их имена не менялись.

- [ ] **Step 11: Коммит**

```bash
git add backend/app/analytics/valuation.py backend/app/analytics/service.py \
        backend/app/marketdata/fx.py backend/tests/test_valuation.py \
        backend/tests/test_analytics.py backend/tests/test_fx.py
git commit -m "feat: капитал целиком — бумаги в любой валюте плюс деньги"
```

---

### Task 9: Контракт API

**Files:**
- Modify: `backend/app/api/schemas.py`
- Modify: `backend/app/api/routes_portfolio.py`
- Modify: `backend/tests/test_api.py`

**Interfaces:**
- Consumes: `Overview` и `PositionRow` из задачи 8; `cash_by_account` из задачи 5.
- Produces: `OverviewOut` с полями `total_value`, `securities_value`,
  `cash_value`, `restricted_value`, `by_asset_class`, `by_account`, `by_currency`,
  `position_currencies`, `as_of`, `fx_as_of`, `valued_positions`,
  `positions_total`; `PositionOut` с `value_base`, `price_source`, `blocked`,
  `restricted`;
  `CashOut(account: str, currency: str, amount: Decimal, blocked: Decimal)` и
  эндпоинт `GET /api/portfolio/cash`.

- [ ] **Step 1: Написать падающий тест**

Дописать в `backend/tests/test_api.py` (клиент и подготовку данных брать по
образцу существующих тестов файла):

```python
def test_overview_exposes_capital_parts(client, session):
    """Контракт обязан разделять бумаги и деньги: одна общая цифра не даёт
    понять, отчего капитал изменился."""
    # подготовка: счёт, оценённая рублёвая позиция на 3000, остаток 20782.27

    body = client.get("/api/portfolio/overview").json()

    assert body["securities_value"] == "3000.0000"
    assert body["cash_value"] == "20782.2700"
    assert body["total_value"] == "23782.2700"
    assert body["restricted_value"] == "0.0000"


def test_positions_expose_price_source_and_blocked(client, session):
    """Оценка по цене брокера не независима, и это должно быть видно на экране,
    а не только в базе."""
    body = client.get("/api/portfolio/positions").json()

    assert body[0]["price_source"] in ("moex", "tbank", None)
    assert "blocked" in body[0]
    assert "restricted" in body[0]
    assert "value_base" in body[0]


def test_cash_endpoint_lists_balances_per_account_and_currency(client, session):
    body = client.get("/api/portfolio/cash").json()

    assert body == [{"account": "Счёт (acc-1)", "currency": "RUB",
                     "amount": "20782.2700", "blocked": "0.0000"}]
```

- [ ] **Step 2: Запустить тест и убедиться, что он падает**

Run: `cd backend && uv run pytest tests/test_api.py -v`
Expected: FAIL — в ответе нет `securities_value`, эндпоинт `/api/portfolio/cash` даёт 404

- [ ] **Step 3: Обновить схемы**

В `backend/app/api/schemas.py` заменить `OverviewOut` и дополнить `PositionOut`,
добавить `CashOut`:

```python
class OverviewOut(BaseModel):
    # Весь капитал в рублях: бумаги плюс деньги, всё пересчитано по курсам ЦБ.
    total_value: Decimal
    securities_value: Decimal
    cash_value: Decimal
    # Часть капитала, которой нельзя распорядиться: заблокированные количества
    # плюс бумаги, ограниченные в обороте. Входит в total_value.
    restricted_value: Decimal
    by_asset_class: dict[str, Decimal]
    by_account: dict[str, Decimal]
    # Итог по каждой валюте в ней самой, без пересчёта.
    by_currency: dict[str, Decimal]
    position_currencies: list[str]
    as_of: date | None
    # Дата курсов: обновляются раз в сутки, тогда как котировки — каждые
    # пятнадцать минут, и несвежесть у них разная.
    fx_as_of: date | None
    valued_positions: int
    positions_total: int

    @field_serializer("total_value", "securities_value", "cash_value", "restricted_value")
    def serialize_amount(self, value: Decimal) -> str:
        return f"{value:.4f}"

    @field_serializer("by_asset_class", "by_account", "by_currency")
    def serialize_mapping(self, value: dict[str, Decimal]) -> dict[str, str]:
        return {key: f"{amount:.4f}" for key, amount in value.items()}


class CashOut(BaseModel):
    account: str
    currency: str
    amount: Decimal
    blocked: Decimal

    @field_serializer("amount", "blocked")
    def serialize_money(self, value: Decimal) -> str:
        return f"{value:.4f}"
```

В `PositionOut` добавить поля и расширить сериализатор:

```python
    # Стоимость позиции в рублях; null, когда цена есть, а курса нет.
    value_base: Decimal | None
    # Откуда взята цена: "moex" — биржа, "tbank" — сам брокер.
    price_source: str | None
    # Заблокированная брокером часть количества.
    blocked: Decimal
    # Бумагой нельзя распорядиться вовсе: ни купить, ни продать.
    restricted: bool

    @field_serializer("quantity", "blocked")
    def serialize_quantity(self, value: Decimal) -> str:
        return f"{value:.8f}"

    @field_serializer("average_price", "last_price", "market_value", "value_base",
                      "profit", "profit_percent")
    def serialize_money(self, value: Decimal | None) -> str | None:
        return None if value is None else f"{value:.4f}"
```

- [ ] **Step 4: Обновить роутеры**

В `backend/app/api/routes_portfolio.py` в `get_overview` передать новые поля:

```python
    return OverviewOut(
        total_value=overview.total_value,
        securities_value=overview.securities_value,
        cash_value=overview.cash_value,
        restricted_value=overview.restricted_value,
        by_asset_class=overview.by_asset_class,
        by_account={
            account_label(accounts[account_id]): value
            for account_id, value in overview.by_account.items()
        },
        by_currency=overview.by_currency,
        position_currencies=overview.position_currencies,
        as_of=overview.as_of,
        fx_as_of=overview.fx_as_of,
        valued_positions=overview.valued_positions,
        positions_total=overview.positions_total,
    )
```

и добавить эндпоинт остатков после `get_positions`:

```python
@router.get("/portfolio/cash", response_model=list[CashOut])
def get_cash(session: Session = Depends(get_session)) -> list[CashOut]:
    balances = session.execute(
        select(CashBalance).order_by(CashBalance.account_id, CashBalance.currency)
    ).scalars().all()
    accounts = {
        account.id: account
        for account in session.execute(
            select(Account).where(Account.id.in_({b.account_id for b in balances}))
        ).scalars()
    }
    return [
        CashOut(
            account=account_label(accounts[balance.account_id]),
            currency=balance.currency,
            amount=balance.amount,
            blocked=balance.blocked,
        )
        for balance in balances
    ]
```

Импорты дополнить: `from app.api.schemas import CashOut, ...` и
`from app.models import Account, CashBalance, DailySnapshot, Reconciliation`.

- [ ] **Step 5: Запустить тесты**

Run: `cd backend && uv run pytest tests/test_api.py -v`
Expected: PASS

- [ ] **Step 6: Прогнать весь бэкенд**

Run: `cd backend && uv run pytest`
Expected: PASS

- [ ] **Step 7: Коммит**

```bash
git add backend/app/api/schemas.py backend/app/api/routes_portfolio.py backend/tests/test_api.py
git commit -m "feat: контракт API с деньгами, блокировками и источником цены"
```

---

### Task 10: Интерфейс — полный капитал, деньги, ограничения

**Files:**
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/components/SummaryCard.tsx`
- Create: `frontend/src/components/CashCard.tsx`
- Modify: `frontend/src/components/PositionsTable.tsx`
- Modify: `frontend/src/pages/PortfolioPage.tsx`
- Modify: `frontend/src/api/format.test.ts`

**Interfaces:**
- Consumes: контракт из задачи 9.
- Produces: типы `Overview` (с `securities_value`, `cash_value`,
  `restricted_value`, `fx_as_of`), `PositionRow` (с `value_base`, `price_source`,
  `blocked`, `restricted`), `CashRow`; `api.cash()`; компонент `CashCard`.

- [ ] **Step 1: Обновить типы и клиент**

В `frontend/src/api/client.ts` заменить интерфейс `Overview` и дополнить `PositionRow`:

```ts
export interface Overview {
  // Весь капитал в рублях: бумаги плюс деньги, всё пересчитано по курсам ЦБ.
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
  as_of: string | null;
  // Дата курсов: они обновляются раз в сутки, котировки — каждые 15 минут.
  fx_as_of: string | null;
  valued_positions: number;
  positions_total: number;
}
```

```ts
  // Стоимость в рублях; null, когда цена есть, а курса нет.
  value_base: string | null;
  // "moex" — биржа, "tbank" — цена самого брокера (оценка не независима).
  price_source: string | null;
  // Заблокированная брокером часть количества.
  blocked: string;
  // Бумагой нельзя распорядиться вовсе: ни купить, ни продать.
  restricted: boolean;
```

```ts
export interface CashRow {
  account: string;
  currency: string;
  amount: string;
  blocked: string;
}
```

и в объект `api`:

```ts
  cash: () => request<CashRow[]>("/portfolio/cash"),
```

- [ ] **Step 2: Переписать карточку сводки**

В `frontend/src/components/SummaryCard.tsx` заменить `ForeignCurrencyTotals` на
разбор капитала и оговорку о блокировках:

```tsx
// Из чего складывается капитал. Одна общая цифра не отвечает на вопрос,
// изменился портфель или просто пришли деньги на счёт.
function CapitalParts({ overview }: { overview: Overview }) {
  return (
    <div style={{ margin: "10px 0 0", fontSize: 12.5, color: "var(--tx-2)" }}>
      Бумаги <span style={{ color: "var(--tx-1, inherit)" }}>
        {formatMoney(overview.securities_value, BASE_CURRENCY)}
      </span>
      {" · деньги "}
      <span style={{ color: "var(--tx-1, inherit)" }}>
        {formatMoney(overview.cash_value, BASE_CURRENCY)}
      </span>
    </div>
  );
}

// Недоступное входит в капитал — брокер считает так же. Но распорядиться им
// нельзя, и знать об этом нужно рядом с самой цифрой: у владельца больше
// двадцати таких позиций, это заметная доля портфеля.
function RestrictedNotice({ overview }: { overview: Overview }) {
  if (overview.restricted_value === "0.0000") return null;

  return (
    <div style={{ margin: "6px 0 0", fontSize: 12.5, color: "var(--tx-2)" }}>
      Недоступно к продаже{" "}
      <span style={{ color: "var(--amber)" }}>
        {formatMoney(overview.restricted_value, BASE_CURRENCY)}
      </span>
    </div>
  );
}
```

В теле `SummaryCard` заменить `<ForeignCurrencyTotals byCurrency={overview.by_currency} />`
на `<CapitalParts overview={overview} />` и `<RestrictedNotice overview={overview} />`,
а подпись под заголовком — на безусловное «Совокупный капитал» без оговорки
«рублёвая часть»: оговорка описывала прежнее поведение, когда валютные позиции
в итог не входили, и теперь она была бы неправдой. Импорт `hasForeignCurrency`
из этого файла убрать, если он больше нигде в нём не используется.

- [ ] **Step 3: Написать карточку остатков**

Создать `frontend/src/components/CashCard.tsx`:

```tsx
import { formatMoney } from "../api/format";
import type { CashRow } from "../api/client";

// Металлы приходят от брокера валютными кодами: XAU — золото в граммах.
// Подписывать их знаком валюты нельзя, у граммов его нет.
const METAL_LABEL: Record<string, string> = {
  XAU: "золото, г",
  XAG: "серебро, г",
  XPT: "платина, г",
  XPD: "палладий, г",
};

export function CashCard({ rows, error }: { rows: CashRow[]; error: string | null }) {
  if (error) {
    return <div className="card"><div style={{ color: "var(--red)" }}>{error}</div></div>;
  }
  if (rows.length === 0) {
    return (
      <div className="card">
        <div style={{ color: "var(--tx-2)", fontSize: 12 }}>Денежные остатки</div>
        <div style={{ marginTop: 8, color: "var(--tx-2)", fontSize: 13 }}>
          Остатков нет. Они появятся после синхронизации.
        </div>
      </div>
    );
  }

  return (
    <div className="card">
      <div style={{ color: "var(--tx-2)", fontSize: 12 }}>Денежные остатки</div>
      <div style={{ marginTop: 8, display: "grid", gap: 6 }}>
        {rows.map((row) => (
          <div
            key={`${row.account}-${row.currency}`}
            style={{ display: "flex", justifyContent: "space-between", fontSize: 13 }}
          >
            <span style={{ color: "var(--tx-2)" }}>
              {row.account}
              {METAL_LABEL[row.currency] ? ` · ${METAL_LABEL[row.currency]}` : ""}
            </span>
            <span style={{ fontVariantNumeric: "tabular-nums" }}>
              {METAL_LABEL[row.currency]
                ? row.amount.replace(/\.?0+$/, "").replace(".", ",")
                : formatMoney(row.amount, row.currency)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Показать источник цены и ограничения в таблице позиций**

В `frontend/src/components/PositionsTable.tsx` в строке позиции: рядом с ценой
показывать пометку источника, когда цена пришла от брокера, и пометку
недоступности — когда бумага ограничена в обороте или заблокирована. Причины
две, и подсказка у них разная: «ни купить, ни продать» — свойство бумаги,
«заблокировано N шт.» — состояние конкретного остатка.

```tsx
// Цена брокера — не независимая оценка: тот же источник, с чьим снимком мы
// сверяемся. Молча показывать её наравне с биржевой нельзя.
function PriceSourceMark({ source }: { source: string | null }) {
  if (source !== "tbank") return null;
  return (
    <span title="Цена от брокера, не с биржи" style={{ color: "var(--tx-2)", marginLeft: 4 }}>
      ·бр
    </span>
  );
}

// Ограничение бумаги и блокировка количества — разные причины недоступности, и
// обе встречаются по отдельности. Значок один, подсказка разная: владельцу
// важно, можно ли распорядиться, но при разборе расхождений важно и почему.
function RestrictedMark({ restricted, blocked }: { restricted: boolean; blocked: string }) {
  const blockedQuantity = Number.parseFloat(blocked);
  if (!restricted && blockedQuantity === 0) return null;

  const title = restricted
    ? "Ни купить, ни продать: бумага ограничена в обороте"
    : `Заблокировано брокером: ${formatQuantity(blocked)} шт.`;

  return <span title={title} style={{ color: "var(--amber)", marginLeft: 4 }}>🔒</span>;
}
```

Вставить `<PriceSourceMark source={row.price_source} />` в ячейку цены и
`<RestrictedMark restricted={row.restricted} blocked={row.blocked} />` рядом с
названием бумаги. Импорт `formatQuantity` из `../api/format` — он там уже есть.

- [ ] **Step 5: Подключить всё на странице**

В `frontend/src/pages/PortfolioPage.tsx` добавить запрос остатков и карточку:

```tsx
  const cash = useQuery({ queryKey: ["cash"], queryFn: api.cash });
```

```tsx
  const cashError = cash.isError ? (cash.error as Error).message : null;
```

и поставить `<CashCard rows={cash.data ?? []} error={cashError} />` в сетку под
карточкой сводки. Подпись даты в шапке дополнить датой курсов:

```tsx
        <span style={{ fontSize: 12.5, color: "var(--tx-2)" }}>
          {asOf ? `данные на ${asOf}` : "данные ещё не рассчитаны — нет котировок"}
          {overview.data!.fx_as_of ? ` · курсы на ${formatDate(overview.data!.fx_as_of)}` : ""}
        </span>
```

- [ ] **Step 6: Проверить сборку и тесты фронтенда**

Run: `cd frontend && pnpm vitest run && pnpm build`
Expected: PASS, сборка без ошибок типов

- [ ] **Step 7: Коммит**

```bash
git add frontend/src
git commit -m "feat: показ полного капитала, денежных остатков и блокировок"
```

---

### Task 11: Проверка на живых данных

**Files:**
- Create: `backend/app/valuation_check.py`
- Modify: `README.md`
- Modify: `docs/roadmap.md`

**Interfaces:**
- Consumes: `portfolio_overview` из задачи 8, `TBankConnector`, `TBankClient`.
- Produces: `python -m app.valuation_check` — печатает наш итог по каждому счёту
  рядом с итогом брокера и расхождение между ними.

- [ ] **Step 1: Написать сверку итогов**

Создать `backend/app/valuation_check.py`:

```python
"""Сверка нашей оценки капитала с итогом брокера.

Запускается вручную: `cd backend && uv run python -m app.valuation_check`.
Читающий инструмент — ходит в API брокера за итогами по счетам и ничего не
меняет ни у брокера, ни в базе.

Зачем отдельный модуль, а не тест: сверять есть смысл только на настоящих
данных владельца, а они в тесты не попадают и попадать не должны.
"""

import logging
from decimal import Decimal

from app.analytics.service import portfolio_overview
from app.config import get_settings
from app.connectors.tbank.client import OPERATIONS_SERVICE, TBankClient
from app.connectors.tbank.quotation import to_money
from app.db import SessionLocal
from app.models import Account
from app.money import money

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

# Расхождение, ниже которого сверка считается сошедшейся. Копейки набегают
# из-за разного порядка округления и разной секунды котировки; проценты — нет.
TOLERANCE_RATIO = Decimal("0.005")


def main() -> None:
    token = get_settings().tbank_token
    if not token:
        logger.warning("TBANK_TOKEN не задан — сверять не с чем")
        return

    client = TBankClient(token)
    with SessionLocal() as session:
        overview = portfolio_overview(session)
        accounts = {
            account.id: account
            for account in session.query(Account).filter(Account.broker == "tbank")
        }

        total_ours = money("0")
        total_theirs = money("0")
        for account_id, ours in sorted(overview.by_account.items()):
            account = accounts.get(account_id)
            if account is None:
                continue
            payload = client._post(
                OPERATIONS_SERVICE, "GetPortfolio", {"accountId": account.external_id}
            )
            raw_total = payload.get("totalAmountPortfolio")
            if not raw_total:
                # Счёт особого типа (цифровые финансовые активы) итога не даёт.
                logger.info("%-28s наш %14s   брокер итога не даёт", account.name, f"{ours:,.2f}")
                continue
            theirs = to_money(raw_total)
            diff = ours - theirs
            verdict = "ок" if abs(diff) <= abs(theirs) * TOLERANCE_RATIO else "РАСХОЖДЕНИЕ"
            logger.info(
                "%-28s наш %14s   брокер %14s   разница %12s  %s",
                account.name, f"{ours:,.2f}", f"{theirs:,.2f}", f"{diff:,.2f}", verdict,
            )
            total_ours += ours
            total_theirs += theirs

        logger.info("")
        logger.info("Итого сопоставимых счетов: наш %s, брокер %s, разница %s",
                    f"{total_ours:,.2f}", f"{total_theirs:,.2f}",
                    f"{total_ours - total_theirs:,.2f}")
        logger.info("Оценено позиций: %s из %s", overview.valued_positions,
                    overview.positions_total)
        logger.info("Из них недоступно к продаже: %s", f"{overview.restricted_value:,.2f}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Накатить миграции и синхронизироваться**

Синхронизация ходит в живой счёт владельца — **запрашивать явное согласие
перед запуском**.

```bash
docker compose up -d --build
cd backend && uv run python -m app.instruments.backfill   # признак ограничения для 251 инструмента
curl -X POST http://localhost:8001/api/sync/tbank
```

Дозаполнение справочника обязательно и именно до синхронизации: без него
признак ограничения в обороте останется пустым у всех бумаг, купленных раньше
окна синхронизации, — а это почти весь портфель.

- [ ] **Step 3: Прогнать сверку**

Run: `cd backend && uv run python -m app.valuation_check`
Expected: по каждому счёту «ок». Ориентир на 09.08.2026 (цифры сдвинутся вместе
с рынком): Инвестиционный ≈ 5 333 989 ₽, Копилка ≈ 5 431 598 ₽, Лежебока
≈ 715 202 ₽, ИИС 4 000 ₽, Казино 0 ₽, всего около 11.48 млн ₽.

Расхождение по счёту означает не «подогнать допуск», а найти причину: у какой
позиции нет цены, у какой валюты нет курса, что попало в капитал дважды.
Ожидаемые честные причины — бумага, которой нет ни на MOEX, ни в ответе
брокера, и корпоративные действия (это фаза 2b, но на сумму они влияют).

- [ ] **Step 4: Обновить README**

В `README.md` дописать раздел о курсах и оценке: откуда берутся курсы (ЦБ,
`XML_daily`; золото — MOEX `GLDRUB_TOM`), что цена может прийти от брокера и
как это видно на экране, чем ограничение бумаги в обороте отличается от
заблокированного количества и почему недоступное всё равно входит в капитал,
и как запустить сверку `uv run python -m app.valuation_check`. Отдельно
отметить, что после накатывания миграций нужно один раз прогнать
`uv run python -m app.instruments.backfill` — иначе признак ограничения у 251
уже записанного инструмента останется пустым.
Добавить `/api/portfolio/cash` в перечень эндпоинтов, если он там есть.

- [ ] **Step 5: Отметить фазу в роадмепе**

В `docs/roadmap.md` в таблице статусов перевести «2a. Капитал целиком» в
«завершена», указав дату; в разделе «Где мы сейчас» заменить устаревшие цифры
(оценены 22 из 59, денег нет) фактическим результатом сверки из шага 3.

- [ ] **Step 6: Прогнать всё**

Run: `cd backend && uv run pytest && cd ../frontend && pnpm vitest run && pnpm build`
Expected: PASS

- [ ] **Step 7: Коммит**

```bash
git add backend/app/valuation_check.py README.md docs/roadmap.md
git commit -m "feat: сверка капитала с итогом брокера и обновление документации"
```

---

## Самопроверка плана

**Покрытие роадмепа.** Раздел «2a. Капитал целиком» требует пяти вещей:
курсы ЦБ (задача 1), рублёвая оценка валютных позиций (задачи 3, 4, 8),
денежные остатки (задача 5), заблокированные активы отдельной сущностью
(задачи 6 и 7), курсовая разница отдельной строкой — **не входит**: она требует
курса на дату каждой операции и разложения прибыли на бумажную и валютную
части, а это расчёт доходности, то есть фаза 4. В роадмепе строка про курсовую
разницу перенесена туда же при обновлении статуса (задача 11, шаг 5).
Признак готовности «капитал включает деньги, ни одна позиция не висит без
оценки, недоступное показано отдельно» проверяется задачей 11.

**Про «заблокированные активы».** Владелец имеет в виду не только поле
`blocked` у брокера, но и ограничение торгов: все бумаги в иностранной валюте
сейчас недоступны к продаже. Поэтому признаков два и задачи под них две —
задача 6 (количество на счёте) и задача 7 (свойство бумаги), — а наружу они
сводятся в одну сумму `restricted_value`.

**Что осознанно не входит в 2a.** Накопленный купонный доход по облигациям
(`currentNkd` есть в ответе брокера, но это доход, а не стоимость бумаги);
денежные потоки журнала как источник остатка вместо снимка брокера; курсы на
дату операции; корпоративные действия и переводы бумаг (фаза 2b).

**Согласованность имён.** `TBANK_SOURCE` объявляется в задаче 3 и используется
в задачах 4 и 8. `LatestPrice` получает поля `currency` и `source` в задаче 3 и
именно так читается в задаче 8. `BrokerPosition.blocked` вводится в задаче 6 и
используется в `store_holdings` там же. `latest_rates`/`to_base` из задачи 1
используются в задачах 2 и 8, `latest_rate_date` добавляется в задаче 8 шагом 8
и потребляется в том же шаге. `cash_by_account` из задачи 5 используется в
задаче 8. `blocked_by_instrument` из задачи 6 и `Instrument.trading_restricted`
из задачи 7 используются в задаче 8. Поле капитала называется
`restricted_value` во всех трёх слоях — аналитике, контракте и интерфейсе.

**Порядок.** Задачи 1–7 независимы между собой, кроме пары 5→6 (обе используют
`_get_positions`, вводимый в задаче 5) и 3→4 (`TBANK_SOURCE` и ключ
уникальности цены). Задача 8 требует 1–7, задача 9 требует 8, задача 10 требует
9, задача 11 — всех.
