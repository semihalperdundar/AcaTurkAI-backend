"""
Modul: score_references - kaynakca nicelik ve nitelik denetimi.

Olculenler: kaynak sayisi (alana gore bant), guncellik (son 10 yil orani),
metin ici atif yogunlugu, kaynak stili tutarliligi (APA/yazar-yil vs numarali), DOI orani.
Alan farki: hukukta kaynak sayisi yuksek, guncellik ve DOI beklentisi dusuktur
(mevzuat/ictihat ve eski temel eserler yaygin).
"""
import re
from datetime import date

from app.services.analysis.modules.structure import detect_sections, extract_sections
from app.services.analysis.text_utils import ModuleResult, band_score, clamp

COUNT_BANDS: dict[str, dict[str, tuple[float, float]]] = {
    "default": {"ideal": (25, 70), "zero": (3, 200)},
    "health": {"ideal": (20, 60), "zero": (3, 150)},
    "law": {"ideal": (30, 150), "zero": (5, 300)},
}
RECENT_YEARS = 10
RECENCY_BAND = {"ideal": (0.40, 1.0), "zero": (0.05, 1.01)}
DOI_TARGET_SHARE = 0.5

# Yeni girdi baslangici: [12] / 12. Yazar / Soyad, A. ; aksi halde onceki girdinin devami (PDF satir kirilimi).
ENTRY_START_RE = re.compile(
    r"^\s*(?:\[\d+\]|\d+\.\s+[A-ZÇĞİÖŞÜ]|[A-ZÇĞİÖŞÜ][\w'’\-]+,\s+[A-ZÇĞİÖŞÜ])"
)
NUMERIC_ENTRY_RE = re.compile(r"^\s*(?:\[\d+\]|\d+\.\s)")
APA_YEAR_RE = re.compile(r"\((?:19|20)\d{2}[a-z]?\)")
YEAR_RE = re.compile(r"\b(19[5-9]\d|20[0-4]\d)\b")
DOI_RE = re.compile(r"\b10\.\d{4,9}/\S+")
IN_TEXT_PATTERNS = (
    re.compile(r"\([A-ZÇĞİÖŞÜ][^()]{0,80}?\s(?:19|20)\d{2}[a-z]?\)"),  # (Yilmaz, 2020) / (Smith et al., 2019)
    re.compile(r"[A-ZÇĞİÖŞÜ][\w'’\-]+(?: et al\.| ve ark\.| vd\.)?\s\((?:19|20)\d{2}[a-z]?\)"),  # Smith (2020)
    re.compile(r"\[\d+(?:\s*[,–-]\s*\d+)*\]"),  # [3] / [1, 4-6]
)


def split_entries(block: str) -> list[str]:
    entries: list[str] = []
    for line in (ln.strip() for ln in block.split("\n")):
        if not line:
            continue
        if ENTRY_START_RE.match(line) or not entries:
            entries.append(line)
        else:
            entries[-1] += " " + line
    return entries


def count_in_text_citations(body: str) -> int:
    return sum(len(p.findall(body)) for p in IN_TEXT_PATTERNS)


def body_before_references(text: str) -> str:
    """Kaynakca basligindan onceki metin (baslik yoksa tum metin)."""
    heading_idx = detect_sections(text).get("references")
    return "\n".join(text.split("\n")[:heading_idx]) if heading_idx is not None else text


def analyze(text: str, language: str, field: str | None = None, today: date | None = None) -> ModuleResult:
    profile_name = field if field in COUNT_BANDS else "default"
    is_law = profile_name == "law"
    heading_idx = detect_sections(text).get("references")
    citations = count_in_text_citations(body_before_references(text))
    entries = split_entries(extract_sections(text).get("references", ""))

    if not entries:
        missing = "Kaynakca bolumu tespit edilemedi." if heading_idx is None else "Kaynakca basligi var ama girdi bulunamadi."
        return ModuleResult(
            module="references",
            agent="references_reviewer",
            agent_role="Kaynakca Hakemi",
            score=10.0 if citations else 0.0,
            feedback=[missing]
            + ([] if citations else ["Metin ici atif da bulunamadi; calisma alanyazina dayanmiyor gorunuyor."]),
            metrics={"entry_count": 0, "in_text_citations": citations},
            confidence=0.5,
        )

    feedback: list[str] = []
    n = len(entries)

    band = COUNT_BANDS[profile_name]
    count_score = band_score(n, band["ideal"], band["zero"])
    if n < band["ideal"][0]:
        feedback.append(f"Kaynak sayisi dusuk ({n}); alan icin beklenen en az {band['ideal'][0]:.0f}.")
    elif n > band["ideal"][1]:
        feedback.append(f"Kaynak sayisi cok yuksek ({n}); dogrudan iliskili olmayanlari ayiklayin.")

    current_year = (today or date.today()).year
    years = [int(m[-1]) for m in (YEAR_RE.findall(e) for e in entries) if m]
    recent_share = sum(1 for y in years if y >= current_year - RECENT_YEARS) / len(years) if years else 0.0
    recency_score = 100.0 if is_law else band_score(recent_share, RECENCY_BAND["ideal"], RECENCY_BAND["zero"])
    if not is_law and recent_share < RECENCY_BAND["ideal"][0]:
        feedback.append(f"Kaynaklarin yalnizca %{recent_share * 100:.0f}'i son {RECENT_YEARS} yila ait; guncel calismalari ekleyin.")

    citation_ratio = citations / n
    citation_score = clamp(100 * citation_ratio)
    if citations == 0:
        feedback.insert(0, "Metin ici atif tespit edilemedi; kaynakca ile metin baglantisi kurulmamis.")
    elif citation_ratio < 1:
        feedback.append("Metin ici atif sayisi kaynak sayisindan az; atif yapilmayan kaynaklar olabilir.")

    numeric = sum(1 for e in entries if NUMERIC_ENTRY_RE.match(e))
    author_year = sum(1 for e in entries if APA_YEAR_RE.search(e))
    style_consistency = max(numeric, author_year) / n
    if style_consistency < 0.8:
        feedback.append("Kaynak stili tutarsiz (numarali ve yazar-yil bicimleri karisik).")

    doi_share = sum(1 for e in entries if DOI_RE.search(e)) / n
    doi_score = 100.0 if is_law else clamp(100 * doi_share / DOI_TARGET_SHARE)
    if not is_law and doi_share < DOI_TARGET_SHARE:
        feedback.append(f"Kaynaklarin %{doi_share * 100:.0f}'inde DOI var; erisilebilirlik icin DOI ekleyin.")

    score = (
        0.35 * count_score
        + 0.20 * recency_score
        + 0.25 * citation_score
        + 0.10 * style_consistency * 100
        + 0.10 * doi_score
    )

    return ModuleResult(
        module="references",
        agent="references_reviewer",
        agent_role="Kaynakca Hakemi",
        score=round(clamp(score), 1),
        feedback=feedback,
        metrics={
            "field_profile": profile_name,
            "entry_count": n,
            "in_text_citations": citations,
            "recent_share": round(recent_share, 2),
            "doi_share": round(doi_share, 2),
            "style": "numeric" if numeric > author_year else "author_year",
            "style_consistency": round(style_consistency, 2),
        },
        confidence=0.8 if n >= 5 else 0.6,
    )
