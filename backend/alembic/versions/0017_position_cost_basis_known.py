"""признак известной себестоимости у позиции

Revision ID: 0017
Revises: 0016

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0017'
down_revision: Union[str, Sequence[str], None] = '0016'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # По умолчанию известна: до появления переводов все позиции собирались
    # только из сделок, у которых цена есть всегда. Пересборка позиций после
    # синхронизации проставит признак заново по журналу.
    op.add_column('position', sa.Column('cost_basis_known', sa.Boolean(), nullable=False,
                                        server_default=sa.text('true')))


def downgrade() -> None:
    op.drop_column('position', 'cost_basis_known')
