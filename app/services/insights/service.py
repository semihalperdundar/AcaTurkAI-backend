"""
Zengin yol is akisi (worker giris noktasi: generate_insights_task).

  analiz (completed) -> metin -> Context -> profil -> InsightPack'ler
    -> her paket: onbellek? -> degilse istemci -> GroundingValidator -> onbellege yaz
    -> full_report["insights"]

Kurallar:
  - Kural skorlarina ve score_* kolonlarina DOKUNULMAZ; yalnizca full_report["insights"] yazilir.
  - Icgoru hatasi analizi bozmaz: insights.status = "failed", analiz "completed" kalir.
  - Onbellege yalnizca dogrulamadan gecmis icgoruler yazilir.
"""
from __future__ import annotations

import logging
import uuid

from sqlalchemy.orm import Session

from app.models.analysis import Analysis
from app.services.analysis.context import build_context
from app.services.analysis.engine import ENGINE_VERSION
from app.services.analysis.profiles import get_profile
from app.services.analysis.text_extractor import extract_text
from app.services.insights.cache import get_cached, insight_cache_key, put_cached
from app.services.insights.client import InsightClient, get_insight_client
from app.services.insights.grounding import validate_grounding

logger = logging.getLogger(__name__)


def _write_insights(db: Session, analysis: Analysis, payload: dict) -> None:
    # JSON kolonunda yerinde degisiklik izlenmez -> yeni dict ata.
    analysis.full_report = {**(analysis.full_report or {}), "insights": payload}
    db.commit()


def generate_insights(db: Session, analysis_id: uuid.UUID | str, client: InsightClient | None = None) -> dict:
    # Dongusel import'u onle: analysis_service, celery_app'i import eder.
    from app.services.analysis_service import upload_path

    analysis_uuid = analysis_id if isinstance(analysis_id, uuid.UUID) else uuid.UUID(str(analysis_id))
    analysis = db.get(Analysis, analysis_uuid)
    if analysis is None:
        return {"status": "not_found", "analysis_id": str(analysis_uuid)}
    if analysis.status != "completed":
        return {"status": "skipped_not_completed", "analysis_id": str(analysis_uuid)}

    try:
        ctx = build_context(extract_text(upload_path(analysis.id, analysis.file_name)).text)
        profile = get_profile(analysis.selected_field)
        rule_modules = (analysis.full_report or {}).get("modules", {})
        client = client or get_insight_client()

        items: list[dict] = []
        packs: list[dict] = []
        for pack in profile.insight_packs:
            key = insight_cache_key(ctx, profile, pack)
            cached = get_cached(db, key)
            if cached is not None:
                accepted, rejected_count = cached, 0
            else:
                raw = client.generate(pack, ctx, rule_modules)
                result = validate_grounding(raw, ctx, allowed_modules=pack.modules)
                accepted, rejected_count = result.accepted, len(result.rejected)
                put_cached(db, key, pack, accepted)
            items.extend(i.model_dump() for i in accepted)
            packs.append({
                "name": pack.name,
                "prompt_id": pack.prompt_id,
                "cache_hit": cached is not None,
                "rejected": rejected_count,
            })
    except Exception:  # noqa: BLE001 - icgoru hatasi analizi asla bozmamali
        db.rollback()
        logger.exception("Icgoru uretimi basarisiz: %s", analysis_uuid)
        analysis = db.get(Analysis, analysis_uuid)
        failed = {"status": "failed", "engine_version": ENGINE_VERSION, "items": [], "packs": []}
        _write_insights(db, analysis, failed)
        return {"status": "failed", "analysis_id": str(analysis_uuid)}

    _write_insights(db, analysis, {
        "status": "ready",
        "engine_version": ENGINE_VERSION,
        "profile": profile.name,
        "items": items,
        "packs": packs,
    })
    return {"status": "ready", "analysis_id": str(analysis_uuid), "insights": len(items)}
