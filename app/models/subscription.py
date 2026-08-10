from datetime import datetime

from sqlalchemy import String, DateTime, Boolean, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import uuid_pk


class Subscription(Base):
    """Spec Bolum 14 - subscriptions (Stripe abonelik takibi)."""

    __tablename__ = "subscriptions"

    id = uuid_pk()
    user_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(255))
    plan: Mapped[str | None] = mapped_column(String(50))  # 'starter' | 'academic'
    status: Mapped[str | None] = mapped_column(String(50))  # 'active' | 'canceled' | 'past_due'
    current_period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()")

    user = relationship("User", back_populates="subscriptions")
