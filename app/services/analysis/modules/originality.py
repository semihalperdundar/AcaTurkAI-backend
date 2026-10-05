"""
Modul: score_originality - ozgunluk sinyalleri (kural tabanli vekil olcum).

Olculenler:
  - Arastirma boslugu ifadeleri (ozet + giris): "little is known", "ilk kez", "eksiklik" ...
  - Acik katki beyani ("this study contributes", "katki").
  - Bolumler arasi tekrar: govdedeki tekrarlanan 6-kelimelik dizilerin orani.
  - Kaynakcaya gore sozcuk yeniligi: govde icerik koklerinden kaynakcada gecmeyenlerin orani.
Ozgunluk kural tabanli olarak yalnizca dolayli olculebilir -> guven bilincli olarak dusuk.
Alan farki: hukukta bosluk, tartismali/yerlesmemis ictihat ifadeleriyle de kurulur.
"""
import re
from collections import Counter

from app.services.analysis.modules.references import body_before_references
from app.services.analysis.modules.structure import extract_sections
from app.services.analysis.text_utils import ModuleResult, band_score, clamp, content_stems, normalize, tokenize

GAP_PATTERNS: tuple[re.Pattern, ...] = tuple(
    re.compile(p)
    for p in (
        r"\b(little is known|remains unclear|remains unknown|limited research|few studies|no study|no prior|"
        r"has not been|have not been|yet to be|gap in|research gap|understudied|overlooked)",
        r"\b(first time|for the first time|novel|to our knowledge|to the best of our knowledge|"
        r"unlike previous|extends prior|new approach)",
        r"\b(ilk kez|ilk defa|eksiklik|boşluk|sınırlı sayıda|az sayıda|bilindiği kadarıyla|henüz|"
        r"ele alınmamış|yeterince incelenmemiş|çalışılmamış|özgün)",
    )
)
LAW_GAP_PATTERN = re.compile(
    r"\b(controvers|unsettled|divergent case law|conflicting decisions|tartışmalı|içtihat farklılığı|"
    r"çelişkili karar|yerleşik değil|doktrinde görüş ayrılığı)"
)
CONTRIBUTION_RE = re.compile(
    r"\b(contribut|this study (adds|extends|offers|provides)|we propose|katkı|katkı sağla|alana kazandır)"
)
GAP_TARGET = 2
SHINGLE = 6
REPETITION_BAND = {"ideal": (0.0, 0.05), "zero": (-1.0, 0.30)}
NOVELTY_BAND = {"ideal": (0.60, 1.0), "zero": (0.20, 1.01)}


def repetition_ratio(tokens: list[str], n: int = SHINGLE) -> float:
    """Birden fazla gecen n-gram orneklerinin tum n-gramlara orani (0 = hic tekrar yok)."""
    grams = [tuple(tokens[i : i + n]) for i in range(len(tokens) - n + 1)]
    if not grams:
        return 0.0
    counts = Counter(grams)
    return sum(c for c in counts.values() if c > 1) / len(grams)


def analyze(text: str, language: str, field: str | None = None) -> ModuleResult:
    is_law = field == "law"
    sections = extract_sections(text)
    body = body_before_references(text)
    feedback: list[str] = []

    framing = " ".join(sections.get(s, "") for s in ("abstract", "introduction", "literature")).strip()
    framing_source = "abstract+introduction" if framing else "body"
    lowered = normalize(framing or body)

    patterns = GAP_PATTERNS + ((LAW_GAP_PATTERN,) if is_law else ())
    gap_hits = sum(1 for p in patterns if p.search(lowered))
    gap_score = 100 * min(1.0, gap_hits / GAP_TARGET)
    if gap_hits == 0:
        feedback.insert(0, "Arastirma boslugu belirtilmemis ('little is known', 'ilk kez', 'eksiklik' vb.); katkinin gerekcesi yok.")
    elif gap_hits < GAP_TARGET:
        feedback.append("Arastirma boslugu zayif tanimlanmis; onceki calismalarin neyi eksik biraktigini acikca yazin.")

    has_contribution = bool(CONTRIBUTION_RE.search(normalize(body)))
    if not has_contribution:
        feedback.append("Acik bir katki beyani yok ('Bu calisma ... katki saglamaktadir').")

    body_tokens = tokenize(body)
    repetition = repetition_ratio(body_tokens)
    repetition_score = band_score(repetition, REPETITION_BAND["ideal"], REPETITION_BAND["zero"])
    if repetition > REPETITION_BAND["ideal"][1]:
        feedback.append(f"Metnin %{repetition * 100:.0f}'i tekrar eden ifade dizilerinden olusuyor; bolumler arasi kopyalamayi azaltin.")

    reference_block = sections.get("references", "")
    novelty = None
    if reference_block:
        body_stems = content_stems(body_tokens)
        ref_stems = content_stems(tokenize(reference_block))
        novelty = len(body_stems - ref_stems) / len(body_stems) if body_stems else 0.0
        novelty_score = band_score(novelty, NOVELTY_BAND["ideal"], NOVELTY_BAND["zero"])
        if novelty < NOVELTY_BAND["ideal"][0]:
            feedback.append("Govde sozcuk dagarcigi buyuk olcude kaynakcadaki basliklarla ortusuyor; ozgun cerceve zayif.")
        score = 0.35 * gap_score + 0.15 * 100 * has_contribution + 0.30 * repetition_score + 0.20 * novelty_score
    else:
        score = (0.35 * gap_score + 0.15 * 100 * has_contribution + 0.30 * repetition_score) / 0.80

    return ModuleResult(
        module="originality",
        agent="originality_reviewer",
        agent_role="Ozgunluk Hakemi",
        score=round(clamp(score), 1),
        feedback=feedback,
        metrics={
            "framing_source": framing_source,
            "gap_indicator_groups": gap_hits,
            "has_contribution_statement": has_contribution,
            "repetition_ratio": round(repetition, 3),
            "vocabulary_novelty_vs_references": None if novelty is None else round(novelty, 2),
        },
        confidence=0.5,
    )
