from datetime import datetime

from sqlalchemy import String, DateTime, Float, Integer, ForeignKey, JSON
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import uuid_pk

# JSONB sadece Postgres'te calisir; sqlite ile test icin generic JSON'a dus.
JsonType = JSONB().with_variant(JSON(), "sqlite")


class Analysis(Base):
    """Spec Bolum 14 - analyses tablosu. 11 modulun skorlari ayri kolonlarda tutulur."""

    __tablename__ = "analyses"

    id = uuid_pk()
    user_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))

    title: Mapped[str | None] = mapped_column(String(500))
    file_name: Mapped[str | None] = mapped_column(String(255))
    file_size_kb: Mapped[int | None] = mapped_column(Integer)
    word_count: Mapped[int | None] = mapped_column(Integer)
    detected_field: Mapped[str | None] = mapped_column(String(100))
    selected_field: Mapped[str | None] = mapped_column(String(100))
    language: Mapped[str] = mapped_column(String(10), default="tr")

    # Skorlar (spec Bolum 5 - 11 analiz modulu, 0-100)
    rejection_risk_score: Mapped[float | None] = mapped_column(Float)
    score_title: Mapped[float | None] = mapped_column(Float)
    score_abstract: Mapped[float | None] = mapped_column(Float)
    score_structure: Mapped[float | None] = mapped_column(Float)
    score_delivery: Mapped[float | None] = mapped_column(Float)
    score_lexical: Mapped[float | None] = mapped_column(Float)
    score_literature: Mapped[float | None] = mapped_column(Float)
    score_originality: Mapped[float | None] = mapped_column(Float)
    score_methodology: Mapped[float | None] = mapped_column(Float)
    score_findings: Mapped[float | None] = mapped_column(Float)
    score_conclusions: Mapped[float | None] = mapped_column(Float)
    score_references: Mapped[float | None] = mapped_column(Float)

    full_report: Mapped[dict | None] = mapped_column(JsonType)
    revision_suggestions: Mapped[dict | None] = mapped_column(JsonType)
    journal_matches: Mapped[dict | None] = mapped_column(JsonType)

    status: Mapped[str] = mapped_column(String(50), default="pending")  # pending/processing/completed/failed
    processing_time_ms: Mapped[int | None] = mapped_column(Integer)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()")

    user = relationship("User", back_populates="analyses")
    versions = relationship("AnalysisVersion", back_populates="analysis")


class ThesisProject(Base):
    """Spec Bolum 14 - thesis_projects (Academic plan: tez takip paneli)."""

    __tablename__ = "thesis_projects"

    id = uuid_pk()
    user_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    title: Mapped[str | None] = mapped_column(String(500))
    field: Mapped[str | None] = mapped_column(String(100))
    target_journal: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()")

    user = relationship("User", back_populates="thesis_projects")
    versions = relationship("AnalysisVersion", back_populates="project")


class AnalysisVersion(Base):
    """Spec Bolum 14 - analysis_versions (surum karsilastirma)."""

    __tablename__ = "analysis_versions"

    id = uuid_pk()
    project_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("thesis_projects.id"))
    analysis_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("analyses.id"))
    version_number: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()")

    project = relationship("ThesisProject", back_populates="versions")
    analysis = relationship("Analysis", back_populates="versions")
