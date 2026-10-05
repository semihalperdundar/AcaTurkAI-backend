"""
Analiz olusturma is mantigi.

Ay 1 kapsami: dosyayi al, Analysis kaydi olustur, Celery task'ini tetikle.
Gercek dosya depolama (S3/R2) ve gercek 11-modul analiz motoru Ay 2 kapsamindadir
(spec Bolum 12.1, Bolum 13.1 - 'Dosya Depolama: AWS S3 veya Cloudflare R2').

Su an dosyalar local diskte gecici olarak saklanir (UPLOAD_DIR); production'da
bu fonksiyon S3/R2 client'i ile degistirilmelidir.
"""
import logging
import time
import uuid
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.core.celery_app import run_analysis
from app.models.analysis import Analysis
from app.services.analysis.engine import analyze_text
from app.services.analysis.text_extractor import TextExtractionError, extract_text

logger = logging.getLogger(__name__)

UPLOAD_DIR = Path("uploads")
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt"}
TITLE_MAX_WORDS = 30


class AnalysisError(Exception):
    pass


def upload_path(analysis_id: uuid.UUID, file_name: str | None) -> Path:
    """Tek dogruluk kaynagi: yukleme ve worker ayni yolu buradan turetir (S3/R2'de object key olacak)."""
    return UPLOAD_DIR / f"{analysis_id}{Path(file_name or '').suffix.lower()}"


def create_analysis_from_upload(
    db: Session, user_id: uuid.UUID, file: UploadFile, selected_field: str
) -> Analysis:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise AnalysisError(
            f"Desteklenmeyen dosya turu: {suffix or 'bilinmiyor'}. Kabul edilenler: PDF, DOCX, TXT."
        )

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    analysis_id = uuid.uuid4()
    dest_path = upload_path(analysis_id, file.filename)

    content = file.file.read()
    dest_path.write_bytes(content)

    analysis = Analysis(
        id=analysis_id,
        user_id=user_id,
        file_name=file.filename,
        file_size_kb=len(content) // 1024,
        selected_field=selected_field,
        status="pending",
    )
    db.add(analysis)
    db.commit()
    db.refresh(analysis)

    # Celery worker calisiyorsa gercek isi orada yapar; calismiyorsa bu cagri
    # sadece kuyruga yazar, hata firlatmaz (broker erisimi olmadan da API ayakta kalir).
    try:
        run_analysis.delay(str(analysis.id))
    except Exception:
        pass

    return analysis


def _guess_title(text: str) -> str | None:
    """Ilk anlamli satir genellikle makale basligidir (Ay 2: score_title modulu dogrular)."""
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped and len(stripped.split()) <= TITLE_MAX_WORDS:
            return stripped[:500]
    return None


def process_analysis(db: Session, analysis_id: uuid.UUID | str) -> dict:
    """
    Worker giris noktasi. Durum gecisleri: pending -> processing -> completed | failed.

    - completed kayit tekrar gelirse (Celery redelivery) atlanir -> idempotent.
    - Hata durumunda kayit HER ZAMAN failed'a cekilir; kullaniciya gosterilebilir
      mesaj full_report['error'] icinde. Beklenmeyen hata ayrintisi yalnizca loglanir.
    """
    analysis_uuid = analysis_id if isinstance(analysis_id, uuid.UUID) else uuid.UUID(str(analysis_id))
    analysis = db.get(Analysis, analysis_uuid)
    if analysis is None:
        return {"status": "not_found", "analysis_id": str(analysis_uuid)}
    if analysis.status == "completed":
        return {"status": "skipped_already_completed", "analysis_id": str(analysis_uuid)}

    analysis.status = "processing"
    db.commit()
    started = time.perf_counter()

    try:
        extracted = extract_text(upload_path(analysis.id, analysis.file_name))
        report = analyze_text(extracted.text, field=analysis.selected_field)

        modules = report["modules"]
        analysis.word_count = extracted.word_count
        analysis.language = report["language"]
        analysis.title = analysis.title or _guess_title(extracted.text)
        analysis.score_structure = modules["structure"]["score"]
        analysis.score_lexical = modules["lexical"]["score"]
        analysis.score_delivery = modules["delivery"]["score"]
        analysis.rejection_risk_score = report["rejection_risk_score"]
        analysis.full_report = report
        analysis.revision_suggestions = {name: m["feedback"] for name, m in modules.items()}
        analysis.status = "completed"
        error_payload = None
    except TextExtractionError as exc:
        db.rollback()
        error_payload = {"type": "text_extraction", "message": str(exc)}
    except Exception:  # noqa: BLE001 - worker asla kaydi 'processing'de birakmamali
        db.rollback()
        logger.exception("Analiz basarisiz: %s", analysis_uuid)
        error_payload = {"type": "internal", "message": "Analiz sirasinda beklenmeyen bir hata olustu."}

    if error_payload is not None:
        analysis = db.get(Analysis, analysis_uuid)
        analysis.status = "failed"
        analysis.full_report = {"error": error_payload}

    analysis.processing_time_ms = int((time.perf_counter() - started) * 1000)
    db.commit()
    return {
        "status": analysis.status,
        "analysis_id": str(analysis_uuid),
        "rejection_risk_score": analysis.rejection_risk_score,
        "error": error_payload,
    }
