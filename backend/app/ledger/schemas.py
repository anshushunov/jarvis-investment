from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

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
