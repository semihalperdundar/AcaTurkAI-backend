"""
Corpus (akademik derleme) modelleri.

Kaynak: 'akademik_kutuphane_projesi.md' (Akademik Referans Kutuphanesi Projesi) -
Bolum 6 (Veritabani Semasi) buraya AcaTurkAI backend'ine tasindi ve mevcut
Journal modeliyle (app/models/journal.py) hizalandi.

Spec (AcaTurkAI_Project_Spec.md) Bolum 10-11'deki 3 katmanli corpus ayrimini
(Acik Erisim / TDM / Local Curated) `source_tier` alaniyla, ticari/arastirma
hattini `commercial_use_allowed` alaniyla, ve KVKK Gizlilik Taslagi Madde 6'daki
"kullanicinin corpus'a katkisi icin ayri acik riza" kuralini `consent_given`
alaniyla kod seviyesinde ayirir.

Alan kodlari User.primary_field / Analysis.selected_field ile birebir ayni
kume olmalidir: 'education' | 'social_sciences' | 'engineering' | 'health' |
'law' | 'business' (bkz. app/services/corpus/areas.py).
"""
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import uuid_pk

JsonType = JSONB().with_variant(JSON(), "sqlite")

# Spec Bolum 10-11: corpus'un hangi hukuki katmandan geldigi.
SOURCE_TIER_OPEN_ACCESS = "open_access"   # OpenAlex/Unpaywall/CORE/arXiv/PMC - toplu indirme yasal
SOURCE_TIER_TDM = "tdm"                   # Elsevier/T&F vb. - sadece arastirma, kurumsal lisans
SOURCE_TIER_LOCAL_CURATED = "local_curated"  # Kullanicinin kendi yukledigi / Zotero


class Author(Base):
    """akademik_kutuphane_projesi.md Bolum 6 - authors tablosu."""

    __tablename__ = "corpus_authors"

    id = uuid_pk()
    openalex_id: Mapped[str | None] = mapped_column(String(100), unique=True, index=True)
    full_name: Mapped[str | None] = mapped_column(String(500))
    orcid: Mapped[str | None] = mapped_column(String(50))
    affiliation: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    works = relationship("WorkAuthor", back_populates="author")


class CorpusWork(Base):
    """
    akademik_kutuphane_projesi.md Bolum 6 - works tablosu.

    AcaTurkAI'daki kullanim amaci: spec Bolum 12'deki alan normu hesaplamalari
    (Modul 4, 6, 8, 9) icin referans corpus'u besler. Tam metin PDF DEGIL,
    esas olarak metadata (baslik, ozet, atif, dergi/quartile) tutulur; PDF
    yalnizca source_tier=open_access ve commercial_use_allowed=True oldugunda
    ve yasal OA linkinden indirilir.
    """

    __tablename__ = "corpus_works"

    id = uuid_pk()
    openalex_id: Mapped[str | None] = mapped_column(String(100), unique=True, index=True)
    doi: Mapped[str | None] = mapped_column(String(255), unique=True, index=True)
    title: Mapped[str | None] = mapped_column(String(1000))
    abstract: Mapped[str | None] = mapped_column(String)
    publication_year: Mapped[int | None] = mapped_column(Integer, index=True)

    journal_id: Mapped[UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("journals.id"))
    journal_name: Mapped[str | None] = mapped_column(String(500))
    journal_issn: Mapped[str | None] = mapped_column(String(20), index=True)

    cited_by_count: Mapped[int | None] = mapped_column(Integer)
    is_oa: Mapped[bool] = mapped_column(Boolean, default=False)
    oa_url: Mapped[str | None] = mapped_column(String(1000))
    oa_license: Mapped[str | None] = mapped_column(String(50))  # 'cc-by', 'cc0', 'publisher-specific' vb.
    pdf_storage_key: Mapped[str | None] = mapped_column(String(500))  # S3/R2 anahtari (yerel yol degil)

    # Spec Bolum 3.2: makale, yayimlandigi yilin quartile'ina gore siniflanir.
    primary_area: Mapped[str | None] = mapped_column(String(50), index=True)
    primary_subarea: Mapped[str | None] = mapped_column(String(100))
    secondary_areas: Mapped[dict | None] = mapped_column(JsonType)
    quartile_at_publication: Mapped[str | None] = mapped_column(String(5))

    source_tier: Mapped[str] = mapped_column(String(20), default=SOURCE_TIER_OPEN_ACCESS, index=True)
    commercial_use_allowed: Mapped[bool] = mapped_column(Boolean, default=False)
    # KVKK Gizlilik Taslagi Madde 6 - kullanicinin kendi yukledigi metnin corpus'a
    # katkisi icin ayri ve acik riza verip vermedigi (yalnizca source_tier=local_curated icin anlamli).
    consent_given: Mapped[bool] = mapped_column(Boolean, default=False)

    raw_json: Mapped[dict | None] = mapped_column(JsonType)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    journal = relationship("Journal", back_populates="works")
    authors = relationship("WorkAuthor", back_populates="work")


class WorkAuthor(Base):
    """corpus_works <-> corpus_authors many-to-many (siralamayi korumak icin position)."""

    __tablename__ = "corpus_work_authors"

    work_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("corpus_works.id"), primary_key=True)
    author_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("corpus_authors.id"), primary_key=True)
    position: Mapped[int | None] = mapped_column(Integer)

    work = relationship("CorpusWork", back_populates="authors")
    author = relationship("Author", back_populates="works")


class JournalQuartileHistory(Base):
    """
    akademik_kutuphane_projesi.md Bolum 6 - journal_quartiles tablosu.

    Mevcut Journal modeli (app/models/journal.py) yalnizca GUNCEL quartile'i tutar.
    Ancak spec Bolum 3.2'nin altini cizdigi gibi bir dergi zaman icinde quartile
    degistirebilir ve bir makale KENDI YAYIN YILINDAKI quartile'a gore
    siniflanmalidir - bu yuzden yil bazli gecmis ayri tutulur (Scimago yillik CSV'den).
    """

    __tablename__ = "journal_quartile_history"
    __table_args__ = (UniqueConstraint("issn", "year", "category", name="uq_journal_quartile_year_cat"),)

    id = uuid_pk()
    issn: Mapped[str] = mapped_column(String(20), index=True)
    year: Mapped[int] = mapped_column(Integer, index=True)
    quartile: Mapped[str | None] = mapped_column(String(5))
    sjr_score: Mapped[float | None] = mapped_column(Float)
    category: Mapped[str | None] = mapped_column(String(255))
    area_mapping: Mapped[str | None] = mapped_column(String(50))  # 'education' | 'social_sciences' | ...
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
