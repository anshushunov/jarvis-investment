"""происхождение и покрытие у снимка стоимости

Revision ID: 0019
Revises: 0018

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0019'
down_revision: Union[str, Sequence[str], None] = '0018'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Существующие снимки сняты живьём — это про них известно точно.
    op.add_column('daily_snapshot', sa.Column('source', sa.String(16), nullable=False,
                                              server_default='live'))
    # А вот покрытие у них неизвестно, и NULL означает ровно это: заполнить его
    # сегодняшним числом значило бы сочинить прошлое. На этом же NULL стоит
    # правило перезаписи: снимок с неизвестным покрытием достройка перебивает.
    op.add_column('daily_snapshot', sa.Column('positions_total', sa.Integer(), nullable=True))
    op.add_column('daily_snapshot', sa.Column('valued_positions', sa.Integer(), nullable=True))
    op.add_column('daily_snapshot', sa.Column('unpriced', postgresql.JSONB(),
                                              nullable=False, server_default='[]'))


def downgrade() -> None:
    op.drop_column('daily_snapshot', 'unpriced')
    op.drop_column('daily_snapshot', 'valued_positions')
    op.drop_column('daily_snapshot', 'positions_total')
    op.drop_column('daily_snapshot', 'source')
