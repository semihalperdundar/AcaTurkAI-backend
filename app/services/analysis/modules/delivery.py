"""
Modul: score_delivery - anlatim akisi ve akademik ton (proxy metrikler).

- Cumle uzunlugu dagilimi: ortalama, uzun cumle orani, varyasyon katsayisi (CV).
- Ton: gayriresmi isaretler (1. tekil sahis zamiri, unlem, EN kisaltmalari) / 1000 kelime.
- Akis: gecis/baglac ifadesi iceren cumle orani.

Turkce cumleler eklemeli yapi nedeniyle kelime sayisi olarak daha kisadir ->
bantlar dile gore ayri.
"""
import re
import statistics

from app.services.analysis.text_utils import ModuleResult, band_score, clamp, normalize, tokenize

LENGTH_BANDS = {
    "en": {"ideal": (15, 25), "zero": (6, 40)},
    "tr": {"ideal": (10, 20), "zero": (4, 35)},
}
LONG_SENTENCE_WORDS = {"en": 40, "tr": 35}
CV_BAND = {"ideal": (0.35, 0.75), "zero": (0.10, 1.30)}
FLOW_BAND = {"ideal": (0.10, 0.40), "zero": (0.0, 0.75)}

TRANSITIONS: dict[str, tuple[str, ...]] = {
    "en": (
        "however", "therefore", "moreover", "furthermore", "consequently", "thus", "hence",
        "additionally", "nevertheless", "similarly", "in contrast", "on the other hand",
        "in addition", "as a result", "for example", "for instance", "accordingly",
    ),
    "tr": (
        "ancak", "dolayısıyla", "ayrıca", "bununla birlikte", "öte yandan", "buna karşın",
        "sonuç olarak", "bu nedenle", "benzer şekilde", "nitekim", "diğer taraftan",
        "ne var ki", "örneğin", "bu bağlamda", "buna ek olarak", "aksine", "böylece",
    ),
}
FIRST_PERSON_SINGULAR = {
    "en": frozenset({"i", "me", "my", "mine", "myself"}),
    "tr": frozenset({"ben", "benim", "bana", "beni", "bende", "benden"}),
}
_CONTRACTION_RE = re.compile(r"\b\w+(?:n't|'re|'m|'ll|'ve|'d)\b", re.IGNORECASE)


def _transition_patterns(lang: str) -> list[re.Pattern]:
    return [re.compile(rf"(?<!\w){re.escape(t)}(?!\w)") for t in TRANSITIONS[lang]]


def analyze(sentences: list[str], tokens: list[str], language: str) -> ModuleResult:
    lang = language if language in LENGTH_BANDS else "en"
    feedback: list[str] = []

    lengths = [len(tokenize(s)) for s in sentences] or [0]
    mean_len = statistics.fmean(lengths)
    cv = statistics.pstdev(lengths) / mean_len if mean_len else 0.0
    long_ratio = sum(1 for n in lengths if n > LONG_SENTENCE_WORDS[lang]) / len(lengths)

    patterns = _transition_patterns(lang)
    with_transition = sum(1 for s in sentences if any(p.search(normalize(s)) for p in patterns))
    flow_ratio = with_transition / len(sentences) if sentences else 0.0

    per_1000 = 1000 / max(len(tokens), 1)
    fps_rate = sum(1 for t in tokens if t in FIRST_PERSON_SINGULAR[lang]) * per_1000
    exclaim_rate = sum(s.count("!") for s in sentences) * per_1000
    contraction_rate = (
        len(_CONTRACTION_RE.findall(" ".join(sentences))) * per_1000 if lang == "en" else 0.0
    )
    informal_rate = fps_rate + 2 * exclaim_rate + contraction_rate
    tone_score = clamp(100 - 15 * informal_rate)

    length_score = band_score(mean_len, **LENGTH_BANDS[lang])
    long_score = band_score(long_ratio, ideal=(0.0, 0.10), zero=(0.0, 0.40))
    cv_score = band_score(cv, **CV_BAND)
    flow_score = band_score(flow_ratio, **FLOW_BAND)
    score = round(
        clamp(0.35 * length_score + 0.15 * long_score + 0.15 * cv_score + 0.15 * tone_score + 0.20 * flow_score),
        1,
    )

    lo, hi = LENGTH_BANDS[lang]["ideal"]
    if mean_len > hi:
        feedback.append(f"Ortalama cumle uzunlugu yuksek ({mean_len:.1f} kelime); uzun cumleleri bolun.")
    elif mean_len < lo:
        feedback.append(f"Ortalama cumle uzunlugu dusuk ({mean_len:.1f} kelime); anlatim kopuk okunabilir.")
    if long_ratio > 0.10:
        feedback.append(
            f"Cumlelerin %{long_ratio * 100:.0f}'i {LONG_SENTENCE_WORDS[lang]} kelimeden uzun; hakem okunabilirligi dusurur."
        )
    if cv < CV_BAND["ideal"][0]:
        feedback.append("Cumle uzunluklari cok tekduze; ritim monoton.")
    elif cv > CV_BAND["ideal"][1]:
        feedback.append("Cumle uzunluklari asiri dengesiz; cok kisa ve cok uzun cumleler karisik.")
    if flow_ratio < FLOW_BAND["ideal"][0]:
        feedback.append("Gecis ifadeleri az; paragraflar arasi mantiksal bag zayif.")
    elif flow_ratio > FLOW_BAND["ideal"][1]:
        feedback.append("Gecis ifadeleri asiri sik; baglaclar mekanik tekrar izlenimi veriyor.")
    if fps_rate > 1:
        feedback.append("Birinci tekil sahis kullanimi yuksek; akademik metinde nesnel anlatim tercih edilir.")
    if exclaim_rate > 0 or contraction_rate > 0:
        feedback.append("Gayriresmi isaretler (unlem, kisaltmali fiiller) tespit edildi.")

    return ModuleResult(
        module="delivery",
        agent="delivery_reviewer",
        agent_role="Anlatim ve Akis Hakemi",
        score=score,
        feedback=feedback,
        metrics={
            "sentence_count": len(sentences),
            "mean_sentence_length": round(mean_len, 1),
            "sentence_length_cv": round(cv, 2),
            "long_sentence_ratio": round(long_ratio, 3),
            "transition_ratio": round(flow_ratio, 3),
            "informal_markers_per_1000": round(informal_rate, 2),
        },
        confidence=0.85 if len(sentences) >= 40 else 0.6,
    )
