"""
Modul: score_abstract - ozet kalitesi.

Olculenler: uzunluk bandi, retorik hamleler (amac / yontem / bulgu / sonuc),
anahtar kelime satiri, nicel bulgu (sayi) varligi.
params:
  moves                : beklenen retorik hamleler (MOVE_PATTERNS anahtarlari)
  require_quantitative : ozette sayisal bulgu yoksa geri bildirim uret
  weights              : skor bilesen agirliklari (moves/length/keywords/quantitative)
  profile_label        : metrics.field_profile etiketi
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from app.services.analysis.text_utils import ModuleResult, band_score, clamp, count_words, normalize

if TYPE_CHECKING:
    from app.services.analysis.context import Context

LENGTH_BAND = {"ideal": (150, 300), "zero": (50, 500)}

# Onek eslemesi (\b yalnizca basta): Turkce ekler ve EN cekimleri ayni kalibi yakalar.
MOVE_PATTERNS: dict[str, re.Pattern] = {
    "purpose": re.compile(
        r"\b(aim|purpose|objective|this study|this paper|this article|we investigate|we examine|"
        r"we evaluate|amaç|bu çalışma|bu araştırma|bu makale|incelen|araştırıl)"
    ),
    "method": re.compile(
        r"\b(method|data|participant|sampl|survey|interview|regression|experiment|"
        r"yöntem|veri|katılımcı|örneklem|anket|görüşme|deney|nitel|nicel)"
    ),
    "results": re.compile(
        r"\b(result|finding|show|indicat|reveal|demonstrat|significant|found|"
        r"bulgu|göster|ortaya|anlamlı|tespit)"
    ),
    "conclusion": re.compile(
        r"\b(conclu|implicat|suggest|recommend|contribut|therefore|thus|"
        r"sonuç olarak|öner|katkı|dolayısıyla|bu nedenle)"
    ),
    "argument": re.compile(r"\b(argu|contend|propos|claim|savun|ileri sür|önerme|tartışıl)"),
}
MOVE_LABELS_TR = {
    "purpose": "amac",
    "method": "yontem",
    "results": "bulgular",
    "conclusion": "sonuc/cikarim",
    "argument": "temel arguman",
}
KEYWORDS_LINE_RE = re.compile(
    r"^\s*(keywords|key words|anahtar kelimeler|anahtar sözcükler)\s*[:—–-]", re.MULTILINE
)
_NUMBER_RE = re.compile(r"\d")


def analyze(ctx: Context, params: Mapping[str, Any]) -> ModuleResult:
    abstract = ctx.sections.get("abstract", "")
    if not abstract:
        return ModuleResult(
            module="abstract",
            agent="abstract_reviewer",
            agent_role="Ozet Hakemi",
            score=0.0,
            feedback=["Ozet/Abstract bolumu tespit edilemedi."],
            metrics={"word_count": 0},
            confidence=0.4,
        )

    feedback: list[str] = []
    expected = params["moves"]
    weights = params["weights"]
    lowered = normalize(abstract)

    # Anahtar kelime satiri ozet govdesine dahilse uzunluga sayilmaz.
    body = KEYWORDS_LINE_RE.split(abstract, maxsplit=1)[0]
    word_count = count_words(body)
    length_score = band_score(word_count, LENGTH_BAND["ideal"], LENGTH_BAND["zero"])
    if word_count < LENGTH_BAND["ideal"][0]:
        feedback.append(f"Ozet kisa ({word_count} kelime); dergiler genellikle 150-300 kelime bekler.")
    elif word_count > LENGTH_BAND["ideal"][1]:
        feedback.append(f"Ozet uzun ({word_count} kelime); 300 kelimenin altina indirin.")

    moves = {m: bool(MOVE_PATTERNS[m].search(lowered)) for m in expected}
    missing = [m for m, ok in moves.items() if not ok]
    move_score = 100 * (len(expected) - len(missing)) / len(expected)
    if missing:
        feedback.insert(0, "Ozette eksik hamle: " + ", ".join(MOVE_LABELS_TR[m] for m in missing) + ".")

    has_keywords = bool(KEYWORDS_LINE_RE.search(normalize(ctx.text)))
    if not has_keywords:
        feedback.append("Anahtar kelime (Keywords / Anahtar Kelimeler) satiri bulunamadi.")

    has_numbers = bool(_NUMBER_RE.search(body))
    if not has_numbers and params["require_quantitative"]:
        feedback.append("Ozette nicel bulgu yok; temel sonucu sayisal olarak (orneklem, etki buyuklugu) verin.")

    score = (
        weights["moves"] * move_score
        + weights["length"] * length_score
        + weights["keywords"] * (100 * has_keywords)
        + weights["quantitative"] * (100 * has_numbers)
    )

    return ModuleResult(
        module="abstract",
        agent="abstract_reviewer",
        agent_role="Ozet Hakemi",
        score=round(clamp(score), 1),
        feedback=feedback,
        metrics={
            "word_count": word_count,
            "moves": moves,
            "has_keywords": has_keywords,
            "has_quantitative_result": has_numbers,
            "field_profile": params["profile_label"],
        },
        confidence=0.85 if word_count >= 50 else 0.6,
    )
