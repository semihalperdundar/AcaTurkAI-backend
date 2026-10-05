"""
Modul: score_literature - alanyazin taramasinin derinligi ve sentezi.

Olculenler: alanyazin kapsaminin metne orani, 100 kelime basina metin ici atif
yogunlugu, coklu kaynakli atif (sentez) orani, kronolojik/karsilastirmali ifadeler.
Kapsam: ayri alanyazin bolumu varsa o, yoksa Giris (bircok makale ikisini birlestirir).
Alan farki: hukukta alanyazin argumantasyona yayilir -> tum govde taranir, oran olculmez.
"""
import re

from app.services.analysis.modules.references import body_before_references, count_in_text_citations
from app.services.analysis.modules.structure import extract_sections
from app.services.analysis.text_utils import ModuleResult, band_score, clamp, count_words, normalize

SECTION_RATIO_BAND = {"ideal": (0.10, 0.30), "zero": (0.02, 0.55)}
DENSITY_BANDS = {
    "default": {"ideal": (1.0, 4.0), "zero": (0.1, 8.0)},
    "law": {"ideal": (0.5, 4.0), "zero": (0.05, 8.0)},
}
SYNTHESIS_PHRASES_TARGET = 3

SYNTHESIS_PATTERNS: tuple[re.Pattern, ...] = tuple(
    re.compile(p)
    for p in (
        r"\b(recent stud|recent research|in recent years|over the past|to date|previous stud|prior stud|"
        r"prior work|earlier stud|previous research)",
        r"\b(consistent with|in line with|in contrast|contrary to|similarly|whereas|however)",
        r"\b(son yıllarda|güncel|önceki çalışma|önceki araştırma|daha önce yapılan|alanyazında|literatürde|"
        r"yapılan çalışmalar)",
        r"\b(tutarlı|paralel|aksine|farklı olarak|benzer şekilde|bununla birlikte|ancak)",
    )
)
_MULTI_SOURCE_RE = re.compile(r"\([^()]*(?:19|20)\d{2}[a-z]?\s*;[^()]*(?:19|20)\d{2}[a-z]?\)")


def analyze(text: str, language: str, field: str | None = None) -> ModuleResult:
    is_law = field == "law"
    sections = extract_sections(text)
    body = body_before_references(text)

    if is_law:
        scope, source = body, "body"
    elif sections.get("literature"):
        scope, source = sections["literature"], "literature"
    elif sections.get("introduction"):
        scope, source = sections["introduction"], "introduction"
    else:
        scope, source = "", None

    if not scope:
        return ModuleResult(
            module="literature",
            agent="literature_reviewer",
            agent_role="Alanyazin Hakemi",
            score=0.0,
            feedback=["Alanyazin veya Giris bolumu tespit edilemedi; calisma kuramsal zemine oturmuyor."],
            metrics={"scope": None},
            confidence=0.4,
        )

    feedback: list[str] = []
    scope_words = count_words(scope)
    total_words = count_words(body)
    section_ratio = scope_words / total_words if total_words else 0.0

    citations = count_in_text_citations(scope)
    density = 100 * citations / scope_words if scope_words else 0.0
    band = DENSITY_BANDS["law" if is_law else "default"]
    density_score = band_score(density, band["ideal"], band["zero"])
    if citations == 0:
        feedback.insert(0, "Alanyazin kapsaminda metin ici atif yok; iddialar kaynaga dayandirilmamis.")
    elif density < band["ideal"][0]:
        feedback.append(f"Atif yogunlugu dusuk (100 kelimede {density:.1f}); temel iddialari kaynaklarla destekleyin.")
    elif density > band["ideal"][1]:
        feedback.append(f"Atif yogunlugu cok yuksek (100 kelimede {density:.1f}); kaynak siralamak yerine sentez yapin.")

    multi_source = len(_MULTI_SOURCE_RE.findall(scope))
    lowered = normalize(scope)
    synthesis_hits = sum(1 for p in SYNTHESIS_PATTERNS if p.search(lowered))
    synthesis_score = 100 * min(1.0, (synthesis_hits + min(multi_source, 2)) / SYNTHESIS_PHRASES_TARGET)
    if synthesis_score < 100:
        feedback.append(
            "Alanyazin sentezi zayif: calismalari karsilastiran/donemlendiren ifadeler "
            "('onceki calismalar', 'in contrast', 'son yillarda') ve coklu atif (A, 2019; B, 2021) az."
        )

    if is_law:
        score = 0.55 * density_score + 0.45 * synthesis_score
        ratio_score = None
    else:
        ratio_score = band_score(section_ratio, SECTION_RATIO_BAND["ideal"], SECTION_RATIO_BAND["zero"])
        if section_ratio < SECTION_RATIO_BAND["ideal"][0]:
            feedback.append(f"Alanyazin kapsami metnin yalnizca %{section_ratio * 100:.0f}'i; tartisma zemini dar.")
        elif section_ratio > SECTION_RATIO_BAND["ideal"][1]:
            feedback.append(f"Alanyazin kapsami metnin %{section_ratio * 100:.0f}'i; ozgun katkiya yer kalmiyor.")
        score = 0.30 * ratio_score + 0.40 * density_score + 0.30 * synthesis_score

    if source == "introduction":
        feedback.append("Ayri bir alanyazin bolumu yok; degerlendirme Giris uzerinden yapildi.")

    return ModuleResult(
        module="literature",
        agent="literature_reviewer",
        agent_role="Alanyazin Hakemi",
        score=round(clamp(score), 1),
        feedback=feedback,
        metrics={
            "scope": source,
            "scope_words": scope_words,
            "section_ratio": None if is_law else round(section_ratio, 3),
            "in_text_citations": citations,
            "citations_per_100_words": round(density, 2),
            "multi_source_citations": multi_source,
            "synthesis_phrase_groups": synthesis_hits,
        },
        confidence=0.8 if source == "literature" else 0.6,
    )
