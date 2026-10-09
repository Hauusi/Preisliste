"""Datenblätter (Modul „Datenblatt erstellen“)

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-09 10:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0012'
down_revision: Union[str, Sequence[str], None] = '0011'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'datasheets',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('owner_id', sa.Integer(), nullable=True),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('content', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name='fk_datasheets_owner'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('datasheets', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_datasheets_owner_id'), ['owner_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('datasheets', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_datasheets_owner_id'))
    op.drop_table('datasheets')
