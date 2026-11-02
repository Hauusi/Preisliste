"""Design-Vorlagen als Original-PDF mit abgelesenem Profil (statt nachgebauter Datenblätter)

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-03 10:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0016'
down_revision: Union[str, Sequence[str], None] = '0015'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'datasheet_examples',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('filename', sa.String(length=200), nullable=False),
        sa.Column('title', sa.String(length=200), server_default='', nullable=False),
        sa.Column('kind', sa.String(length=60), nullable=True),
        sa.Column('profile', sa.JSON(), nullable=False),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], name='fk_datasheet_examples_user'),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('datasheet_examples')
