from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_serializer


class OverviewOut(BaseModel):
    # Весь капитал в рублях: бумаги плюс деньги, всё пересчитано по курсам на
    # дату оценки — валюты от ЦБ, драгоценные металлы с MOEX (у ЦБ их нет).
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
    # Валюты позиций портфеля, включая неоценённые: по ним интерфейс решает,
    # нужна ли оговорка «рублёвая часть».
    position_currencies: list[str]
    # Валюты, которых не хватило курса: их часть капитала не посчитана, и
    # интерфейс обязан назвать их поимённо.
    currencies_without_rate: list[str]
    as_of: date | None
    # Дата курсов: обновляются раз в сутки, тогда как котировки — каждые
    # пятнадцать минут, и несвежесть у них разная. Самый старый из курсов,
    # участвовавших в пересчёте.
    fx_as_of: date | None
    # Покрытие оценкой — числа, а не деньги: сериализуются как есть.
    valued_positions: int
    positions_total: int

    @field_serializer("total_value", "securities_value", "cash_value", "restricted_value")
    def serialize_amount(self, value: Decimal) -> str:
        return f"{value:.4f}"

    @field_serializer("by_asset_class", "by_account", "by_currency")
    def serialize_mapping(self, value: dict[str, Decimal]) -> dict[str, str]:
        return {key: f"{amount:.4f}" for key, amount in value.items()}


class PositionOut(BaseModel):
    # Собирается разворачиванием PositionRow.__dict__ в routes_portfolio.py —
    # без forbid опечатка в имени поля или новое поле PositionRow молча
    # выпадали бы из ответа вместо явной ошибки при сборке.
    model_config = ConfigDict(extra="forbid")

    isin: str | None
    ticker: str | None
    name: str
    broker: str
    # Подпись счёта — той же единственной на проект функцией, что подписывает
    # счета в расхождениях и в результатах синхронизации.
    account: str
    # Валюта котировки: текущая цена и стоимость подписываются ею, а не рублём
    # по умолчанию.
    currency: str
    quantity: Decimal
    # None — себестоимость неизвестна (бумаги пришли переводом). Сериализуется
    # как null и на экране даёт прочерк, а не ноль.
    average_price: Decimal | None
    cost_basis_known: bool
    # Валюта средней цены — своя, потому что у замещающей облигации расчёты
    # рублёвые, а котировка валютная (см. PositionRow в app/analytics/service.py).
    average_price_currency: str
    # None = «оценки нет» и отдаётся наружу как null, чтобы на экране это
    # отличалось от настоящего нуля (см. PositionRow в app/analytics/service.py).
    last_price: Decimal | None
    market_value: Decimal | None
    # Стоимость позиции в рублях; null, когда цена есть, а курса нет.
    value_base: Decimal | None
    # Откуда взята цена: "moex" — биржа, "tbank" — сам брокер.
    price_source: str | None
    # Заблокированная брокером часть количества.
    blocked: Decimal
    # Бумагой нельзя распорядиться вовсе: ни купить, ни продать.
    restricted: bool
    profit: Decimal | None
    profit_percent: Decimal | None

    @field_serializer("quantity", "blocked")
    def serialize_quantity(self, value: Decimal) -> str:
        return f"{value:.8f}"

    @field_serializer("average_price", "last_price", "market_value", "value_base",
                      "profit", "profit_percent")
    def serialize_money(self, value: Decimal | None) -> str | None:
        return None if value is None else f"{value:.4f}"


class CashOut(BaseModel):
    account: str
    currency: str
    amount: Decimal
    blocked: Decimal

    @field_serializer("amount", "blocked")
    def serialize_money(self, value: Decimal) -> str:
        return f"{value:.4f}"


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

    @field_serializer("total_value")
    def serialize_total(self, value: Decimal) -> str:
        return f"{value:.4f}"

    @field_serializer("by_account")
    def serialize_by_account(self, value: dict[str, Decimal]) -> dict[str, str]:
        return {key: f"{amount:.4f}" for key, amount in value.items()}


class SuggestionOut(BaseModel):
    """Гипотеза корпоративного действия, предложенная системой.

    Едет вместе со строкой расхождения, а не отдельным списком: сопоставлять
    их на стороне интерфейса значило бы повторить там правило подбора пары.
    """

    from_isin: str
    from_quantity: Decimal
    to_isin: str
    to_quantity: Decimal
    # Бумага-получатель заблокирована у брокера целиком — усиливающий признак.
    blocked_fully: bool
    # Кандидатов с такой же величиной несколько: выбирает владелец.
    ambiguous: bool

    @field_serializer("from_quantity", "to_quantity")
    def serialize_quantity(self, value: Decimal) -> str:
        return f"{value:.8f}"


