from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, field_serializer


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
    average_price: Decimal
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

    @field_serializer("total_value")
    def serialize_total(self, value: Decimal) -> str:
        return f"{value:.4f}"


class ReconciliationOut(BaseModel):
    isin: str | None
    status: str
    ledger_quantity: Decimal
    broker_quantity: Decimal
    account: str

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
    error: str | None
