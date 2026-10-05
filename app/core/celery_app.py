"""
Celery uygulamasi. Spec Bolum 13.1: 'Task Queue: Celery + Redis (analiz isleri icin)'.

Gercek 11-modul analiz motoru Ay 2 kapsaminda buraya eklenecek
(spec Bolum 12.1 - Paralel Analiz Katmani). Su an yalnizca iskelet + saglik testi task'i var.
"""
from celery import Celery

from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "acaturkai",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Europe/Istanbul",
    enable_utc=True,
)


@celery_app.task(name="acaturkai.ping")
def ping() -> str:
    return "pong"


@celery_app.task(name="acaturkai.run_analysis")
def run_analysis(analysis_id: str) -> dict:
    """
    Analiz motoru v1 (structure + lexical + delivery). Is mantigi
    app.services.analysis_service.process_analysis icinde; task yalnizca session yonetir.
    """
    from app.database import SessionLocal
    from app.services.analysis_service import process_analysis

    db = SessionLocal()
    try:
        return process_analysis(db, analysis_id)
    finally:
        db.close()


# --- Corpus toplama task'lari ---------------------------------------------
# akademik_kutuphane_projesi.md modulunun entegrasyonu: OpenAlex harvest,
# Unpaywall OA PDF indirme ve Scimago quartile import'u arka planda calisir
# (Bolum 5 - Faz 2/3'teki "arka planda calisan" is akisiyla birebir ayni amac).

@celery_app.task(name="acaturkai.corpus.harvest_area")
def corpus_harvest_area_task(area_code: str, year_from: int, year_to: int, max_results: int | None = None) -> dict:
    from app.database import SessionLocal
    from app.services.corpus_service import harvest_area

    db = SessionLocal()
    try:
        return harvest_area(db, area_code=area_code, year_from=year_from, year_to=year_to, max_results=max_results)
    finally:
        db.close()


@celery_app.task(name="acaturkai.corpus.download_oa_pdfs")
def corpus_download_oa_pdfs_task(area_code: str | None = None, limit: int = 100) -> dict:
    from app.database import SessionLocal
    from app.services.corpus_service import download_oa_pdfs

    db = SessionLocal()
    try:
        return download_oa_pdfs(db, area_code=area_code, limit=limit)
    finally:
        db.close()


@celery_app.task(name="acaturkai.corpus.import_scimago_year")
def corpus_import_scimago_year_task(csv_path: str, year: int, set_as_current: bool = False) -> dict:
    from app.database import SessionLocal
    from app.services.corpus_service import import_scimago_year

    db = SessionLocal()
    try:
        return import_scimago_year(db, csv_path=csv_path, year=year, set_as_current=set_as_current)
    finally:
        db.close()
