"""
Modul: score_findings - bulgularin kanit niteligi.

Uc profil:
  - quantitative (varsayilan; STEM/saglik/sosyal nicel): sayi yogunlugu, istatistik
    isaretleri (p <, β, CI, anlamli), tablo/sekil atfi, bolumun metne orani.
  - qualitative: alinti (dogrudan ifade), katilimci kodlari (P3, K5), tema/kategori dili.
    Metin nitel isaretleri istatistik isaretlerinden fazla iceriyorsa secilir.
  - law: mevzuat/ictihat atiflari (madde, m. 12, Yargitay, E./K.) ve alinti; ayri bulgular
    bolumu beklenmez, tum govde taranir ve oran olculmez.
"""
import re

from app.services.analysis.modules.references import body_before_references
from app.services.analysis.modules.structure import extract_sections
from app.services.analysis.text_utils import ModuleResult, band_score, clamp, count_words, normalize

SECTION_RATIO_BAND = {"ideal": (0.15, 0.40), "zero": (0.03, 0.65)}
NUMBER_DENSITY_BAND = {"ideal": (1.5, 8.0), "zero": (0.2, 20.0)}

STAT_PATTERNS: tuple[re.Pattern, ...] = tuple(
    re.compile(p)
    for p in (
        r"\bp\s*[<=>≤]\s*0?\.\d+",
        r"(β|\bbeta\b|\br\s*=\s*-?0?\.\d+|\bt\s*\(\d+\)|\bf\s*\(\d+\s*,\s*\d+\)|χ2|\bchi[- ]square)",
        r"(\bci\b|confidence interval|%\s?95|95\s?%|güven aralığı|odds ratio|\bor\s*=)",
        r"\b(significant|anlamlı|anlamsız|effect size|etki büyüklüğü|cohen)",
        r"\b(mean|sd\b|standard deviation|ortalama|standart sapma|median|medyan)",
    )
)
QUAL_MARKER_RE = re.compile(
    r"\b(theme|thematic|category|categories|code[sd]?\b|participant [a-z]?\d|interviewee|"
    r"tema|kategori|kod\b|kodla|görüşmeci|katılımcı \d|alt tema)"
)
LAW_REFERENCE_RE = re.compile(
    r"(\b(article|art\.|section|madde|md\.|m\.)\s*\d+|\b(yargıtay|danıştay|anayasa mahkemesi|aym|aihm|echr|"
    r"court of|supreme court)\b|\be\.\s*\d{4}/\d+|\bk\.\s*\d{4}/\d+|\b(tck|tmk|tbk|hmk|cmk)\b)"
)
QUOTE_RE = re.compile(r"[\"“”«]([^\"“”»]{25,})[\"“”»]")
PARTICIPANT_CODE_RE = re.compile(r"\b(?:P|K|Ö|T)\d{1,3}\b")
TABLE_FIGURE_RE = re.compile(r"\b(table|figure|fig\.|tablo|şekil|grafik)\s*\d+")
_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?\s*%?")
QUALITATIVE_METHOD_RE = re.compile(r"\b(qualitative|interview|thematic|nitel|görüşme|tematik|fenomenoloji)")


def _profile(field: str | None, text_lowered: str) -> str:
    if field == "law":
        return "law"
    stat_hits = sum(1 for p in STAT_PATTERNS if p.search(text_lowered))
    qual_hits = len(QUAL_MARKER_RE.findall(text_lowered)) + len(QUALITATIVE_METHOD_RE.findall(text_lowered))
    return "qualitative" if qual_hits > stat_hits and QUALITATIVE_METHOD_RE.search(text_lowered) else "quantitative"


