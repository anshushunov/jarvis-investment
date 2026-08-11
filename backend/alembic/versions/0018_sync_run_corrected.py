"""счётчик корректирующих записей у прогона синхронизации

Revision ID: 0018
Revises: 0017

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0018'
down_revision: Union[str, Sequence[str], None] = '0017'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Ноль у прошлых прогонов — честное значение, а не заглушка: корректирующие
    # записи появились в фазе 2b, и до неё их не было ни одной.
    op.add_column('sync_run', sa.Column('corrected', sa.Integer(), nullable=False,
                                        server_default=sa.text('0')))


def downgrade() -> None:
    op.drop_column('sync_run', 'corrected')
