"""
Analiz motoru: metin -> Context (tek ayristirma) -> alan profili -> 11 kural tabanli modul
-> agirlikli genel skor -> full_report.

Saf fonksiyon (DB/dosya/ag yok) -> dogrudan birim test edilebilir.
Moduller alan adini bilmez: her biri analyze(ctx, params) imzasiyla, profilin kendisine
verdigi parametrelerle calisir (bkz. profiles.py). Yeni alan eklemek bu dosyaya dokunmaz.
"""
from collections.abc import Callable, Mapping
from typing import Any

from app.services.analysis.context import Context, build_context
from app.services.analysis.modules import (
    abstract,
    conclusions,
    delivery,
    findings,
    lexical,
    literature,
    methodology,
    originality,
    references,
    structure,
    title,
)
from app.services.analysis.profiles import BASE, MODULE_WEIGHTS, DomainProfile, get_profile
from app.services.analysis.text_utils import ModuleResult, verdict_for

ENGINE_VERSION = "1.2.0"

Analyzer = Callable[[Context, Mapping[str, Any]], ModuleResult]

# Sira = rapordaki modul ve yayin kurulu sirasi.
ANALYZERS: dict[str, Analyzer] = {
    "title": title.analyze,
    "abstract": abstract.analyze,
    "structure": structure.analyze,
    "literature": literature.analyze,
    "originality": originality.analyze,
    "methodology": methodology.analyze,
    "findings": findings.analyze,
    "conclusions": conclusions.analyze,
    "references": references.analyze,
    "lexical": lexical.analyze,
    "delivery": delivery.analyze,
}
EVALUATED_MODULES = tuple(ANALYZERS)
NOT_YET_EVALUATED = tuple(name for name in MODULE_WEIGHTS if name not in ANALYZERS)


def effective_weights(profile: DomainProfile = BASE) -> dict[str, float]:
    """Uygulanmis modullerin agirliklari, toplami 1.0 olacak sekilde normalize."""
    total = sum(profile.weights[name] for name in EVALUATED_MODULES)
    return {name: profile.weights[name] / total for name in EVALUATED_MODULES}


def run_modules(ctx: Context, profile: DomainProfile) -> dict[str, ModuleResult]:
    return {name: analyze(ctx, profile.params_for(name)) for name, analyze in ANALYZERS.items()}


def analyze_text(text: str, field: str | None = None) -> dict:
    ctx = build_context(text)
    profile = get_profile(field)
    results = run_modules(ctx, profile)

    weights = effective_weights(profile)
    overall = round(sum(r.score * weights[name] for name, r in results.items()), 1)
    reviews = [r.agent_review for r in results.values()]

    return {
        "engine_version": ENGINE_VERSION,
        "language": ctx.language,
        "field": field,
        "word_count": len(ctx.tokens),
        "overall_score": overall,
        "rejection_risk_score": round(100 - overall, 1),
        "weights": {name: round(w, 4) for name, w in weights.items()},
        "configured_weights": dict(profile.weights),  # JSONB'ye yazilir -> duz dict
        "modules": {name: r.to_dict() for name, r in results.items()},
        "editorial_board": {
            "decision": verdict_for(overall),
            "reviews": reviews,
            "unanimous": len({rv["verdict"] for rv in reviews}) == 1,
        },
        "not_yet_evaluated": list(NOT_YET_EVALUATED),
    }
