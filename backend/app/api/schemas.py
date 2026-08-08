from datetime import date
from decimal import Decimal

from pydantic import BaseModel, field_serializer


class OverviewOut(BaseModel):
    # Рублёвая часть портфеля; позиции в других валютах — в by_currency.
    total_value: Decimal
    positions_value: Decimal
    by_asset_class: dict[str, Decimal]
    by_account: dict[str, Decimal]
    by_currency: dict[str, Decimal]
    as_of: date | None
    # Покрытие оценкой — числа, а не деньги: сериализуются как есть.
    valued_positions: int
    positions_total: int

    @field_serializer("total_value", "positions_value")
    def serialize_amount(self, value: Decimal) -> str:
        return f"{value:.4f}"

    @field_serializer("by_asset_class", "by_account", "by_currency")
    def serialize_mapping(self, value: dict[str, Decimal]) -> dict[str, str]:
        return {key: f"{amount:.4f}" for key, amount in value.items()}


class PositionOut(BaseModel):
    isin: str | None
    ticker: str | None
    name: str
    broker: str
    # Валюта строки: суммы подписываются ею, а не рублём по умолчанию.
    currency: str
    quantity: Decimal
    average_price: Decimal
    # None = «оценки нет» и отдаётся наружу как null, чтобы на экране это
    # отличалось от настоящего нуля (см. PositionRow в app/analytics/service.py).
    last_price: Decimal | None
    market_value: Decimal | None
    profit: Decimal | None
    profit_percent: Decimal | None

    @field_serializer("quantity")
    def serialize_quantity(self, value: Decimal) -> str:
        return f"{value:.8f}"

    @field_serializer("average_price", "last_price", "market_value", "profit", "profit_percent")
    def serialize_money(self, value: Decimal | None) -> str | None:
        return None if value is None else f"{value:.4f}"


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
