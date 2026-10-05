"""
Analiz motoru v1: metin -> 3 modul -> agirlikli genel skor -> full_report.

Saf fonksiyon (DB/dosya/ag yok) -> dogrudan birim test edilebilir.
Kalan 8 modul (spec Bolum 5) eklendikce MODULE_WEIGHTS genisler; agirliklar
hesaplamada yeniden normalize edildigi icin mevcut skorlar kirilmaz.
"""
from app.services.analysis.modules import delivery, lexical, structure
from app.services.analysis.text_utils import detect_language, split_sentences, tokenize, verdict_for

ENGINE_VERSION = "1.0.0"

MODULE_WEIGHTS: dict[str, float] = {
    "structure": 0.40,
    "lexical": 0.30,
    "delivery": 0.30,
}
NOT_YET_EVALUATED = (
    "title", "abstract", "literature", "originality", "methodology",
    "findings", "conclusions", "references",
)


def analyze_text(text: str, field: str | None = None) -> dict:
    tokens = tokenize(text)
    language = detect_language(tokens)
    sentences = split_sentences(text)

    results = {
        "structure": structure.analyze(text, language, field),
        "lexical": lexical.analyze(tokens, language),
        "delivery": delivery.analyze(sentences, tokens, language),
    }

    total_weight = sum(MODULE_WEIGHTS[name] for name in results)
    overall = round(sum(r.score * MODULE_WEIGHTS[name] for name, r in results.items()) / total_weight, 1)
    reviews = [r.agent_review for r in results.values()]

    return {
        "engine_version": ENGINE_VERSION,
        "language": language,
        "field": field,
        "word_count": len(tokens),
        "overall_score": overall,
        "rejection_risk_score": round(100 - overall, 1),
        "weights": MODULE_WEIGHTS,
        "modules": {name: r.to_dict() for name, r in results.items()},
        "editorial_board": {
            "decision": verdict_for(overall),
            "reviews": reviews,
            "unanimous": len({rv["verdict"] for rv in reviews}) == 1,
        },
        "not_yet_evaluated": list(NOT_YET_EVALUATED),
    }
