"""
Alan kodu <-> OpenAlex concept ID eslemesi.

akademik_kutuphane_projesi.md Bolum 7.2'deki AREA_CONCEPTS sozlugu buraya
tasindi, ancak klasor-adi anahtarlari ('01_EgitimBilimleri' vb.) yerine
User.primary_field / Analysis.selected_field ile AYNI 6 alan kodu kullanildi
('education' | 'social_sciences' | 'engineering' | 'health' | 'law' | 'business') -
boylece corpus tablosu ile kullanici/analiz tablolari ayni sozlugu paylasir.
"""

# OpenAlex concept ID'leri (https://api.openalex.org/concepts) - alan basina
# birden fazla concept olabilir, sorgu hepsini OR ile tarar.
AREA_CONCEPTS: dict[str, list[str]] = {
    "education": ["C15744967"],  # Education
    "social_sciences": ["C144024400", "C166957645", "C95457728"],  # Sociology, Geography, History
    "engineering": ["C127413603", "C121332964"],  # Engineering, Physics
    "health": ["C71924100"],  # Medicine
    "law": ["C17744445"],  # Political science (Law alt kumesi - dedicated concept yok)
    "business": ["C162324750", "C144133560"],  # Economics, Business
}

# Scimago CSV'deki "Categories" hucresi (ör. "Education; Social Sciences (miscellaneous)")
# icin kaba anahtar kelime eslemesi - import_scimago_year bunu area_mapping'e yazmak icin kullanir.
SCIMAGO_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "education": ["education"],
    "social_sciences": ["sociology", "social science", "political science", "history", "anthropology",
                          "communication", "geography"],
    "engineering": ["engineering", "physics", "computer science", "chemistry", "mathematics", "materials"],
    "health": ["medicine", "health", "nursing", "pharmacology", "dentistry", "biomedical"],
    "law": ["law"],
    "business": ["economics", "econometrics", "business", "management", "finance", "accounting"],
}

VALID_AREA_CODES = tuple(AREA_CONCEPTS.keys())


def guess_area_from_scimago_category(category: str | None) -> str | None:
    """Scimago 'Categories' metnini kaba anahtar kelimeyle bizim 6 alan kodumuza esler."""
    if not category:
        return None
    lowered = category.lower()
    for area_code, keywords in SCIMAGO_CATEGORY_KEYWORDS.items():
        if any(kw in lowered for kw in keywords):
            return area_code
    return None
