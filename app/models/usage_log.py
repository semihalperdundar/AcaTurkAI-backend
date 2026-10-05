from datetime import datetime

from sqlalchemy import String, DateTime, ForeignKey, JSON, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import uuid_pk

JsonType = JSONB().with_variant(JSON(), "sqlite")


class UsageLog(Base):
    """Spec Bolum 14 - usage_logs. Plan limiti kontrolu (Free: 1/ay, Starter: 5/ay) bu tablo uzerinden yapilir."""

    __tablename__ = "usage_logs"

    id = uuid_pk()
    user_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    action: Mapped[str | None] = mapped_column(String(100))  # 'analysis' | 'pdf_export' | 'revision_view'
    analysis_id: Mapped[UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("analyses.id"))
    log_metadata: Mapped[dict | None] = mapped_column("metadata", JsonType)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="usage_logs")
