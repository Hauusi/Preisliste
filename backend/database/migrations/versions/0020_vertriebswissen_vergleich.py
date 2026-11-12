"""Vertriebswissen: Artikelvergleich je Artikelgruppe (Hersteller, Artikel, Punkte je Kriterium)

Revision ID: 0020
Revises: 0019
Create Date: 2026-11-12 20:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0020'
down_revision: Union[str, Sequence[str], None] = '0019'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('kb_topics', schema=None) as b:
        b.add_column(sa.Column('criteria', sa.JSON(), nullable=True))
    op.create_table(
        'kb_products',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('group_id', sa.Integer(), nullable=False),
        sa.Column('maker_id', sa.Integer(), nullable=True),
        sa.Column('artnr', sa.String(length=60), nullable=False),
        sa.Column('name', sa.String(length=160), nullable=False),
        sa.Column('scores', sa.JSON(), nullable=False),
        sa.Column('note', sa.String(length=500), nullable=True),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_by', sa.Integer(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['group_id'], ['kb_topics.id'], name='fk_kb_products_group', ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['maker_id'], ['kb_topics.id'], name='fk_kb_products_maker', ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], name='fk_kb_products_created_by'),
        sa.ForeignKeyConstraint(['updated_by'], ['users.id'], name='fk_kb_products_updated_by'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_kb_products_group_id', 'kb_products', ['group_id'])
    op.create_index('ix_kb_products_maker_id', 'kb_products', ['maker_id'])


def downgrade() -> None:
    op.drop_table('kb_products')
    with op.batch_alter_table('kb_topics', schema=None) as b:
        b.drop_column('criteria')
