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
    # Add columns with server defaults to handle existing rows
    op.add_column('user_settings', sa.Column('language', sa.String(length=10), server_default='en', nullable=False))
    op.add_column('user_settings', sa.Column('max_file_size', sa.Integer(), server_default='50', nullable=False))
    
    # Remove server defaults after population to keep them in Python code only (optional but cleaner)
    op.alter_column('user_settings', 'language', server_default=None)
    op.alter_column('user_settings', 'max_file_size', server_default=None)


def downgrade() -> None:
    op.drop_column('user_settings', 'max_file_size')
    op.drop_column('user_settings', 'language')
