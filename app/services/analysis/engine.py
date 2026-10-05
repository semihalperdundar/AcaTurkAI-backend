"""
Analiz motoru: metin -> kural tabanli moduller -> agirlikli genel skor -> full_report.

Saf fonksiyon (DB/dosya/ag yok) -> dogrudan birim test edilebilir.
MODULE_WEIGHTS spec Bolum 5'teki 11 modulun TAMAMINI kapsar ve toplami 1.0'dir.
Genel skor yalnizca uygulanmis modullerin (ANALYZERS) agirliklari uzerinden yeniden
normalize edilir -> yeni modul eklendikce mevcut skorlar kirilmaz.
"""
from collections.abc import Callable
from dataclasses import dataclass

from app.services.analysis.modules import abstract, delivery, lexical, methodology, references, structure, title
from app.services.analysis.text_utils import ModuleResult, detect_language, split_sentences, tokenize, verdict_for

ENGINE_VERSION = "1.1.0"

MODULE_WEIGHTS: dict[str, float] = {
    "title": 0.05,
    "abstract": 0.10,
    "structure": 0.10,
    "literature": 0.10,
    "originality": 0.10,
    "methodology": 0.15,
    "findings": 0.12,
    "conclusions": 0.08,
    "references": 0.07,
    "lexical": 0.06,
    "delivery": 0.07,
}


@dataclass(frozen=True)
class _Context:
    text: str
    tokens: list[str]
    sentences: list[str]
    language: str
    field: str | None


ANALYZERS: dict[str, Callable[[_Context], ModuleResult]] = {
    "title": lambda c: title.analyze(c.text, c.language, c.field),
    "abstract": lambda c: abstract.analyze(c.text, c.language, c.field),
    "structure": lambda c: structure.analyze(c.text, c.language, c.field),
    "methodology": lambda c: methodology.analyze(c.text, c.language, c.field),
    "references": lambda c: references.analyze(c.text, c.language, c.field),
    "lexical": lambda c: lexical.analyze(c.tokens, c.language),
    "delivery": lambda c: delivery.analyze(c.sentences, c.tokens, c.language),
}
EVALUATED_MODULES = tuple(ANALYZERS)
NOT_YET_EVALUATED = tuple(name for name in MODULE_WEIGHTS if name not in ANALYZERS)


def effective_weights() -> dict[str, float]:
    """Uygulanmis modullerin agirliklari, toplami 1.0 olacak sekilde normalize."""
    total = sum(MODULE_WEIGHTS[name] for name in EVALUATED_MODULES)
    return {name: MODULE_WEIGHTS[name] / total for name in EVALUATED_MODULES}


def analyze_text(text: str, field: str | None = None) -> dict:
    tokens = tokenize(text)
    language = detect_language(tokens)

    context = _Context(text, tokens, split_sentences(text), language, field)
    results = {name: run(context) for name, run in ANALYZERS.items()}

    weights = effective_weights()
    overall = round(sum(r.score * weights[name] for name, r in results.items()), 1)
    reviews = [r.agent_review for r in results.values()]

    return {
        "engine_version": ENGINE_VERSION,
        "language": language,
        "field": field,
        "word_count": len(tokens),
        "overall_score": overall,
        "rejection_risk_score": round(100 - overall, 1),
        "weights": {name: round(w, 4) for name, w in weights.items()},
        "configured_weights": MODULE_WEIGHTS,
        "modules": {name: r.to_dict() for name, r in results.items()},
        "editorial_board": {
            "decision": verdict_for(overall),
            "reviews": reviews,
            "unanimous": len({rv["verdict"] for rv in reviews}) == 1,
        },
        "not_yet_evaluated": list(NOT_YET_EVALUATED),
    }
