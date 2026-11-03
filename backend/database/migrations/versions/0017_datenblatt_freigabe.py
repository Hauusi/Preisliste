"""Datenblätter freigeben: freigegebene Blätter sehen alle Benutzer in einer gemeinsamen Liste

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-03 12:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0017'
down_revision: Union[str, Sequence[str], None] = '0016'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('datasheets', schema=None) as batch_op:
        batch_op.add_column(sa.Column('released_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('released_by', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_datasheets_released_by', 'users', ['released_by'], ['id'])


def downgrade() -> None:
    with op.batch_alter_table('datasheets', schema=None) as batch_op:
        batch_op.drop_constraint('fk_datasheets_released_by', type_='foreignkey')
        batch_op.drop_column('released_by')
        batch_op.drop_column('released_at')
