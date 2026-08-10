"""решения владельца по расхождениям журнала с брокером

Revision ID: 0016
Revises: 0015

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0016'
down_revision: Union[str, Sequence[str], None] = '0015'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'ledger_decision',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('account_id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.Enum('CONVERSION', 'ADJUSTMENT', 'ACCEPTED_AS_IS',
                                  name='decision_kind'), nullable=False),
        sa.Column('status', sa.Enum('CONFIRMED', 'REJECTED', 'REVERTED',
                                    name='decision_status'), nullable=False),
        sa.Column('from_instrument_id', sa.Integer(), nullable=True),
        sa.Column('from_quantity', sa.Numeric(20, 8), nullable=True),
        sa.Column('to_instrument_id', sa.Integer(), nullable=True),
        sa.Column('to_quantity', sa.Numeric(20, 8), nullable=True),
        sa.Column('cost_basis', sa.Numeric(20, 4), nullable=True),
        sa.Column('effective_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('note', sa.Text(), nullable=False),
        sa.Column('proposed', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('reverts_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['account_id'], ['account.id']),
        sa.ForeignKeyConstraint(['from_instrument_id'], ['instrument.id']),
        sa.ForeignKeyConstraint(['to_instrument_id'], ['instrument.id']),
        sa.ForeignKeyConstraint(['reverts_id'], ['ledger_decision.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_ledger_decision_account_id'), 'ledger_decision',
                    ['account_id'])


def downgrade() -> None:
    # Откат уносит решения владельца, а вместе с ними — объяснение записям
    # журнала, которые они породили. Сами записи остаются (журнал append-only,
    # DELETE по нему запрещён триггером), но станут безотцовщиной: понять,
    # откуда взялась конвертация на 1012 бумаг, будет уже не из чего.
    # Отказываемся, как это делает 0011 при конфликте ключа.
    orphans = op.get_bind().execute(sa.text(
        "SELECT count(*) FROM transaction WHERE source = 'manual'"
    )).scalar_one()
    if orphans:
        raise RuntimeError(
            f"Откат миграции 0016 невозможен: в журнале {orphans} записей с "
            "source='manual', порождённых решениями владельца. Журнал "
            "append-only, удалить их нельзя, а без таблицы решений они "
            "останутся без объяснения. Отмените решения через "
            "POST /api/decisions/{id}/revert, либо снимите ограничение "
            "осознанно, отредактировав миграцию."
        )

    op.drop_index(op.f('ix_ledger_decision_account_id'), table_name='ledger_decision')
    op.drop_table('ledger_decision')
    sa.Enum(name='decision_status').drop(op.get_bind())
    sa.Enum(name='decision_kind').drop(op.get_bind())
