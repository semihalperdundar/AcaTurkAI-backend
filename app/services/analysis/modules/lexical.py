"""
Modul: score_lexical - sozcuk cesitliligi ve akademik sozcuk yogunlugu.

- MATTR (Moving-Average TTR, pencere=100): ham TTR metin uzunluguyla duser,
  MATTR uzunluktan bagimsizdir -> farkli uzunlukta makaleler karsilastirilabilir.
- Akademik sozcuk yogunlugu: kok-onek listesi (EN: AWL alt kumesi, TR: muadil kokler).
- Tekrar: tek bir icerik sozcugunun asiri kullanimi.

Bant esikleri v1 sezgiseldir; corpus normlari (corpus_works) olusunca alan
bazli kalibre edilecek.
"""
from collections import Counter

from app.services.analysis.text_utils import ModuleResult, band_score, clamp, matches_stem

MATTR_WINDOW = 100

ACADEMIC_STEMS: dict[str, tuple[str, ...]] = {
    "en": (
        "analy", "approach", "assess", "assum", "concept", "consisten", "context", "criteri",
        "data", "defin", "deriv", "empiric", "establish", "estimat", "evaluat", "eviden",
        "factor", "framework", "hypothes", "identif", "implica", "indicat", "interpret",
        "investigat", "method", "paradigm", "participant", "perspectiv", "phenomen",
        "signific", "sampl", "theor", "valid", "variab", "correlat", "furthermore",
        "moreover", "consequen", "demonstrat", "substantia", "conceptual", "structur",
    ),
    "tr": (
        "analiz", "yöntem", "kavram", "kuram", "hipotez", "değişken", "bulgu", "veri",
        "örneklem", "değerlendir", "yaklaşım", "bağlam", "çerçeve", "anlamlı", "ilişki",
        "etki", "süreç", "model", "katılımcı", "araştırma", "incele", "kapsam", "tutarlı",
        "gösterge", "ölçek", "geçerlik", "güvenirlik", "istatistik", "olgu", "varsayım",
        "kuramsal", "ampirik", "nitel", "nicel", "betimle", "yorumla", "korelasyon",
    ),
}
STOPWORDS: dict[str, frozenset[str]] = {
    "en": frozenset(
        "the of and to in a is that for on with as are by this be from an was were which or "
        "it at not have has been their its can these also such than more other between we "
        "our they there may into".split()
    ),
    "tr": frozenset(
        "ve bir bu da de ile için olarak olan gibi daha çok en ise ya veya ancak kadar sonra "
        "göre olduğu her şekilde arasında ki ne o şu bu ilgili üzerinde olan ayrıca".split()
    ),
}
# Turkce eklemeli yapi ayni koku farkli tokenlara boler -> MATTR dogal olarak yuksek.
MATTR_BANDS = {
    "en": {"ideal": (0.68, 0.82), "zero": (0.50, 0.95)},
    "tr": {"ideal": (0.78, 0.92), "zero": (0.60, 0.99)},
}
DENSITY_BANDS = {
    "en": {"ideal": (0.04, 0.14), "zero": (0.0, 0.30)},
    "tr": {"ideal": (0.04, 0.14), "zero": (0.0, 0.30)},
}
OVERUSE_THRESHOLD = 0.025  # icerik sozcuklerinin %2.5'inden fazlasi tek kelime
OVERUSE_MIN_COUNT = 8


def mattr(tokens: list[str], window: int = MATTR_WINDOW) -> float:
    if not tokens:
        return 0.0
    if len(tokens) <= window:
        return len(set(tokens)) / len(tokens)
    counts = Counter(tokens[:window])
    total = len(counts)
    for i in range(window, len(tokens)):
        counts[tokens[i]] += 1
        old = tokens[i - window]
        counts[old] -= 1
        if counts[old] == 0:
            del counts[old]
        total += len(counts)
    return total / window / (len(tokens) - window + 1)


def analyze(tokens: list[str], language: str) -> ModuleResult:
    lang = language if language in ACADEMIC_STEMS else "en"
    feedback: list[str] = []

    diversity = mattr(tokens)
    academic_hits = sum(1 for t in tokens if matches_stem(t, ACADEMIC_STEMS[lang]))
    density = academic_hits / len(tokens) if tokens else 0.0

    content = [t for t in tokens if t not in STOPWORDS[lang] and len(t) > 2]
    overused = [
        word
        for word, n in Counter(content).most_common(5)
        if content and n >= OVERUSE_MIN_COUNT and n / len(content) > OVERUSE_THRESHOLD
    ]

    mattr_score = band_score(diversity, **MATTR_BANDS[lang])
    density_score = band_score(density, **DENSITY_BANDS[lang])
    penalty = min(10, 3 * len(overused))
    score = round(clamp(0.5 * mattr_score + 0.5 * density_score - penalty), 1)

    lo, hi = MATTR_BANDS[lang]["ideal"]
    if diversity < lo:
        feedback.append(f"Sozcuk cesitliligi dusuk (MATTR {diversity:.2f}); ayni ifadeler sik tekrarlaniyor.")
    elif diversity > hi:
        feedback.append(f"Sozcuk cesitliligi olagan disi yuksek (MATTR {diversity:.2f}); terim tutarliligini kontrol edin.")
    dlo, dhi = DENSITY_BANDS[lang]["ideal"]
    if density < dlo:
        feedback.append(f"Akademik sozcuk yogunlugu dusuk (%{density * 100:.1f}); anlatim gundelik dile kayiyor.")
    elif density > dhi:
        feedback.append(f"Akademik sozcuk yogunlugu cok yuksek (%{density * 100:.1f}); okunabilirlik zarar gorebilir.")
    if overused:
        feedback.append(f"Asiri tekrar eden sozcukler: {', '.join(overused)}. Es anlamli ifadelerle cesitlendirin.")

    return ModuleResult(
        module="lexical",
        agent="lexical_reviewer",
        agent_role="Dil ve Sozcuk Hakemi",
        score=score,
        feedback=feedback,
        metrics={
            "token_count": len(tokens),
            "mattr": round(diversity, 3),
            "mattr_window": MATTR_WINDOW,
            "academic_density": round(density, 4),
            "overused_words": overused,
        },
        confidence=0.85 if len(tokens) >= 1000 else 0.6,
    )
