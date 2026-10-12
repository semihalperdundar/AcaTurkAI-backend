"""
Modul: score_structure - akademik bolum yapisi (IMRAD) denetimi.

Olculenler: zorunlu bolumlerin varligi, siralamasi, kaynakca varligi.
params:
  core_weights  : beklenen bolumler ve agirliklari (hangi bolumlerin zorunlu oldugu buradan gelir)
  profile_label : metrics.field_profile etiketi
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from app.services.analysis.text_utils import (
    ModuleResult,
    clamp,
    is_heading_line,
    normalize,
    strip_heading_number,
)

if TYPE_CHECKING:  # context.py bu modulu import eder -> dongusel import'u onle
    from app.services.analysis.context import Context

SECTION_PATTERNS: dict[str, re.Pattern] = {
    "abstract": re.compile(r"^(abstract|özet|öz)\b"),
    "introduction": re.compile(r"^(introduction|giriş)\b"),
    "literature": re.compile(
        r"^(literature review|literature|related work|background|theoretical framework|conceptual framework|"
        r"alanyazın|literatür|kuramsal çerçeve|kavramsal çerçeve|ilgili çalışmalar)"
    ),
    "methodology": re.compile(
        r"(method|yöntem|metot|metod|materials and methods|gereç ve yöntem|research design|araştırma deseni)"
    ),
    "results": re.compile(r"(results|findings|bulgular)"),
    "discussion": re.compile(r"(discussion|tartışma)"),
    "conclusion": re.compile(r"(conclusion|concluding|sonuç)"),
    "references": re.compile(r"^(references|bibliography|kaynakça|kaynaklar)\b"),
}
# Inline etiket: "Abstract: ..." / "Özet — ..." (uzun satir olsa da bolum sayilir)
_INLINE_LABEL_RE = re.compile(r"^(abstract|özet|öz)\s*[:—–-]")

EXPECTED_ORDER = ("abstract", "introduction", "methodology", "results", "conclusion")

SECTION_LABELS_TR = {
    "abstract": "Ozet/Abstract",
    "introduction": "Giris",
    "literature": "Alanyazin",
    "methodology": "Yontem",
    "results": "Bulgular",
    "discussion": "Tartisma",
    "conclusion": "Sonuc",
    "references": "Kaynakca",
}


def detect_sections(text: str) -> dict[str, int]:
    """bolum -> ilk gorundugu satir indeksi."""
    found: dict[str, int] = {}
    for idx, raw in enumerate(text.split("\n")):
        line = normalize(strip_heading_number(raw))
        if not line:
            continue
        candidates = SECTION_PATTERNS.items() if is_heading_line(raw) else ()
        if _INLINE_LABEL_RE.match(line):
            candidates = [("abstract", SECTION_PATTERNS["abstract"])]
        for name, pattern in candidates:
            if name not in found and pattern.search(line):
                found[name] = idx
    return found


def extract_sections(text: str, found: Mapping[str, int] | None = None) -> dict[str, str]:
    """bolum -> govde metni (basliktan bir sonraki tespit edilen basliga kadar).

    Inline etiketli ozetlerde ("Abstract: ...") etiket sonrasi metin de govdeye dahildir.
    found verilirse (Context) basliklar yeniden taranmaz.
    """
    lines = text.split("\n")
    starts = sorted((found if found is not None else detect_sections(text)).items(), key=lambda kv: kv[1])
    sections: dict[str, str] = {}
    for i, (name, idx) in enumerate(starts):
        end = starts[i + 1][1] if i + 1 < len(starts) else len(lines)
        head = strip_heading_number(lines[idx])
        inline = re.split(r"[:—–-]", head, maxsplit=1)[1] if _INLINE_LABEL_RE.match(normalize(head)) else ""
        sections[name] = "\n".join([inline, *lines[idx + 1 : end]]).strip()
    return sections


def _order_ratio(found: dict[str, int], expected: tuple[str, ...]) -> float:
    present = [s for s in expected if s in found]
    if len(present) < 2:
        return 1.0 if present else 0.0
    pairs = list(zip(present, present[1:]))
    return sum(1 for a, b in pairs if found[a] < found[b]) / len(pairs)


def analyze(ctx: Context, params: Mapping[str, Any]) -> ModuleResult:
    weights = params["core_weights"]
    expected = tuple(s for s in EXPECTED_ORDER if s in weights)
    found = ctx.section_index
    feedback: list[str] = []

    presence = 0.0
    for section, weight in weights.items():
        if section in found:
            presence += weight
        elif section == "conclusion" and "discussion" in found:
            presence += weight / 2
            feedback.append("Ayri bir Sonuc bolumu yok; Tartisma bolumu sonuclari tek basina tasiyor.")
        else:
            feedback.append(f"'{SECTION_LABELS_TR[section]}' bolumu tespit edilemedi.")

    order = _order_ratio(found, expected)
    if order < 1.0:
        feedback.append("Bolum sirasi beklenen akademik akisa (Ozet > Giris > Yontem > Bulgular > Sonuc) uymuyor.")

    has_refs = "references" in found
    if not has_refs:
        feedback.append("Kaynakca bolumu tespit edilemedi.")

    score = round(clamp(presence * 0.75 + order * 100 * 0.15 + (10 if has_refs else 0)), 1)

    # Hic baslik bulunamadiysa sorun buyuk olasilikla metin cikarimindadir (bicim kaybi).
    confidence = 0.9 if len(found) >= 3 else 0.6 if found else 0.3
    if not found:
        feedback.insert(0, "Hicbir bolum basligi tespit edilemedi; basliklar ayri satirlarda olmayabilir.")

    return ModuleResult(
        module="structure",
        agent="structure_editor",
        agent_role="Yapisal Editor",
        score=score,
        feedback=feedback,
        metrics={
            "sections_found": sorted(found, key=found.get),
            "expected_sections": list(weights),
            "order_ratio": round(order, 2),
            "field_profile": params["profile_label"],
        },
        confidence=confidence,
    )
