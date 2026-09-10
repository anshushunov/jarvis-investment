from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import TargetAllocation


def test_database_refuses_target_without_exactly_one_key(session):
    """Цель без ключа — не цель; цель с двумя ключами считала бы один рубль
    дважды. Оба случая отбивает база, а не только сервис."""
    session.add(TargetAllocation(asset_class=None, instrument_id=None, share=Decimal("0.5")))
    with pytest.raises(IntegrityError, match="ck_target_allocation_one_key"):
        session.flush()


def test_database_refuses_two_targets_on_one_class(session):
    session.add_all([
        TargetAllocation(asset_class="equity", share=Decimal("0.5")),
        TargetAllocation(asset_class="equity", share=Decimal("0.3")),
    ])
    with pytest.raises(IntegrityError, match="uq_target_allocation_asset_class"):
        session.flush()
