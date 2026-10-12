"""
GroundingValidator: halusinasyon filtresi, tamamen kural tabanli.

Her icgorunun evidence_quote'u makale metninde birebir aranir; yalnizca bosluk ve
buyuk/kucuk harf farklari yok sayilir (PDF satir kirilimlari, "İ"/"i" farki).
Bulunamayan, cok kisa veya pakete ait olmayan modul adini tasiyan icgoru dusurulur.
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.services.analysis.text_utils import normalize
from app.services.insights.schema import Insight

if TYPE_CHECKING:
    from app.services.analysis.context import Context

# "the", "p < .05" gibi her metinde gecebilecek alintilar kanit sayilmaz.
MIN_QUOTE_WORDS = 4
_WS_RE = re.compile(r"\s+")


def canonical(text: str) -> str:
    """Karsilastirma bicimi: Turkce-guvenli kucuk harf + tek bosluk.

    "ı" da "i"ye katlanir: Python "I".lower() == "i" verir, bu yuzden "ARAŞTIRMA" ile
    "araştırma" ancak iki taraf da ayni bicime indirilirse eslesir.
    """
    return _WS_RE.sub(" ", normalize(text).replace("ı", "i")).strip()


@dataclass(frozen=True)
class GroundingResult:
    accepted: list[Insight]
    rejected: list[tuple[Insight, str]] = field(default_factory=list)  # (icgoru, neden)


def validate_grounding(
    insights: Iterable[Insight], ctx: Context, allowed_modules: Iterable[str] | None = None
) -> GroundingResult:
    haystack = canonical(ctx.text)
    allowed = set(allowed_modules) if allowed_modules is not None else None
    accepted: list[Insight] = []
    rejected: list[tuple[Insight, str]] = []

    for insight in insights:
        quote = canonical(insight.evidence_quote)
        if allowed is not None and insight.module not in allowed:
            rejected.append((insight, "module_not_in_pack"))
        elif len(quote.split()) < MIN_QUOTE_WORDS:
            rejected.append((insight, "quote_too_short"))
        elif quote not in haystack:
            rejected.append((insight, "quote_not_in_text"))
        else:
            accepted.append(insight)
    return GroundingResult(accepted, rejected)
