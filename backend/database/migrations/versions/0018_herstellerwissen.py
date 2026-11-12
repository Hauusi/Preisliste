"""Vertriebswissen: gemeinsame Themen (Hersteller, Artikelgruppen), Angaben, Einträge, Folgen, Verlauf

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-12 12:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0018'
down_revision: Union[str, Sequence[str], None] = '0017'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'kb_topics',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(length=16), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('key', sa.String(length=120), nullable=False),
        sa.Column('aliases', sa.JSON(), nullable=False),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_by', sa.Integer(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], name='fk_kb_topics_created_by'),
        sa.ForeignKeyConstraint(['updated_by'], ['users.id'], name='fk_kb_topics_updated_by'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('kind', 'key', name='uq_kb_topics_kind_key'),
    )
    op.create_table(
        'kb_facts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('topic_id', sa.Integer(), nullable=False),
        sa.Column('label', sa.String(length=60), nullable=False),
        sa.Column('value', sa.String(length=200), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('updated_by', sa.Integer(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['topic_id'], ['kb_topics.id'], name='fk_kb_facts_topic', ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['updated_by'], ['users.id'], name='fk_kb_facts_updated_by'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_kb_facts_topic_id', 'kb_facts', ['topic_id'])
    op.create_table(
        'kb_entries',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('type', sa.String(length=16), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('original', sa.Text(), nullable=True),
        sa.Column('private', sa.Boolean(), server_default='0', nullable=False),
        sa.Column('author_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_by', sa.Integer(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('checked_by', sa.Integer(), nullable=True),
        sa.Column('checked_at', sa.DateTime(), nullable=False),
        sa.Column('topic_ids', sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(['author_id'], ['users.id'], name='fk_kb_entries_author'),
        sa.ForeignKeyConstraint(['updated_by'], ['users.id'], name='fk_kb_entries_updated_by'),
        sa.ForeignKeyConstraint(['checked_by'], ['users.id'], name='fk_kb_entries_checked_by'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_kb_entries_author_id', 'kb_entries', ['author_id'])
    op.create_table(
        'kb_unfollow',
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('topic_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name='fk_kb_unfollow_user', ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['topic_id'], ['kb_topics.id'], name='fk_kb_unfollow_topic', ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id', 'topic_id'),
    )
    op.create_table(
        'kb_changes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('object', sa.String(length=16), nullable=False),
        sa.Column('object_id', sa.Integer(), nullable=False),
        sa.Column('topic_id', sa.Integer(), nullable=True),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('at', sa.DateTime(), nullable=False),
        sa.Column('action', sa.String(length=16), nullable=False),
        sa.Column('before', sa.Text(), nullable=True),
        sa.Column('after', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name='fk_kb_changes_user'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_kb_changes_object_id', 'kb_changes', ['object_id'])
    op.create_index('ix_kb_changes_topic_id', 'kb_changes', ['topic_id'])


def downgrade() -> None:
    op.drop_table('kb_changes')
    op.drop_table('kb_unfollow')
    op.drop_table('kb_entries')
    op.drop_table('kb_facts')
    op.drop_table('kb_topics')
