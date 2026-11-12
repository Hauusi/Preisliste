"""Vertriebswissen: Firmengruppen (Muttergesellschaft je Hersteller)

Revision ID: 0021
Revises: 0020
Create Date: 2026-11-13 12:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0021'
down_revision: Union[str, Sequence[str], None] = '0020'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('kb_topics', schema=None) as b:
        b.add_column(sa.Column('parent_id', sa.Integer(), nullable=True))
        b.create_foreign_key('fk_kb_topics_parent', 'kb_topics', ['parent_id'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    with op.batch_alter_table('kb_topics', schema=None) as b:
        b.drop_constraint('fk_kb_topics_parent', type_='foreignkey')
        b.drop_column('parent_id')
