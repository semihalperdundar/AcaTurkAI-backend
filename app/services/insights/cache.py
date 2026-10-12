"""
Icerik-ozeti anahtarli icgoru onbellegi.

Anahtar = sha256(ctx.text) : ENGINE_VERSION : prompt_id : profile.name
  - metin degisirse          -> yeni anahtar
  - motor surumu degisirse   -> kural metrikleri (LLM'e giden on bulgular) degismis olabilir
  - istem surumu degisirse   -> "claim_evidence@2" eski cikti kullanilmaz
  - profil degisirse         -> alana ozgu paket/parametre farki
Boylece ayni makale tekrar yuklendiginde 0 token harcanir ve ayni geri bildirim doner.
"""
from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from app.models.insight_cache import InsightCache
from app.services.analysis.engine import ENGINE_VERSION
from app.services.insights.schema import Insight

if TYPE_CHECKING:
    from app.services.analysis.context import Context
    from app.services.analysis.profiles import DomainProfile, InsightPack


def insight_cache_key(ctx: Context, profile: DomainProfile, pack: InsightPack) -> str:
    text_digest = hashlib.sha256(ctx.text.encode("utf-8")).hexdigest()
    return f"{text_digest}:{ENGINE_VERSION}:{pack.prompt_id}:{profile.name}"


def get_cached(db: Session, key: str) -> list[Insight] | None:
    row = db.get(InsightCache, key)
    return None if row is None else [Insight.model_validate(item) for item in row.insights]


def put_cached(db: Session, key: str, pack: InsightPack, insights: list[Insight]) -> None:
    """Yalnizca dogrulamadan GECMIS icgoruler yazilir (cagiran sorumlu)."""
    db.merge(InsightCache(cache_key=key, pack=pack.name, insights=[i.model_dump() for i in insights]))
