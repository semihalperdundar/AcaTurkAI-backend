"""
Modul: score_title - baslik kalitesi.

Olculenler: uzunluk (dile gore bant), baslik kavramlarinin ozet/giriste karsiligi,
bicim (nokta ile bitis, tamami buyuk harf, belirsiz veya abartili ifade).
Baslik = ilk tespit edilen bolum basligindan onceki ilk anlamli satir.
"""
import re

from app.services.analysis.modules.structure import detect_sections, extract_sections
from app.services.analysis.text_utils import (
    STOPWORDS,
    ModuleResult,
    band_score,
    clamp,
    count_words,
    normalize,
    tokenize,
)

# Turkce eklemeli yapi -> ayni icerik daha az kelimeyle ifade edilir.
LENGTH_BANDS = {
    "en": {"ideal": (8, 16), "zero": (3, 30)},
    "tr": {"ideal": (6, 14), "zero": (2, 28)},
}
TITLE_MAX_WORDS = 30
STEM_LEN = 5  # Turkce ekler icin kaba kok eslemesi (degerlendirme -> degerl)

VAGUE_RE = re.compile(
    r"\b(a study of|a study on|an investigation of|an investigation into|some aspects|various|"
    r"üzerine bir çalışma|üzerine bir inceleme|bazı|çeşitli)"
)
HYPE_RE = re.compile(r"\b(novel|groundbreaking|revolutionary|first ever|çığır açan|devrim niteliğinde)")


def find_title(text: str) -> str | None:
    lines = text.split("\n")
    first_section = min(detect_sections(text).values(), default=len(lines))
    for line in lines[:first_section]:
        stripped = line.strip()
        if 2 <= count_words(stripped) <= TITLE_MAX_WORDS:
            return stripped
    return None


def _content_stems(tokens: list[str]) -> set[str]:
    return {t[:STEM_LEN] for t in tokens if len(t) >= 4 and t not in STOPWORDS}


def analyze(text: str, language: str, field: str | None = None) -> ModuleResult:
    lang = language if language in LENGTH_BANDS else "en"
    title = find_title(text)
    if title is None:
        return ModuleResult(
            module="title",
            agent="title_reviewer",
            agent_role="Baslik Hakemi",
            score=0.0,
            feedback=["Baslik tespit edilemedi; ilk satirda ayri bir baslik olmayabilir."],
            metrics={"title": None},
            confidence=0.3,
        )

    feedback: list[str] = []
    word_count = count_words(title)
    band = LENGTH_BANDS[lang]
    length_score = band_score(word_count, band["ideal"], band["zero"])
    if word_count < band["ideal"][0]:
        feedback.append(f"Baslik kisa ({word_count} kelime); calismanin kapsami ve yontemi basliktan anlasilmiyor.")
    elif word_count > band["ideal"][1]:
        feedback.append(f"Baslik uzun ({word_count} kelime); alt baslik kullanarak sadelestirin.")

    sections = extract_sections(text)
    reference = " ".join(sections.get(s, "") for s in ("abstract", "introduction")) or text[:5000]
    title_stems = _content_stems(tokenize(title))
    overlap = len(title_stems & _content_stems(tokenize(reference))) / len(title_stems) if title_stems else 0.0
    if overlap < 0.5:
        feedback.append(
            f"Baslik kavramlarinin yalnizca %{overlap * 100:.0f}'i ozet/giriste geciyor; baslik icerigi temsil etmiyor olabilir."
        )

    lowered = normalize(title)
    ends_with_period = title.endswith(".")
    all_caps = title.isupper()
    vague = bool(VAGUE_RE.search(lowered))
    hype = bool(HYPE_RE.search(lowered))
    form_score = clamp(100 - 40 * ends_with_period - 40 * all_caps - 30 * vague - 30 * hype)
    if ends_with_period:
        feedback.append("Baslik nokta ile bitmemeli.")
    if all_caps:
        feedback.append("Baslik tamamen buyuk harfle yazilmis; dergi yazim kuralina gore duzenleyin.")
    if vague:
        feedback.append("Baslikta belirsiz ifade var ('bazi', 'a study of' vb.); arastirma odagini dogrudan belirtin.")
    if hype:
        feedback.append("Baslikta abartili ifade var ('cigir acan', 'novel' vb.); hakemler bunu olumsuz karsilar.")

    score = round(clamp(0.45 * length_score + 0.40 * overlap * 100 + 0.15 * form_score), 1)

    return ModuleResult(
        module="title",
        agent="title_reviewer",
        agent_role="Baslik Hakemi",
        score=score,
        feedback=feedback,
        metrics={
            "title": title,
            "word_count": word_count,
            "concept_overlap": round(overlap, 2),
            "has_subtitle": ":" in title,
            "ends_with_period": ends_with_period,
            "all_caps": all_caps,
            "vague_phrase": vague,
            "hype_phrase": hype,
        },
        confidence=0.8 if sections else 0.5,
    )
