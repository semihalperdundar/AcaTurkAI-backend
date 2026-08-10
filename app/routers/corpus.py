"""
Corpus (akademik derleme) yonetim endpoint'leri - admin-only.

akademik_kutuphane_projesi.md'deki CLI script'lerinin ("python _scripts/02_fetch_openalex.py ...")
API karsiligi. Agir/uzun suren isler (OpenAlex harvest, toplu PDF indirme) Celery'e
devredilir; endpoint yalnizca task'i kuyruga yazar ve task_id doner.

GET /api/corpus/stats, Faz 0 kapanis raporunda acik birakilan "corpus'un gercek
durumu bilinmiyor" sorusuna canli bir cevap verir.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.celery_app import (
    corpus_download_oa_pdfs_task,
    corpus_harvest_area_task,
    corpus_import_scimago_year_task,
)
from app.database import get_db
from app.routers.deps import get_current_admin_user
from app.schemas.corpus import (
    DownloadOaPdfsRequest,
    HarvestAreaRequest,
    ImportScimagoRequest,
    TaskQueuedResponse,
)
from app.services.corpus.areas import VALID_AREA_CODES
from app.services.corpus_service import corpus_stats

router = APIRouter(prefix="/api/corpus", tags=["corpus"], dependencies=[Depends(get_current_admin_user)])


@router.get("/areas")
def list_areas():
    return {"areas": list(VALID_AREA_CODES)}


@router.get("/stats")
def get_corpus_stats(db: Session = Depends(get_db)):
    return corpus_stats(db)


@router.post("/harvest/openalex", response_model=TaskQueuedResponse)
def harvest_openalex(payload: HarvestAreaRequest):
    result = corpus_harvest_area_task.delay(
        area_code=payload.area_code,
        year_from=payload.year_from,
        year_to=payload.year_to,
        max_results=payload.max_results,
    )
    return TaskQueuedResponse(task_id=result.id)


@router.post("/download-oa-pdfs", response_model=TaskQueuedResponse)
def download_oa_pdfs(payload: DownloadOaPdfsRequest):
    result = corpus_download_oa_pdfs_task.delay(area_code=payload.area_code, limit=payload.limit)
    return TaskQueuedResponse(task_id=result.id)


@router.post("/harvest/scimago", response_model=TaskQueuedResponse)
def harvest_scimago(payload: ImportScimagoRequest):
    result = corpus_import_scimago_year_task.delay(
        csv_path=payload.csv_path, year=payload.year, set_as_current=payload.set_as_current
    )
    return TaskQueuedResponse(task_id=result.id)
