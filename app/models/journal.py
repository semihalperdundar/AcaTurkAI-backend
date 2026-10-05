from datetime import datetime

from sqlalchemy import String, DateTime, Float, Integer, Boolean, JSON, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import uuid_pk

JsonType = JSONB().with_variant(JSON(), "sqlite")


class Journal(Base):
    """Spec Bolum 14 - journals (SCImago + OpenAlex kaynakli dergi veritabani)."""

    __tablename__ = "journals"

    id = uuid_pk()
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    issn: Mapped[str | None] = mapped_column(String(20))
    eissn: Mapped[str | None] = mapped_column(String(20))
    quartile: Mapped[str | None] = mapped_column(String(5))  # Q1-Q4
    sjr_score: Mapped[float | None] = mapped_column(Float)
    h_index: Mapped[int | None] = mapped_column(Integer)
    total_cites_3y: Mapped[int | None] = mapped_column(Integer)
    field: Mapped[str | None] = mapped_column(String(100))
    country: Mapped[str | None] = mapped_column(String(100))
    language: Mapped[str | None] = mapped_column(String(50))
    is_turkey_journal: Mapped[bool] = mapped_column(Boolean, default=False)
    openalex_id: Mapped[str | None] = mapped_column(String(100))
    norm_profile: Mapped[dict | None] = mapped_column(JsonType)
    last_updated: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    works = relationship("CorpusWork", back_populates="journal")
