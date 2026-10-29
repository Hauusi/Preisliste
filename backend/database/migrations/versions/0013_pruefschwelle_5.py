"""Prüfschwelle EK-Änderung: Standard 5 % statt 10 %

Hersteller, die noch auf dem alten Standard 10 stehen, werden auf 5 gesetzt.

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-28 20:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0013'
down_revision: Union[str, Sequence[str], None] = '0012'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('manufacturers') as batch_op:
        batch_op.alter_column('review_threshold', existing_type=sa.String(length=40), server_default='5',
                              existing_nullable=False)
    op.execute("UPDATE manufacturers SET review_threshold = '5' WHERE review_threshold = '10'")


def downgrade() -> None:
    with op.batch_alter_table('manufacturers') as batch_op:
        batch_op.alter_column('review_threshold', existing_type=sa.String(length=40), server_default='10',
                              existing_nullable=False)
