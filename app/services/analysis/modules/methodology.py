"""
Modul: score_methodology - yontem bolumunun tamligi.

Olculenler: yontem bilesenlerinin varligi (desen, orneklem, veri toplama, analiz,
gecerlik/guvenirlik, etik), orneklem buyuklugunun raporlanmasi, bolumun metne orani.
Alan farki:
  - health: etik kurul / onam zorunlu kabul edilir (agirligi yuksek).
  - law: ayri bir yontem bolumu beklenmez; tum metinde yaklasim (doktrinel,
    karsilastirmali, ictihat) ve birincil kaynak kullanimi aranir.
"""
import re

from app.services.analysis.modules.structure import extract_sections
from app.services.analysis.text_utils import ModuleResult, band_score, clamp, count_words, normalize

ELEMENT_PATTERNS: dict[str, re.Pattern] = {
    "design": re.compile(
        r"\b(research design|study design|qualitative|quantitative|mixed[- ]method|experimental|"
        r"quasi[- ]experimental|cross[- ]sectional|longitudinal|case study|survey|meta[- ]analys|"
        r"systematic review|araştırma deseni|desen|nitel|nicel|karma yöntem|deneysel|yarı deneysel|"
        r"kesitsel|boylamsal|durum çalışması|tarama model|ilişkisel tarama)"
    ),
    "sample": re.compile(
        r"\b(participant|sampl|respondent|patient|subject|cohort|"
        r"katılımcı|örneklem|çalışma grubu|evren|hasta)"
    ),
    "instruments": re.compile(
        r"\b(questionnaire|interview|scale|inventory|instrument|record|observation|data were collected|"
        r"data collection|anket|görüşme|ölçe|ölçüm|envanter|gözlem|veri toplama|toplanmıştır)"
    ),
    "analysis": re.compile(
        r"\b(regression|anova|t[- ]test|chi[- ]square|correlation|thematic|content analysis|spss|stata|"
        r"nvivo|structural equation|statistical|analyzed|analysed|estimated|regresyon|korelasyon|"
        r"tematik|içerik analizi|betimsel|istatistik|analiz edil)"
    ),
    "validity": re.compile(
        r"\b(validity|reliability|cronbach|validated|kappa|triangulation|"
        r"geçerlik|geçerlilik|güvenirlik|güvenilirlik|üçgenleme)"
    ),
    "ethics": re.compile(
        r"\b(ethic|informed consent|institutional review|irb|helsinki|etik|onam|bilgilendirilmiş|aydınlatılmış)"
    ),
    "approach": re.compile(
        r"\b(doctrinal|comparative|case law|jurisprudence|legal analysis|normative|"
        r"doktrin|karşılaştırmalı|içtihat|hukuki analiz|normatif|yorum yöntem)"
    ),
    "sources": re.compile(
        r"\b(statute|legislation|court|constitution|treaty|regulation|"
        r"kanun|yasa|mevzuat|anayasa|mahkeme|yargıtay|danıştay|uluslararası sözleşme|yönetmelik)"
    ),
}
FIELD_PROFILES: dict[str, dict[str, float]] = {
    "default": {"design": 20, "sample": 20, "instruments": 20, "analysis": 25, "validity": 10, "ethics": 5},
    "health": {"design": 15, "sample": 20, "instruments": 15, "analysis": 20, "validity": 10, "ethics": 20},
    "law": {"approach": 60, "sources": 40},
}
ELEMENT_LABELS_TR = {
    "design": "arastirma deseni",
    "sample": "orneklem/katilimcilar",
    "instruments": "veri toplama araclari",
    "analysis": "analiz yontemi",
    "validity": "gecerlik/guvenirlik",
    "ethics": "etik kurul/onam",
    "approach": "hukuki yontem yaklasimi",
    "sources": "birincil hukuk kaynaklari",
}
SECTION_RATIO_BAND = {"ideal": (0.12, 0.35), "zero": (0.03, 0.60)}
SAMPLE_SIZE_RE = re.compile(
    r"\b(?:n\s*=\s*(\d+)|(\d{2,})\s+(?:[^\W\d_]+\s+){0,2}?(?:participants|students|patients|respondents|teachers|subjects|"
    r"lisans öğrenci|katılımcı|öğrenci|hasta|öğretmen|kişi))"
)
SAMPLE_WITHOUT_SIZE_CREDIT = 0.7


def _sample_size(lowered: str) -> int | None:
    match = SAMPLE_SIZE_RE.search(lowered)
    return int(match.group(1) or match.group(2)) if match else None


def analyze(text: str, language: str, field: str | None = None) -> ModuleResult:
    profile_name = field if field in FIELD_PROFILES else "default"
    weights = FIELD_PROFILES[profile_name]
    is_law = profile_name == "law"
    feedback: list[str] = []

    section = extract_sections(text).get("methodology", "")
    has_section = bool(section)
    # Hukukta yontem metne yayilir; diger alanlarda bolum yoksa tum metin taranir ama cezali.
    scope = normalize(text if is_law or not has_section else section)

    found = {name: bool(ELEMENT_PATTERNS[name].search(scope)) for name in weights}
    sample_size = None if is_law else _sample_size(scope)
    credit = {name: float(ok) for name, ok in found.items()}
    if found.get("sample") and sample_size is None:
        credit["sample"] = SAMPLE_WITHOUT_SIZE_CREDIT
        feedback.append("Katilimcilar anilmis ama orneklem buyuklugu (n) acikca raporlanmamis.")
    coverage = sum(weights[n] * credit[n] for n in weights) / sum(weights.values())

    missing = [n for n, ok in found.items() if not ok]
    if missing:
        feedback.insert(0, "Yontemde eksik bilesen: " + ", ".join(ELEMENT_LABELS_TR[n] for n in missing) + ".")
    if profile_name == "health" and not found["ethics"]:
        feedback.append("Saglik alaninda etik kurul onayi ve onam beyani olmadan makale masa basinda reddedilebilir.")

    total_words = count_words(text)
    section_ratio = count_words(section) / total_words if total_words else 0.0
    if is_law:
        score = 100 * coverage
        confidence = 0.6  # hukuk yontemi anahtar kelimeden cok argumantasyonla anlasilir
    elif has_section:
        ratio_score = band_score(section_ratio, SECTION_RATIO_BAND["ideal"], SECTION_RATIO_BAND["zero"])
        if section_ratio < SECTION_RATIO_BAND["ideal"][0]:
            feedback.append(f"Yontem bolumu metnin %{section_ratio * 100:.0f}'i; tekrarlanabilirlik icin yetersiz ayrinti.")
        score = 80 * coverage + 0.20 * ratio_score
        confidence = 0.85
    else:
        feedback.insert(0, "Ayri bir Yontem bolumu tespit edilemedi; bilesenler tum metinde arandi.")
        score = 50 * coverage
        confidence = 0.4

    return ModuleResult(
        module="methodology",
        agent="methodology_reviewer",
        agent_role="Yontem Hakemi",
        score=round(clamp(score), 1),
        feedback=feedback,
        metrics={
            "field_profile": profile_name,
            "has_section": has_section,
            "elements_found": found,
            "sample_size": sample_size,
            "section_ratio": round(section_ratio, 3),
            "coverage": round(coverage, 2),
        },
        confidence=confidence,
    )
