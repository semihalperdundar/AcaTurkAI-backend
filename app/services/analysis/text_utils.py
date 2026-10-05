"""
Analiz modullerinin paylastigi saf (ag/DB gerektirmeyen) metin yardimcilari.

v1 bilincli olarak spaCy/model indirmesi gerektirmez: regex tokenizasyon +
kok-onek eslemesi (Turkce eklemeli yapida kelime listesinden daha isabetli).
"""
import re
from dataclasses import dataclass, field

_WORD_RE = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)?")
# Kisaltmalardan sonra cumle bolme yapma (et al., vb., orn., Fig., Dr., s., No.)
_ABBREV_RE = re.compile(
    r"\b(et al|vb|vs|örn|bkz|Fig|Eq|Dr|Prof|Doç|Yrd|No|s|pp|vol|ss|cf|e\.g|i\.e)\.",
    re.IGNORECASE,
)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[\"'“(\[]?[A-ZÇĞİÖŞÜ0-9])")
_HEADING_NUMBER_RE = re.compile(r"^(?:\d+(?:\.\d+)*\.?|[IVXLC]+\.|[A-Z]\.)\s*")

_TR_STOPWORDS = frozenset(
    "ve bir bu da de ile için olarak olan gibi daha çok en ise ya veya ancak "
    "kadar sonra göre olduğu bu nedenle her şekilde arasında".split()
)
_EN_STOPWORDS = frozenset(
    "the of and to in a is that for on with as are by this be from an was "
    "were which or it at not have has".split()
)
STOPWORDS = _TR_STOPWORDS | _EN_STOPWORDS


def normalize(word: str) -> str:
    """Turkce-guvenli kucuk harf: 'İ'.lower() birlesik nokta uretir, onu engelle."""
    return word.replace("İ", "i").lower()


def tokenize(text: str) -> list[str]:
    return [normalize(w) for w in _WORD_RE.findall(text)]


def count_words(text: str) -> int:
    return len(_WORD_RE.findall(text))


def detect_language(tokens: list[str]) -> str:
    tr = sum(1 for t in tokens if t in _TR_STOPWORDS)
    en = sum(1 for t in tokens if t in _EN_STOPWORDS)
    return "en" if en > tr else "tr"


def strip_heading_number(line: str) -> str:
    return _HEADING_NUMBER_RE.sub("", line.strip())


def is_heading_line(line: str, max_words: int = 10) -> bool:
    stripped = line.strip()
    if not stripped or stripped[-1] in ".?!;,":
        return False
    return 0 < count_words(stripped) <= max_words


def body_text(text: str) -> str:
    """Baslik satirlarini at, PDF satir kirilimlarini birlestir -> akan govde metni."""
    lines = [ln for ln in text.split("\n") if ln.strip() and not is_heading_line(ln)]
    return " ".join(lines)


def split_sentences(text: str) -> list[str]:
    protected = _ABBREV_RE.sub(lambda m: m.group(0).replace(".", "<DOT>"), body_text(text))
    sentences = (s.replace("<DOT>", ".").strip() for s in _SENTENCE_SPLIT_RE.split(protected))
    return [s for s in sentences if count_words(s) >= 3]


def matches_stem(token: str, stems: tuple[str, ...]) -> bool:
    return token.startswith(stems)


def band_score(value: float, ideal: tuple[float, float], zero: tuple[float, float]) -> float:
    """ideal araliginda 100; zero sinirlarina dogru dogrusal olarak 0'a iner."""
    lo, hi = ideal
    zlo, zhi = zero
    if lo <= value <= hi:
        return 100.0
    if value < lo:
        return 0.0 if value <= zlo else 100.0 * (value - zlo) / (lo - zlo)
    return 0.0 if value >= zhi else 100.0 * (zhi - value) / (zhi - hi)


def clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def verdict_for(score: float) -> str:
    if score >= 80:
        return "accept"
    if score >= 65:
        return "minor_revision"
    if score >= 45:
        return "major_revision"
    return "reject"


@dataclass
class ModuleResult:
    """Her modulun ortak cikti sozlesmesi -> full_report['modules'][name]."""

    module: str
    agent: str
    agent_role: str
    score: float
    feedback: list[str] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    confidence: float = 1.0

    @property
    def agent_review(self) -> dict:
        """Coklu-ajan editor kurulu icin tek hakem gorusu (Ay 2: LLM hakemleri ayni semayi doldurur)."""
        return {
            "agent": self.agent,
            "role": self.agent_role,
            "verdict": verdict_for(self.score),
            "score": self.score,
            "summary": self.feedback[0] if self.feedback else "Belirgin bir sorun tespit edilmedi.",
            "key_issues": self.feedback[:3],
            "confidence": round(self.confidence, 2),
        }

    def to_dict(self) -> dict:
        return {
            "module": self.module,
            "score": self.score,
            "feedback": self.feedback,
            "metrics": self.metrics,
            "agent_review": self.agent_review,
        }
