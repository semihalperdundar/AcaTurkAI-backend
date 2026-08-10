from datetime import datetime

from sqlalchemy import String, DateTime, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import uuid_pk


class User(Base):
    """Spec Bolum 14 - users tablosu."""

    __tablename__ = "users"

    id = uuid_pk()
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str | None] = mapped_column(String(255), nullable=True)
    full_name: Mapped[str | None] = mapped_column(String(255))
    institution: Mapped[str | None] = mapped_column(String(255))

    # spec: 'education' | 'social_sciences' | 'engineering' | 'health' | 'law' | 'business'
    primary_field: Mapped[str | None] = mapped_column(String(100))
    # spec: 'masters_student' | 'phd' | 'faculty' | vb.
    academic_role: Mapped[str | None] = mapped_column(String(100))

    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    subscription_tier: Mapped[str] = mapped_column(String(50), default="free")
    subscription_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stripe_customer_id: Mapped[str | None] = mapped_column(String(255))
    orcid_id: Mapped[str | None] = mapped_column(String(50))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()")

    analyses = relationship("Analysis", back_populates="user", cascade="all, delete-orphan")
    thesis_projects = relationship("ThesisProject", back_populates="user")
    subscriptions = relationship("Subscription", back_populates="user")
    usage_logs = relationship("UsageLog", back_populates="user")
