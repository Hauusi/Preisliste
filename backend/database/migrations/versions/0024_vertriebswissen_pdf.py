"""Vertriebswissen: PDF-Anhang an Einträgen

Revision ID: 0024
Revises: 0023
Create Date: 2026-11-13 10:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0024'
down_revision: Union[str, Sequence[str], None] = '0023'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('kb_entries', schema=None) as b:
        b.add_column(sa.Column('file_name', sa.String(length=200), nullable=True))
        b.add_column(sa.Column('file_key', sa.String(length=64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('kb_entries', schema=None) as b:
        b.drop_column('file_key')
        b.drop_column('file_name')
