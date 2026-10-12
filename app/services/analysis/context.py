"""
Analiz baglami: makale BIR KEZ ayristirilir, 11 modul ayni nesneyi okur.

Onceden her modul extract_sections()/detect_sections()'i kendisi cagiriyordu
(makale basina ~10 tekrar). Context bunu tek gecise indirir; moduller metni
yeniden ayristirmaz, yalnizca buradaki alanlari kullanir.
"""
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from types import MappingProxyType

from app.services.analysis.modules.structure import detect_sections, extract_sections
from app.services.analysis.text_utils import count_words, detect_language, split_sentences, tokenize


@dataclass(frozen=True)
class Context:
    text: str
    language: str
    tokens: list[str]
    sentences: list[str]
    section_index: Mapping[str, int]  # bolum -> baslik satir indeksi
    sections: Mapping[str, str]  # bolum -> govde metni
    body: str  # kaynakca basligindan onceki metin (baslik yoksa tum metin)
    word_count: int  # tum metin (kaynakca dahil)
    body_word_count: int  # kaynakca haric
    as_of: date  # guncellik hesaplari icin referans tarih (testte sabitlenir)


def build_context(text: str, language: str | None = None, as_of: date | None = None) -> Context:
    tokens = tokenize(text)
    section_index = detect_sections(text)
    references_idx = section_index.get("references")
    body = "\n".join(text.split("\n")[:references_idx]) if references_idx is not None else text
    return Context(
        text=text,
        language=language or detect_language(tokens),
        tokens=tokens,
        sentences=split_sentences(text),
        section_index=MappingProxyType(section_index),
        sections=MappingProxyType(extract_sections(text, found=section_index)),
        body=body,
        word_count=count_words(text),
        body_word_count=count_words(body),
        as_of=as_of or date.today(),
    )
