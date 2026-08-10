"""
Scimago (SJR) yillik CSV -> journal_quartile_history import'u.

akademik_kutuphane_projesi.md Bolum 4.1 ve 7.4'e dayanir. Scimago CSV'de
'Issn' sutunu "12345678, 87654321" gibi birden fazla ISSN'i tek hucrede
virgulle ayrilmis tutabilir; bu fonksiyon her ISSN icin ayri satir uretir
(explode), tipki dokumandaki orijinal script gibi.
"""
import pandas as pd
from sqlalchemy.orm import Session

from app.models.corpus import JournalQuartileHistory
from app.models.journal import Journal
from app.services.corpus.areas import guess_area_from_scimago_category


def parse_scimago_csv(csv_path: str, year: int) -> list[dict]:
    """Scimago'nun ';'-ayracli CSV'sini duz bir satir listesine cevirir (ISSN basina bir satir)."""
    df = pd.read_csv(csv_path, sep=";")

    required_cols = {"Issn", "SJR Best Quartile", "SJR", "Categories", "Title"}
    missing = required_cols - set(df.columns)
    if missing:
        raise ValueError(f"Scimago CSV'de beklenen sutunlar eksik: {missing}")

    df = df.assign(Issn=df["Issn"].astype(str).str.split(","))
    df = df.explode("Issn")
    df["Issn"] = df["Issn"].str.strip()
    df = df[df["Issn"].notna() & (df["Issn"] != "") & (df["Issn"] != "nan")]

    rows = []
    for _, r in df.iterrows():
        sjr_raw = str(r.get("SJR", "")).replace(",", ".")
        try:
            sjr_score = float(sjr_raw) if sjr_raw not in ("", "nan") else None
        except ValueError:
            sjr_score = None

        category = r.get("Categories")
        rows.append(
            {
                "issn": r["Issn"],
                "year": year,
                "quartile": r.get("SJR Best Quartile") or None,
                "sjr_score": sjr_score,
                "category": category,
                "area_mapping": guess_area_from_scimago_category(category),
                "journal_name": r.get("Title"),
            }
        )
    return rows


def upsert_journal_quartiles(db: Session, rows: list[dict], set_as_current: bool = False) -> int:
    """
    JournalQuartileHistory'ye upsert eder (issn, year, category) benzersizligiyle.
    set_as_current=True ise ayrica mevcut Journal kaydinin guncel quartile/sjr_score
    alanlarini da bu yilin degerleriyle gunceller (en guncel Scimago yili import
    edilirken kullanilir).
    """
    written = 0
    for row in rows:
        existing = (
            db.query(JournalQuartileHistory)
            .filter(
                JournalQuartileHistory.issn == row["issn"],
                JournalQuartileHistory.year == row["year"],
                JournalQuartileHistory.category == row["category"],
            )
            .one_or_none()
        )
        if existing:
            existing.quartile = row["quartile"]
            existing.sjr_score = row["sjr_score"]
            existing.area_mapping = row["area_mapping"]
        else:
            db.add(
                JournalQuartileHistory(
                    issn=row["issn"],
                    year=row["year"],
                    quartile=row["quartile"],
                    sjr_score=row["sjr_score"],
                    category=row["category"],
                    area_mapping=row["area_mapping"],
                )
            )
        written += 1

        if set_as_current:
            journal = db.query(Journal).filter(Journal.issn == row["issn"]).one_or_none()
            if journal is None:
                journal = Journal(name=row.get("journal_name") or row["issn"], issn=row["issn"])
                db.add(journal)
            journal.quartile = row["quartile"]
            journal.sjr_score = row["sjr_score"]
            journal.field = journal.field or row["area_mapping"]

    db.commit()
    return written
