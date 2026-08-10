"""
Tum SQLAlchemy modellerini tek yerden import eder ki Alembic autogenerate
ve Base.metadata butun tablolari gorsun.

Spec referansi: AcaTurkAI_Project_Spec.md - Bolum 14 (Veritabani Semasi)
Corpus modelleri: akademik_kutuphane_projesi.md - Bolum 6 (Veritabani Semasi)
"""
from app.models.user import User  # noqa: F401
from app.models.analysis import Analysis, ThesisProject, AnalysisVersion  # noqa: F401
from app.models.journal import Journal  # noqa: F401
from app.models.subscription import Subscription  # noqa: F401
from app.models.usage_log import UsageLog  # noqa: F401
from app.models.corpus import Author, CorpusWork, WorkAuthor, JournalQuartileHistory  # noqa: F401

__all__ = [
    "User",
    "Analysis",
    "ThesisProject",
    "AnalysisVersion",
    "Journal",
    "Subscription",
    "UsageLog",
    "Author",
    "CorpusWork",
    "WorkAuthor",
    "JournalQuartileHistory",
]
