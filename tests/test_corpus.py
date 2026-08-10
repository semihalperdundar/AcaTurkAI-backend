"""
Corpus modulu icin ag erisimi gerektirmeyen birim testleri.
OpenAlex/Unpaywall/Scimago'ya gercek istek atmaz - sadece saf donusum
fonksiyonlarini (parsing, lisans/alan eslemesi) dogrular.
"""
from app.services.corpus.areas import guess_area_from_scimago_category, VALID_AREA_CODES
from app.services.corpus.openalex_client import extract_fields, _reconstruct_abstract
from app.services.corpus.unpaywall_client import is_commercial_use_allowed


def test_valid_area_codes_match_user_primary_field_convention():
    # app/models/user.py docstring'indeki 6 alanla birebir ayni olmali.
    assert set(VALID_AREA_CODES) == {
        "education", "social_sciences", "engineering", "health", "law", "business",
    }


def test_guess_area_from_scimago_category():
    assert guess_area_from_scimago_category("Education") == "education"
    assert guess_area_from_scimago_category("Economics and Econometrics") == "business"
    assert guess_area_from_scimago_category(None) is None
    assert guess_area_from_scimago_category("Something Unrelated Xyz") is None


def test_is_commercial_use_allowed():
    assert is_commercial_use_allowed("cc-by") is True
    assert is_commercial_use_allowed("CC0") is True
    assert is_commercial_use_allowed(None) is False
    assert is_commercial_use_allowed("publisher-specific-oa") is False


def test_reconstruct_abstract_from_inverted_index():
    inverted = {"Merhaba": [0], "dunya": [1]}
    assert _reconstruct_abstract(inverted) == "Merhaba dunya"
    assert _reconstruct_abstract(None) is None


def test_extract_fields_from_openalex_work():
    work = {
        "id": "https://openalex.org/W123",
        "doi": "https://doi.org/10.1000/xyz",
        "title": "Ornek Makale",
        "abstract_inverted_index": {"test": [0]},
        "publication_year": 2022,
        "primary_location": {"source": {"display_name": "Ornek Dergi", "issn_l": "1234-5678", "issn": ["1234-5678"]}},
        "open_access": {"is_oa": True, "oa_url": "https://example.com/pdf"},
        "cited_by_count": 5,
        "authorships": [{"author": {"id": "A1", "display_name": "Yazar Bir", "orcid": None}}],
    }
    fields = extract_fields(work)
    assert fields["doi"] == "10.1000/xyz"
    assert fields["journal_issn"] == "1234-5678"
    assert fields["is_oa"] is True
    assert fields["abstract"] == "test"
    assert fields["authors"][0]["full_name"] == "Yazar Bir"
