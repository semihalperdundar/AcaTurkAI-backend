from datetime import datetime

from sqlalchemy import JSON, DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

JsonType = JSONB().with_variant(JSON(), "sqlite")


class InsightCache(Base):
    """LLM icgoru onbellegi. Anahtar icerik ozetidir (bkz. app/services/insights/cache.py):
    ayni makale + ayni motor/istem surumu + ayni profil -> ayni icgoru, 0 token.

    Kullaniciya bagli DEGILDIR: ayni metni yukleyen iki kullanici ayni (metinden turetilmis)
    icgoruyu alir; icgoru yalnizca metindeki alintilari icerir, kisisel veri tasimaz.
    """

    __tablename__ = "insight_cache"

    cache_key: Mapped[str] = mapped_column(String(255), primary_key=True)
    pack: Mapped[str] = mapped_column(String(100))
    insights: Mapped[list] = mapped_column(JsonType)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
