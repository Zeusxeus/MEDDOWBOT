"""add upload_as_video to user_settings

Revision ID: 8ce082938721
Revises: b88a3ffca6cb
Create Date: 2026-04-24 19:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8ce082938721'
down_revision: Union[str, None] = 'b88a3ffca6cb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Get existing columns to avoid duplicate column errors
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [c['name'] for c in inspector.get_columns('user_settings')]

    # Use batch_alter_table for SQLite compatibility
    with op.batch_alter_table('user_settings', schema=None) as batch_op:
        if 'upload_as_video' not in columns:
            batch_op.add_column(sa.Column('upload_as_video', sa.Boolean(), server_default='0', nullable=False))


def downgrade() -> None:
    with op.batch_alter_table('user_settings', schema=None) as batch_op:
        batch_op.drop_column('upload_as_video')
