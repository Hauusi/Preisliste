"""Vertriebswissen: Zuständige, feste Felder (Menge, Verweis), Meldung „stimmt nicht mehr“, Synonyme, Suchen ohne Treffer

Revision ID: 0019
Revises: 0018
Create Date: 2026-11-12 18:00:00

"""
from datetime import datetime
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0019'
down_revision: Union[str, Sequence[str], None] = '0018'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Allgemeine Fachbegriffe als Startpunkt; im Tool änder- und löschbar
START_SYNONYMS = [
    ["Mindestbestellmenge", "MOQ", "Mindestmenge", "Mindestabnahme"],
    ["Lieferzeit", "Lieferfrist", "Liefertermin"],
    ["Aufschlag", "Zuschlag", "Mehrpreis"],
]


def upgrade() -> None:
    with op.batch_alter_table('kb_topics', schema=None) as b:
        b.add_column(sa.Column('owner_id', sa.Integer(), nullable=True))
        b.create_foreign_key('fk_kb_topics_owner', 'users', ['owner_id'], ['id'])
    with op.batch_alter_table('kb_facts', schema=None) as b:
        b.add_column(sa.Column('field', sa.String(length=20), nullable=True))
        b.add_column(sa.Column('number', sa.Integer(), nullable=True))
        b.add_column(sa.Column('ref_topic_id', sa.Integer(), nullable=True))
    with op.batch_alter_table('kb_entries', schema=None) as b:
        b.add_column(sa.Column('flagged_by', sa.Integer(), nullable=True))
        b.add_column(sa.Column('flagged_at', sa.DateTime(), nullable=True))
        b.add_column(sa.Column('flag_note', sa.String(length=300), nullable=True))
        b.create_foreign_key('fk_kb_entries_flagged_by', 'users', ['flagged_by'], ['id'])
    syn = op.create_table(
        'kb_synonyms',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('words', sa.JSON(), nullable=False),
        sa.Column('updated_by', sa.Integer(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['updated_by'], ['users.id'], name='fk_kb_synonyms_updated_by'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'kb_search_misses',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('key', sa.String(length=80), nullable=False),
        sa.Column('query', sa.String(length=80), nullable=False),
        sa.Column('count', sa.Integer(), nullable=False),
        sa.Column('last_at', sa.DateTime(), nullable=False),
        sa.Column('last_user', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['last_user'], ['users.id'], name='fk_kb_search_misses_user'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('key'),
    )
    now = datetime.utcnow()
    op.bulk_insert(syn, [{"words": w, "updated_by": None, "updated_at": now} for w in START_SYNONYMS])


def downgrade() -> None:
    op.drop_table('kb_search_misses')
    op.drop_table('kb_synonyms')
    with op.batch_alter_table('kb_entries', schema=None) as b:
        b.drop_constraint('fk_kb_entries_flagged_by', type_='foreignkey')
        b.drop_column('flag_note')
        b.drop_column('flagged_at')
        b.drop_column('flagged_by')
    with op.batch_alter_table('kb_facts', schema=None) as b:
        b.drop_column('ref_topic_id')
        b.drop_column('number')
        b.drop_column('field')
    with op.batch_alter_table('kb_topics', schema=None) as b:
        b.drop_constraint('fk_kb_topics_owner', type_='foreignkey')
        b.drop_column('owner_id')
