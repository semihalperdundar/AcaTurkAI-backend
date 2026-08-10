"""
Corpus toplama orchestration katmani.

akademik_kutuphane_projesi.md'deki CLI script'lerinin (02_fetch_openalex.py,
03_download_oa_pdfs.py, 04_scimago_import.py) is mantigini, mevcut backend'in
Postgres + SQLAlchemy session mimarisine tasir. Ayri bir SQLite/yerel disk
kutuphanesi yerine dogrudan uygulamanin ana veritabanini kullanir ki
Analysis/Journal modelleriyle ayni corpus'a referans verilebilsin (spec
Bolum 12 - alan normu hesaplamalari bu corpus'u besler).

Celery task'lari (app/core/celery_app.py) bu fonksiyonlari sarar.
"""
import logging
import time
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.corpus import Author, CorpusWork, JournalQuartileHistory, SOURCE_TIER_OPEN_ACCESS, WorkAuthor
from app.models.journal import Journal
from app.services.corpus import openalex_client, scimago_import, unpaywall_client
from app.services.corpus.areas import AREA_CONCEPTS, VALID_AREA_CODES

logger = logging.getLogger("acaturkai.corpus")

CORPUS_PDF_DIR = Path("corpus_pdfs")  # Ay 2'de S3/R2'ye tasinacak (bkz. analysis_service.py'deki ayni not)
DOWNLOAD_SLEEP_SECONDS = 1.0  # Bolum 8.3 "insan hizinda" onerisi - yayinci sitelerini rahatsiz etmemek icin


class CorpusServiceError(Exception):
    pass


def _resolve_quartile_at_publication(db: Session, issn: str | None, year: int | None) -> str | None:
    if not issn or not year:
        return None
    history = (
        db.query(JournalQuartileHistory)
        .filter(JournalQuartileHistory.issn == issn, JournalQuartileHistory.year == year)
        .order_by(JournalQuartileHistory.sjr_score.desc())
        .first()
    )
    if history:
        return history.quartile
    # Gecmis yil verisi yoksa, guncel Journal snapshot'ina dus (yaklasik deger).
    journal = db.query(Journal).filter(Journal.issn == issn).one_or_none()
    return journal.quartile if journal else None


def _upsert_author(db: Session, author_data: dict) -> Author | None:
    openalex_id = author_data.get("openalex_id")
    if not openalex_id:
        return None
    author = db.query(Author).filter(Author.openalex_id == openalex_id).one_or_none()
    if author is None:
        author = Author(
            openalex_id=openalex_id,
            full_name=author_data.get("full_name"),
            orcid=author_data.get("orcid"),
        )
        db.add(author)
        db.flush()
    return author


def harvest_area(
    db: Session,
    area_code: str,
    year_from: int,
    year_to: int,
    max_results: int | None = None,
    subarea: str | None = None,
) -> dict:
    """
    OpenAlex'ten bir alanin (area_code) belirtilen yil araligindaki eserlerini
    ceker, corpus_works + corpus_authors + corpus_work_authors tablolarina yazar.

    Donen: {"area": area_code, "fetched": int, "created": int, "updated": int}
    """
    if area_code not in VALID_AREA_CODES:
        raise CorpusServiceError(f"Gecersiz alan kodu: {area_code}. Gecerli kodlar: {VALID_AREA_CODES}")

    settings = get_settings()
    concept_ids = AREA_CONCEPTS[area_code]

    fetched = created = updated = 0
    for work in openalex_client.iter_works(
        concept_ids=concept_ids,
        year_from=year_from,
        year_to=year_to,
        email=settings.OPENALEX_EMAIL,
        max_results=max_results,
    ):
        fetched += 1
        fields = openalex_client.extract_fields(work)

        corpus_work = db.query(CorpusWork).filter(CorpusWork.openalex_id == fields["openalex_id"]).one_or_none()
        quartile = _resolve_quartile_at_publication(db, fields["journal_issn"], fields["publication_year"])

        if corpus_work is None:
            corpus_work = CorpusWork(
                openalex_id=fields["openalex_id"],
                doi=fields["doi"],
                title=fields["title"],
                abstract=fields["abstract"],
                publication_year=fields["publication_year"],
                journal_name=fields["journal_name"],
                journal_issn=fields["journal_issn"],
                cited_by_count=fields["cited_by_count"],
                is_oa=fields["is_oa"],
                oa_url=fields["oa_url"],
                primary_area=area_code,
                primary_subarea=subarea,
                quartile_at_publication=quartile,
                source_tier=SOURCE_TIER_OPEN_ACCESS,
                raw_json=fields["raw_json"],
            )
            db.add(corpus_work)
            db.flush()
            created += 1
        else:
            corpus_work.cited_by_count = fields["cited_by_count"]
            corpus_work.is_oa = fields["is_oa"]
            corpus_work.oa_url = fields["oa_url"]
            corpus_work.quartile_at_publication = quartile
            updated += 1

        for author_data in fields["authors"]:
            author = _upsert_author(db, author_data)
            if author is None:
                continue
            link = (
                db.query(WorkAuthor)
                .filter(WorkAuthor.work_id == corpus_work.id, WorkAuthor.author_id == author.id)
                .one_or_none()
            )
            if link is None:
                db.add(WorkAuthor(work_id=corpus_work.id, author_id=author.id, position=author_data["position"]))

        if fetched % 50 == 0:
            db.commit()
            logger.info("corpus.harvest area=%s fetched=%d created=%d updated=%d", area_code, fetched, created, updated)

    db.commit()
    return {"area": area_code, "fetched": fetched, "created": created, "updated": updated}


