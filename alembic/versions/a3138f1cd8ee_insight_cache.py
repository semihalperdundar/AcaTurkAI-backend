"""insight_cache

Revision ID: a3138f1cd8ee
Revises: d1f440167fdd
Create Date: 2026-10-12 15:00:00

Zengin yol (LLM icgorusu) icin icerik-ozeti anahtarli onbellek tablosu.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a3138f1cd8ee'
down_revision: Union[str, None] = 'd1f440167fdd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'insight_cache',
        sa.Column('cache_key', sa.String(length=255), nullable=False),
        sa.Column('pack', sa.String(length=100), nullable=False),
        sa.Column('insights', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('cache_key'),
    )


def downgrade() -> None:
    op.drop_table('insight_cache')
