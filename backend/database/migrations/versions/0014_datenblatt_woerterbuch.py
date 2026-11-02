"""Wörterbuch für den Datenblatt-Import (Herstellerbegriff -> B&B-Begriff, pro Hersteller)

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-02 10:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0014'
down_revision: Union[str, Sequence[str], None] = '0013'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'datasheet_terms',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(length=12), nullable=False),
        sa.Column('source', sa.String(length=120), nullable=False),
        sa.Column('target', sa.String(length=200), nullable=False),
        sa.Column('manufacturer', sa.String(length=200), server_default='', nullable=False),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], name='fk_datasheet_terms_user'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('kind', 'source', 'manufacturer', name='uq_datasheet_terms'),
    )


def downgrade() -> None:
    op.drop_table('datasheet_terms')
