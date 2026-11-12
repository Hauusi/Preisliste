"""Vertriebswissen: Artikelgruppen je Hersteller (Sortiment)

Revision ID: 0022
Revises: 0021
Create Date: 2026-11-12 14:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0022'
down_revision: Union[str, Sequence[str], None] = '0021'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'kb_assortment',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('maker_id', sa.Integer(), sa.ForeignKey('kb_topics.id', ondelete='CASCADE', name='fk_kb_assortment_maker'), nullable=False),
        sa.Column('group_id', sa.Integer(), sa.ForeignKey('kb_topics.id', ondelete='CASCADE', name='fk_kb_assortment_group'), nullable=False),
        sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id', name='fk_kb_assortment_created_by'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('maker_id', 'group_id', name='uq_kb_assortment'),
    )
    op.create_index('ix_kb_assortment_maker_id', 'kb_assortment', ['maker_id'])
    op.create_index('ix_kb_assortment_group_id', 'kb_assortment', ['group_id'])


def downgrade() -> None:
    op.drop_index('ix_kb_assortment_group_id', table_name='kb_assortment')
    op.drop_index('ix_kb_assortment_maker_id', table_name='kb_assortment')
    op.drop_table('kb_assortment')
