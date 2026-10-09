"""Kalkulationsfaktor je Artikel aus unserer Liste (Spalte „Kalk“)

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-09 09:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0011'
down_revision: Union[str, Sequence[str], None] = '0010'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('articles', schema=None) as batch_op:
        batch_op.add_column(sa.Column('calc_factor', sa.String(length=40), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('articles', schema=None) as batch_op:
        batch_op.drop_column('calc_factor')