class DecisionIn(BaseModel):
    # Подпись счёта — та же, что показана в строке расхождения: интерфейс
    # идентификаторов счетов не видит.
    account: str
    kind: str
    status: str
    from_isin: str | None = None
    from_quantity: Decimal | None = None
    to_isin: str | None = None
    to_quantity: Decimal | None = None
    cost_basis: Decimal | None = None
    effective_at: datetime
    note: str


class DecisionOut(BaseModel):
    id: int
    account: str
    kind: str
    status: str
    from_isin: str | None
    from_quantity: Decimal | None
    to_isin: str | None
    to_quantity: Decimal | None
    effective_at: datetime
    note: str
    reverts_id: int | None

    @field_serializer("from_quantity", "to_quantity")
    def serialize_quantity(self, value: Decimal | None) -> str | None:
        return None if value is None else f"{value:.8f}"


class RevertIn(BaseModel):
    note: str


class ReconciliationOut(BaseModel):
    isin: str | None
    status: str
    ledger_quantity: Decimal
    broker_quantity: Decimal
    account: str
    # Гипотезы конвертации по этой строке. Пусто — пары не нашлось, и
    # расхождение закрывается ручной корректировкой.
    suggestions: list[SuggestionOut] = []

    @field_serializer("ledger_quantity", "broker_quantity")
    def serialize_quantity(self, value: Decimal) -> str:
        return f"{value:.8f}"


class SyncRunOut(BaseModel):
    account: str
    broker: str
    status: str
    inserted: int
    skipped: int
    mismatches: int
    # Операции, которые брокер переписал задним числом (см. sync_run.corrected).
    corrected: int
    error: str | None


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
    # Сколько дней цепочка TWR действительно измерила для ЭТОГО периметра (не
    # общее число дней периода — оно одно на весь отчёт и уже есть в
    # `period.from`/`period.to`). Число, а не деньги: сериализуется как есть.
    # None — у периметра TWR не считается вовсе (строка «Деньги», см. Metric в
    # app/returns/metrics.py); 0 — цепочка построена, но не измерила ни
    # одного шага. Это разные ответы, и подменять один другим нельзя.
    chain_days: int | None
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
    # None — не ноль: посчитать нечем (нет цены/курса на конец или начало
    # периода), причина — в reason (см. InstrumentRow в app/returns/service.py,
    # уточнено по коду в задаче 8: бриф объявлял их обязательным Decimal).
    profit: Decimal | None
    value: Decimal | None
    # Позиция продана целиком: конечная стоимость ноль, история — нет.
    closed: bool
    # Нереализованная прибыль открытых партий — величина, которую и раскладывают
    # price_part с fx_part. Отдельно от profit, потому что это разные числа: у
    # бумаги с частичными продажами profit содержит ещё и реализованный
    # результат периода (дизайн, раздел 4.4). Экран подписывает колонку тем,
    # чем она является, а не «прибылью».
    unrealized: Decimal | None
    # Разложение нереализованной прибыли открытой позиции. None у рублёвой
    # бумаги в fx_part не бывает — там ноль; None означает «посчитать нечем», и
    # почему, говорит reason.
    price_part: Decimal | None
    fx_part: Decimal | None
    reason: str | None

    @field_serializer("xirr")
    def serialize_rate(self, value: Decimal | None) -> str | None:
        return None if value is None else f"{value:.4f}"

    @field_serializer("profit", "value", "unrealized", "price_part", "fx_part")
    def serialize_optional_money(self, value: Decimal | None) -> str | None:
        return None if value is None else f"{value:.4f}"


class CoverageOut(BaseModel):
    days_total: int
    days_valued: int
    # None — покрытие позиций на последний день периода никто не считал
    # (снимки старше фазы 2c). Ноль означал бы «позиций нет вовсе», а это
    # другое (см. Coverage в app/returns/service.py).
    positions_total: int | None
    positions_valued: int | None
    unpriced: list[str]
    # Сколько шагов выпало из цепочки TWR: у них не было базы для сравнения,
    # день был оценён не полностью или в ряду была дыра.
    chain_breaks: int
    # Сколько дней цепочка действительно измерила. Годовая ставка TWR приведена
    # к году по этому времени, и без него она не читается: 444 дня из 2219 и
    # 2219 из 2219 — разные ответы (см. Chain в app/returns/twr.py).
    chain_days: int
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
