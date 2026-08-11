from datetime import datetime
from decimal import Decimal
from types import MappingProxyType

from pydantic import BaseModel, ConfigDict, field_validator

from app.models import OperationType


class RawOperation(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

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
    # Только для чтения: frozen=True защищает поля модели, но не содержимое
    # вложенного словаря — правка payload у одного держателя ссылки меняла
    # операцию у всех сразу, а обещание неизменности оказывалось ложным.
    #
    # Аннотация — именно MappingProxyType, а не typing.Mapping: для
    # typing.Mapping у pydantic есть встроенная core-схема, которая после
    # "before"-валидатора всё равно приводит значение к обычному dict (тогда
    # frozen=True защищает поле, но не спасает от operation.payload[k] = v).
    # MappingProxyType pydantic не знает — arbitrary_types_allowed заставляет
    # его просто проверить isinstance и оставить объект как есть.
    #
    # Цена этого выбора: MappingProxyType непрозрачен для pydantic —
    # model_dump_json(), model_json_schema() и глубокое копирование модели
    # (copy.deepcopy, model_copy(deep=True)) на нём падают ("Unable to
    # serialize unknown type: mappingproxy" / "cannot pickle 'mappingproxy'
    # object"). Сегодня это никого не задевает — таких вызывающих у
    # RawOperation нет. Первый, кто захочет залогировать операцию как JSON
    # или сделать её глубокую копию, упрётся в эту ошибку — пусть узнает о
    # причине здесь, а не из трассировки.
    payload: MappingProxyType

    @field_validator("payload", mode="before")
    @classmethod
    def payload_must_be_read_only(cls, value):
        if isinstance(value, MappingProxyType):
            return value
        return MappingProxyType(dict(value))

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
