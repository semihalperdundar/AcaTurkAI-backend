"""
Analiz olusturma is mantigi.

Ay 1 kapsami: dosyayi al, Analysis kaydi olustur, Celery task'ini tetikle.
Gercek dosya depolama (S3/R2) ve gercek 11-modul analiz motoru Ay 2 kapsamindadir
(spec Bolum 12.1, Bolum 13.1 - 'Dosya Depolama: AWS S3 veya Cloudflare R2').

Su an dosyalar local diskte gecici olarak saklanir (UPLOAD_DIR); production'da
bu fonksiyon S3/R2 client'i ile degistirilmelidir.
"""
import uuid
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.core.celery_app import run_analysis
from app.models.analysis import Analysis

UPLOAD_DIR = Path("uploads")
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt"}


class AnalysisError(Exception):
    pass


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
    dest_path = UPLOAD_DIR / f"{analysis_id}{suffix}"

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
