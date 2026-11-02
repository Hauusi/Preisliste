"""Design-Vorlagen für Datenblätter (Datenblatt als Vorlage markieren, mit Produktart)

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-02 14:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0015'
down_revision: Union[str, Sequence[str], None] = '0014'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('datasheets', schema=None) as batch_op:
        batch_op.add_column(sa.Column('is_template', sa.Boolean(), server_default='0', nullable=False))
        batch_op.add_column(sa.Column('template_kind', sa.String(length=60), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('datasheets', schema=None) as batch_op:
        batch_op.drop_column('template_kind')
        batch_op.drop_column('is_template')
