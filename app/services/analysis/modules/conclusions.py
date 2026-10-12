"""
Modul: score_conclusions - sonuc bolumunun islevi.

Olculenler:
  - Yeni atif: sonucta metin ici atif = kirmizi bayrak (sonuc yeni kaynak tanitmaz, ozetler).
  - Yeni kavram: sonuc icerik koklerinden onceki metinde hic gecmeyenlerin orani.
  - Sinirliliklar, gelecek arastirma onerileri, kuramsal/uygulamaya donuk cikarimlar.
  - Bolumun metne orani.
Kapsam: Sonuc bolumu; yoksa Tartisma (yari guven).
params:
  citation_penalty   : sonuctaki her metin ici atif icin dusulecek puan
  weights            : skor bilesen agirliklari (citations/limitations/future/implications/alignment/length)
  expect_limitations : False -> sinirlilik beyani yoksa uyarilmaz
  profile_label      : metrics.profile etiketi
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from app.services.analysis.modules.references import count_in_text_citations
from app.services.analysis.text_utils import (
    ModuleResult,
    band_score,
    clamp,
    content_stems,
    count_words,
    normalize,
    tokenize,
)

if TYPE_CHECKING:
    from app.services.analysis.context import Context

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


def analyze(ctx: Context, params: Mapping[str, Any]) -> ModuleResult:
    sections = ctx.sections
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

    body = ctx.body
    lowered = normalize(scope)

    citations = count_in_text_citations(scope)
    citation_score = clamp(100 - params["citation_penalty"] * citations)
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
    if not has_limitations and params["expect_limitations"]:
        feedback.append("Calismanin sinirliliklari (kisitliliklar) belirtilmemis.")
    if not has_future:
        feedback.append("Gelecek arastirmalar icin oneri yok.")
    if not has_implications:
        feedback.append("Kuramsal veya uygulamaya donuk cikarim/oneri yok.")

    total_words = ctx.body_word_count
    section_ratio = count_words(scope) / total_words if total_words else 0.0
    length_score = band_score(section_ratio, SECTION_RATIO_BAND["ideal"], SECTION_RATIO_BAND["zero"])
    if section_ratio < SECTION_RATIO_BAND["ideal"][0]:
        feedback.append(f"Sonuc bolumu metnin yalnizca %{section_ratio * 100:.0f}'i; temel cikarimlar yetersiz islenmis.")
    elif section_ratio > SECTION_RATIO_BAND["ideal"][1]:
        feedback.append(f"Sonuc bolumu metnin %{section_ratio * 100:.0f}'i; bulgulari tekrar etmek yerine ozetleyin.")

    w = params["weights"]
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
            "profile": params["profile_label"],
            "new_citations": citations,
            "new_concept_ratio": round(new_concepts, 2),
            "has_limitations": has_limitations,
            "has_future_research": has_future,
            "has_implications": has_implications,
            "section_ratio": round(section_ratio, 3),
        },
        confidence=0.8 if source == "conclusion" else 0.5,
    )