def analyze(text: str, language: str, field: str | None = None) -> ModuleResult:
    sections = extract_sections(text)
    body = body_before_references(text)
    profile = _profile(field, normalize(body))
    feedback: list[str] = []

    if profile == "law":
        scope, source = body, "body"
    elif sections.get("results"):
        scope, source = sections["results"], "results"
    elif sections.get("discussion"):
        scope, source = sections["discussion"], "discussion"
        feedback.append("Ayri bir Bulgular bolumu yok; bulgular Tartisma icinde degerlendirildi.")
    else:
        scope, source = body, None
        feedback.append("Bulgular bolumu tespit edilemedi; kanit tum metinde arandi.")

    lowered = normalize(scope)
    scope_words = count_words(scope)
    total_words = count_words(body)
    section_ratio = scope_words / total_words if total_words else 0.0
    ratio_score = band_score(section_ratio, SECTION_RATIO_BAND["ideal"], SECTION_RATIO_BAND["zero"])
    quotes = len(QUOTE_RE.findall(scope))
    metrics: dict = {"profile": profile, "scope": source, "scope_words": scope_words, "quotes": quotes}

    if profile == "law":
        legal_refs = len(LAW_REFERENCE_RE.findall(lowered))
        if legal_refs < 5:
            feedback.insert(0, f"Mevzuat/ictihat atfi az ({legal_refs}); hukuki tespitler norm ve kararlara dayandirilmali.")
        score = 60 * min(1.0, legal_refs / 5) + 40 * min(1.0, quotes / 2)
        metrics["legal_references"] = legal_refs
    elif profile == "qualitative":
        codes = len(PARTICIPANT_CODE_RE.findall(scope))
        themes = len(QUAL_MARKER_RE.findall(lowered))
        evidence = quotes + codes
        if evidence < 4:
            feedback.insert(0, "Nitel bulgular dogrudan katilimci alintilariyla (P3: \"...\") yeterince desteklenmemis.")
        if themes == 0:
            feedback.append("Tema/kategori yapisi gorunmuyor; bulgulari temalar altinda sunun.")
        score = 45 * min(1.0, evidence / 4) + 30 * min(1.0, themes / 3) + 0.25 * ratio_score
        metrics.update(participant_codes=codes, theme_markers=themes)
    else:
        numbers = len(_NUMBER_RE.findall(scope))
        density = 100 * numbers / scope_words if scope_words else 0.0
        stat_groups = sum(1 for p in STAT_PATTERNS if p.search(lowered))
        has_tables = bool(TABLE_FIGURE_RE.search(lowered))
        if density < NUMBER_DENSITY_BAND["ideal"][0]:
            feedback.insert(0, f"Bulgularda nicel kanit az (100 kelimede {density:.1f} sayi); sonuclari sayisal raporlayin.")
        if stat_groups < 3:
            feedback.append("Istatistik raporu eksik: test istatistigi, p degeri, etki buyuklugu ve guven araligi verin.")
        if not has_tables:
            feedback.append("Bulgularda tablo/sekil atfi yok (Tablo 1, Figure 2).")
        score = (
            0.35 * band_score(density, NUMBER_DENSITY_BAND["ideal"], NUMBER_DENSITY_BAND["zero"])
            + 25 * min(1.0, stat_groups / 3)
            + 15 * has_tables
            + 0.25 * ratio_score
        )
        metrics.update(numbers_per_100_words=round(density, 2), stat_marker_groups=stat_groups, table_figure_refs=has_tables)

    if profile != "law":
        metrics["section_ratio"] = round(section_ratio, 3)
        if source and section_ratio < SECTION_RATIO_BAND["ideal"][0]:
            feedback.append(f"Bulgular metnin yalnizca %{section_ratio * 100:.0f}'i; temel sonuclar orantisiz kisa.")
        if source is None:
            score *= 0.5

    return ModuleResult(
        module="findings",
        agent="findings_reviewer",
        agent_role="Bulgular Hakemi",
        score=round(clamp(score), 1),
        feedback=feedback,
        metrics=metrics,
        confidence=0.8 if source in ("results", "body") else 0.6 if source else 0.4,
    )
