"""
OpenAlex REST client.

akademik_kutuphane_projesi.md Bolum 4.1 ve 7.2'ye dayanir. `pyalex` paketine
bagimlilik eklemek yerine dogrudan `requests` ile cursor-based pagination
kullanilir (tek bagimlilik, davranisi acik).

Guvenli hiz siniri (Bolum 8.3): polite pool + email ile 10 req/sn onerilir;
bu client varsayilan olarak istekler arasi kucuk bir bekleme uygular.
"""
import time
from collections.abc import Iterator

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

BASE_URL = "https://api.openalex.org/works"
DEFAULT_PER_PAGE = 200
MIN_REQUEST_INTERVAL_SECONDS = 0.15  # ~6-7 req/sn, polite pool siniri altinda kalir


class OpenAlexError(Exception):
    pass


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(min=2, max=30),
    retry=retry_if_exception_type((requests.RequestException, OpenAlexError)),
)
def _get_page(params: dict) -> dict:
    resp = requests.get(BASE_URL, params=params, timeout=30)
    if resp.status_code >= 500:
        raise OpenAlexError(f"OpenAlex 5xx: {resp.status_code}")
    resp.raise_for_status()
    return resp.json()


def iter_works(
    concept_ids: list[str],
    year_from: int,
    year_to: int,
    email: str | None = None,
    per_page: int = DEFAULT_PER_PAGE,
    max_results: int | None = None,
) -> Iterator[dict]:
    """
    Verilen concept ID'lerden herhangi birine ait, year_from-year_to araligindaki
    'article' tipi eserleri sayfa sayfa (cursor pagination) dondurur.

    OpenAlex concept filtresi OR mantigiyla pipe (|) ile birlestirilir:
    concepts.id:C1|C2 -> C1 VEYA C2.
    """
    concept_filter = "|".join(concept_ids)
    params = {
        "filter": f"concepts.id:{concept_filter},publication_year:{year_from}-{year_to},type:article",
        "per-page": per_page,
        "cursor": "*",
    }
    if email:
        params["mailto"] = email

    returned = 0
    while True:
        data = _get_page(params)
        results = data.get("results", [])
        for work in results:
            yield work
            returned += 1
            if max_results is not None and returned >= max_results:
                return

        next_cursor = data.get("meta", {}).get("next_cursor")
        if not next_cursor or not results:
            return
        params["cursor"] = next_cursor
        time.sleep(MIN_REQUEST_INTERVAL_SECONDS)


def extract_fields(work: dict) -> dict:
    """OpenAlex ham JSON'undan CorpusWork alanlarina duz bir sozluk cikarir."""
    primary_location = work.get("primary_location") or {}
    source = primary_location.get("source") or {}
    oa = work.get("open_access") or {}

    authors = []
    for pos, authorship in enumerate(work.get("authorships", [])):
        author = authorship.get("author") or {}
        authors.append(
            {
                "openalex_id": author.get("id"),
                "full_name": author.get("display_name"),
                "orcid": author.get("orcid"),
                "position": pos,
            }
        )

    return {
        "openalex_id": work.get("id"),
        "doi": (work.get("doi") or "").replace("https://doi.org/", "") or None,
        "title": work.get("title"),
        "abstract": _reconstruct_abstract(work.get("abstract_inverted_index")),
        "publication_year": work.get("publication_year"),
        "journal_name": source.get("display_name"),
        "journal_issn": (source.get("issn_l") or (source.get("issn") or [None])[0]),
        "cited_by_count": work.get("cited_by_count"),
        "is_oa": bool(oa.get("is_oa")),
        "oa_url": oa.get("oa_url"),
        "authors": authors,
        "raw_json": work,
    }


def _reconstruct_abstract(inverted_index: dict | None) -> str | None:
    """OpenAlex ozet'i 'inverted index' (kelime -> pozisyon listesi) olarak doner; duz metne cevirir."""
    if not inverted_index:
        return None
    position_word: dict[int, str] = {}
    for word, positions in inverted_index.items():
        for pos in positions:
            position_word[pos] = word
    if not position_word:
        return None
    return " ".join(position_word[i] for i in sorted(position_word))
