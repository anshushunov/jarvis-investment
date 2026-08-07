from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, field_validator

from app.models import OperationType


class RawOperation(BaseModel):
    model_config = ConfigDict(frozen=True)

    external_id: str | None
    op_type: OperationType
    executed_at: datetime
    isin: str | None
    ticker: str | None
    quantity: Decimal
    price: Decimal
    amount: Decimal
    currency: str
    fee: Decimal
    payload: dict

    @field_validator("executed_at")
    @classmethod
    def executed_at_must_be_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("executed_at должен быть timezone-aware (содержать информацию о часовом поясе)")
        return value

    @field_validator("quantity", "price", "amount", "fee", mode="before")
    @classmethod
    def decimal_fields_must_not_be_float_or_bool(cls, value):
        if isinstance(value, bool):
            raise TypeError("bool недопустим для денежных величин, используйте str, int или Decimal")
        if isinstance(value, float):
            raise TypeError("float недопустим для денежных величин, используйте str или Decimal")
        return value
