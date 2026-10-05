"""
Modul: score_conclusions - sonuc bolumunun islevi.

Olculenler:
  - Yeni atif: sonucta metin ici atif = kirmizi bayrak (sonuc yeni kaynak tanitmaz, ozetler).
  - Yeni kavram: sonuc icerik koklerinden onceki metinde hic gecmeyenlerin orani.
  - Sinirliliklar, gelecek arastirma onerileri, kuramsal/uygulamaya donuk cikarimlar.
  - Bolumun metne orani.
Kapsam: Sonuc bolumu; yoksa Tartisma (yari guven).
Alan farki: hukukta sinirlilik beyani nadirdir -> agirligi cikarim/oneriye kayar,
sonucta norm atfi daha olagan oldugu icin atif cezasi hafiftir.
"""
import re

from app.services.analysis.modules.references import body_before_references, count_in_text_citations
from app.services.analysis.modules.structure import extract_sections
from app.services.analysis.text_utils import (
    ModuleResult,
    band_score,
    clamp,
    content_stems,
    count_words,
    normalize,
    tokenize,
)

LIMITATION_RE = re.compile(
    r"\b(limitation|limited to|caveat|should be interpreted with caution|kısıtlılık|sınırlılık|sınırlı kalmaktadır)"
)
FUTURE_RE = re.compile(
    r"\b(future research|future stud|further research|further stud|future work|should investigate|"
    r"gelecekteki|ileride yapılacak|sonraki çalışmalar|ileriki çalışmalar|araştırmacılara öneri)"
)
IMPLICATION_RE = re.compile(
    r"\b(implicat|practical|practitioner|policy|recommend|should|contribut|"
    r"uygulama|uygulayıcı|politika|öneri|öneril|katkı)"
    r"|\w(melidir|malıdır|meliyiz|malıyız)\b"  # TR gereklilik kipi: "dahil edilmelidir"
)
SECTION_RATIO_BAND = {"ideal": (0.04, 0.15), "zero": (0.01, 0.35)}
NEW_CONCEPT_BAND = {"ideal": (0.0, 0.35), "zero": (-1.0, 0.70)}
CONCEPT_MIN_LEN = 6  # kisa islev kelimelerini (into, should, appear) kavram sayma
CITATION_PENALTY = {"default": 25, "law": 10}
WEIGHTS = {
    "default": {
        "citations": 0.20, "limitations": 0.15, "future": 0.15,
        "implications": 0.15, "alignment": 0.20, "length": 0.15,
    },
    "law": {
        "citations": 0.15, "limitations": 0.05, "future": 0.15,
        "implications": 0.25, "alignment": 0.25, "length": 0.15,
    },
}


def analyze(text: str, language: str, field: str | None = None) -> ModuleResult:
    profile = "law" if field == "law" else "default"
    sections = extract_sections(text)
    feedback: list[str] = []

    if sections.get("conclusion"):
        scope, source = sections["conclusion"], "conclusion"
    elif sections.get("discussion"):
        scope, source = sections["discussion"], "discussion"
        feedback.append("Ayri bir Sonuc bolumu yok; Tartisma sonuc islevi acisindan degerlendirildi.")
    else:
        return ModuleResult(
            module="conclusions",
            agent="conclusions_reviewer",
            agent_role="Sonuc Hakemi",
            score=0.0,
            feedback=["Sonuc/Tartisma bolumu tespit edilemedi."],
            metrics={"scope": None},
            confidence=0.4,
        )

    body = body_before_references(text)
    lowered = normalize(scope)

    citations = count_in_text_citations(scope)
    citation_score = clamp(100 - CITATION_PENALTY[profile] * citations)
    if citations and source == "conclusion":
        feedback.insert(0, f"Sonuc bolumunde {citations} metin ici atif var; sonuc yeni kaynak tanitmamali, bulgulari ozetlemeli.")

    preceding = body.split(scope, 1)[0] if scope in body else body
    conclusion_stems = content_stems(tokenize(scope), CONCEPT_MIN_LEN)
    unseen = conclusion_stems - content_stems(tokenize(preceding), CONCEPT_MIN_LEN)
    new_concepts = len(unseen) / len(conclusion_stems) if conclusion_stems else 0.0
    alignment_score = band_score(new_concepts, NEW_CONCEPT_BAND["ideal"], NEW_CONCEPT_BAND["zero"])
    if new_concepts > NEW_CONCEPT_BAND["ideal"][1]:
        feedback.append(f"Sonuc kavramlarinin %{new_concepts * 100:.0f}'i metnin onceki kisimlarinda yok; sonuc yeni icerik tasiyor.")

    has_limitations = bool(LIMITATION_RE.search(lowered))
    has_future = bool(FUTURE_RE.search(lowered))
    has_implications = bool(IMPLICATION_RE.search(lowered))
    if not has_limitations and profile != "law":
        feedback.append("Calismanin sinirliliklari (kisitliliklar) belirtilmemis.")
    if not has_future:
        feedback.append("Gelecek arastirmalar icin oneri yok.")
    if not has_implications:
        feedback.append("Kuramsal veya uygulamaya donuk cikarim/oneri yok.")

    total_words = count_words(body)
    section_ratio = count_words(scope) / total_words if total_words else 0.0
    length_score = band_score(section_ratio, SECTION_RATIO_BAND["ideal"], SECTION_RATIO_BAND["zero"])
    if section_ratio < SECTION_RATIO_BAND["ideal"][0]:
        feedback.append(f"Sonuc bolumu metnin yalnizca %{section_ratio * 100:.0f}'i; temel cikarimlar yetersiz islenmis.")
    elif section_ratio > SECTION_RATIO_BAND["ideal"][1]:
        feedback.append(f"Sonuc bolumu metnin %{section_ratio * 100:.0f}'i; bulgulari tekrar etmek yerine ozetleyin.")

    w = WEIGHTS[profile]
    score = (
        w["citations"] * citation_score
        + w["limitations"] * 100 * has_limitations
        + w["future"] * 100 * has_future
        + w["implications"] * 100 * has_implications
        + w["alignment"] * alignment_score
        + w["length"] * length_score
    )

    return ModuleResult(
        module="conclusions",
        agent="conclusions_reviewer",
        agent_role="Sonuc Hakemi",
        score=round(clamp(score), 1),
        feedback=feedback,
        metrics={
            "scope": source,
            "profile": profile,
            "new_citations": citations,
            "new_concept_ratio": round(new_concepts, 2),
            "has_limitations": has_limitations,
            "has_future_research": has_future,
            "has_implications": has_implications,
            "section_ratio": round(section_ratio, 3),
        },
        confidence=0.8 if source == "conclusion" else 0.5,
    )