def download_oa_pdfs(db: Session, area_code: str | None = None, limit: int = 100) -> dict:
    """
    is_oa=True ve henuz indirilmemis (pdf_storage_key IS NULL) eserler icin
    Unpaywall'dan yasal OA PDF linkini bulur ve yerel diske indirir
    (Ay 2'de S3/R2'ye yazacak sekilde degistirilecek - bkz. analysis_service.py).

    commercial_use_allowed alani Unpaywall lisans bilgisine gore otomatik set edilir;
    lisans bilinmiyorsa veya ticari-dostu degilse False kalir (spec Bolum 10-11 - TDM/OA ayrimi).
    """
    settings = get_settings()
    if not settings.OPENALEX_EMAIL:
        raise CorpusServiceError("OPENALEX_EMAIL (.env) bos - Unpaywall polite pool icin gerekli.")

    query = db.query(CorpusWork).filter(CorpusWork.is_oa.is_(True), CorpusWork.pdf_storage_key.is_(None))
    if area_code:
        query = query.filter(CorpusWork.primary_area == area_code)
    works = query.limit(limit).all()

    CORPUS_PDF_DIR.mkdir(parents=True, exist_ok=True)

    downloaded = skipped = failed = 0
    for work in works:
        if not work.doi:
            skipped += 1
            continue
        try:
            location = unpaywall_client.get_oa_location(work.doi, settings.OPENALEX_EMAIL)
        except Exception:
            logger.exception("unpaywall lookup failed doi=%s", work.doi)
            failed += 1
            continue

        if not location or not location.get("pdf_url"):
            skipped += 1
            continue

        dest_dir = CORPUS_PDF_DIR / (work.primary_area or "unclassified") / (work.quartile_at_publication or "unknown")
        dest_dir.mkdir(parents=True, exist_ok=True)
        safe_doi = work.doi.replace("/", "__")
        dest_path = dest_dir / f"{safe_doi}.pdf"

        if not _download_pdf(location["pdf_url"], dest_path):
            failed += 1
            continue

        work.pdf_storage_key = str(dest_path)
        work.oa_license = location.get("license")
        work.commercial_use_allowed = unpaywall_client.is_commercial_use_allowed(location.get("license"))
        db.add(work)
        downloaded += 1
        time.sleep(DOWNLOAD_SLEEP_SECONDS)

    db.commit()
    return {"area": area_code, "downloaded": downloaded, "skipped": skipped, "failed": failed}


def _download_pdf(url: str, dest_path: Path) -> bool:
    import requests

    try:
        resp = requests.get(url, timeout=30, headers={"User-Agent": "AcaTurkAI-CorpusBot/0.1 (mailto)"})
    except requests.RequestException:
        logger.exception("pdf download request failed url=%s", url)
        return False
    content_type = resp.headers.get("Content-Type", "").lower()
    if resp.status_code != 200 or "pdf" not in content_type:
        return False
    dest_path.write_bytes(resp.content)
    return True


def import_scimago_year(db: Session, csv_path: str, year: int, set_as_current: bool = False) -> dict:
    rows = scimago_import.parse_scimago_csv(csv_path, year)
    written = scimago_import.upsert_journal_quartiles(db, rows, set_as_current=set_as_current)
    return {"year": year, "rows_written": written}


def corpus_stats(db: Session) -> dict:
    """
    Corpus'un fiili durumunu ozetler - AcaTurkAI_Faz0_Kapanis_Raporu.md'de acik
    birakilan '1. Corpus'un gercek durumu' sorusuna cevap veren canli sayim.
    """
    from sqlalchemy import func

    by_area = dict(
        db.query(CorpusWork.primary_area, func.count(CorpusWork.id)).group_by(CorpusWork.primary_area).all()
    )
    by_source_tier = dict(
        db.query(CorpusWork.source_tier, func.count(CorpusWork.id)).group_by(CorpusWork.source_tier).all()
    )
    total_works = db.query(func.count(CorpusWork.id)).scalar() or 0
    total_with_pdf = db.query(func.count(CorpusWork.id)).filter(CorpusWork.pdf_storage_key.isnot(None)).scalar() or 0
    total_commercial_ok = (
        db.query(func.count(CorpusWork.id)).filter(CorpusWork.commercial_use_allowed.is_(True)).scalar() or 0
    )
    total_journals_with_quartile = (
        db.query(func.count(func.distinct(JournalQuartileHistory.issn))).scalar() or 0
    )

    return {
        "total_works": total_works,
        "total_with_pdf": total_with_pdf,
        "total_commercial_use_allowed": total_commercial_ok,
        "by_area": by_area,
        "by_source_tier": by_source_tier,
        "journals_with_quartile_history": total_journals_with_quartile,
    }
