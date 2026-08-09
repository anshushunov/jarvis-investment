"""drop redundant dedup_key index

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-08 12:30:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '0009'
down_revision: Union[str, Sequence[str], None] = '0008'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    На transaction.dedup_key стояли сразу два индекса: отдельный
    ix_transaction_dedup_key (от index=True в модели) и индекс, который
    PostgreSQL создаёт под уникальное ограничение uq_transaction_dedup_key.
    Возможности поиска у них одинаковые, а платится за оба — записью на каждой
    вставке в журнал. Отдельный снимается, уникальное ограничение остаётся:
    именно оно несёт смысл (защита от дубля), и его индекс полностью
    покрывает поиск по dedup_key.
    """
    op.drop_index(op.f('ix_transaction_dedup_key'), table_name='transaction')


def downgrade() -> None:
    """Downgrade schema."""
    op.create_index(op.f('ix_transaction_dedup_key'), 'transaction', ['dedup_key'], unique=False)
