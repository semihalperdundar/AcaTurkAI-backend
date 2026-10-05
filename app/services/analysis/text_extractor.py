"""
Yuklenen dosyadan (PDF/DOCX/TXT) duz metin cikarma.

Analiz modulleri yalnizca duz metin gorur; dosya formati bilgisi burada kalir.
Taranmis (goruntu) PDF'lerde metin katmani yoktur -> TextExtractionError
(OCR Ay 3+ kapsami).
"""
import re
from dataclasses import dataclass
from pathlib import Path

from app.services.analysis.text_utils import count_words

MIN_WORDS = 50  # bunun altindaki metinler anlamli analiz icin yetersiz


class TextExtractionError(Exception):
    pass


@dataclass(frozen=True)
class ExtractedText:
    text: str
    word_count: int


def _read_txt(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "cp1254", "latin-1"):  # cp1254 = Windows Turkce
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise TextExtractionError("TXT dosyasi cozulemedi (desteklenen kodlamalar: UTF-8, Windows-1254).")


def _read_pdf(path: Path) -> str:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted:
            raise TextExtractionError("Sifreli PDF dosyalari desteklenmiyor.")
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except PdfReadError as exc:
        raise TextExtractionError(f"PDF okunamadi: {exc}") from exc


def _read_docx(path: Path) -> str:
    import docx
    from docx.opc.exceptions import PackageNotFoundError

    try:
        document = docx.Document(str(path))
    except (PackageNotFoundError, KeyError, ValueError) as exc:
        raise TextExtractionError(f"DOCX okunamadi: {exc}") from exc
    # Tablo icerigi analiz disi; yalnizca govde paragraflari (baslik satirlari dahil).
    return "\n".join(p.text for p in document.paragraphs)


_READERS = {".txt": _read_txt, ".pdf": _read_pdf, ".docx": _read_docx}


def _clean(text: str) -> str:
    text = text.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)  # PDF satir sonu tirelemesi
    text = re.sub(r"[ \t ]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_text(path: Path) -> ExtractedText:
    suffix = path.suffix.lower()
    reader = _READERS.get(suffix)
    if reader is None:
        raise TextExtractionError(f"Desteklenmeyen dosya turu: {suffix or 'bilinmiyor'}.")
    if not path.is_file():
        raise TextExtractionError(f"Dosya bulunamadi: {path.name}")

    text = _clean(reader(path))
    word_count = count_words(text)
    if word_count < MIN_WORDS:
        raise TextExtractionError(
            f"Metin cok kisa veya cikarilamadi ({word_count} kelime). "
            "Taranmis PDF ise metin katmani iceren bir surum yukleyin."
        )
    return ExtractedText(text=text, word_count=word_count)
