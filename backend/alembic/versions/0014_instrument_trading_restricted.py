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
