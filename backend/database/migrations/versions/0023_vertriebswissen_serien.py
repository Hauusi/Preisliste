"""Vertriebswissen: Serien (Thema-Art „serie“ mit Artikelgruppe und Hersteller)

Revision ID: 0023
Revises: 0022
Create Date: 2026-11-12 16:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0023'
down_revision: Union[str, Sequence[str], None] = '0022'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('kb_topics', schema=None) as b:
        b.add_column(sa.Column('maker_id', sa.Integer(), nullable=True))
        b.create_foreign_key('fk_kb_topics_maker', 'kb_topics', ['maker_id'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    with op.batch_alter_table('kb_topics', schema=None) as b:
        b.drop_constraint('fk_kb_topics_maker', type_='foreignkey')
        b.drop_column('maker_id')
