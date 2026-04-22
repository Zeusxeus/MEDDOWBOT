"""add missing columns to user_settings

Revision ID: b88a3ffca6cb
Revises: 17be663c2123
Create Date: 2026-04-21 17:15:54.771624

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b88a3ffca6cb'
down_revision: Union[str, None] = '17be663c2123'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Use batch_alter_table for SQLite compatibility
    with op.batch_alter_table('user_settings', schema=None) as batch_op:
        batch_op.add_column(sa.Column('language', sa.String(length=10), server_default='en', nullable=False))
        batch_op.add_column(sa.Column('max_file_size', sa.Integer(), server_default='50', nullable=False))
        
    # We leave the server defaults as is for SQLite to avoid complex table recreation just to drop defaults.
    # On PostgreSQL these could be dropped easily, but batch mode handles the logic for us.


def downgrade() -> None:
    with op.batch_alter_table('user_settings', schema=None) as batch_op:
        batch_op.drop_column('max_file_size')
        batch_op.drop_column('language')
