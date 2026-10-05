"""
Analiz motoru v1 testleri - ag/Postgres/Redis gerektirmez.
Servis testi in-memory SQLite + tmp_path uzerinde calisir.
"""
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app import models  # noqa: F401  (iliskileri Base.metadata'ya kaydeder)
from app.database import Base, get_db
from app.main import app
from app.models.analysis import Analysis
from app.routers.deps import get_current_user
from app.services import analysis_service
from app.services.analysis.engine import MODULE_WEIGHTS, analyze_text
from app.services.analysis.modules import delivery, lexical, structure
from app.services.analysis.text_extractor import TextExtractionError, extract_text
from app.services.analysis.text_utils import (
    band_score,
    detect_language,
    split_sentences,
    tokenize,
    verdict_for,
)

BODY_EN = (
    "Previous research has examined how digital feedback shapes learning outcomes in higher education. "
    "However, the evidence remains inconsistent across contexts and the theoretical framework is rarely stated. "
    "This study therefore evaluates the effect of structured feedback on student performance. "
    "Moreover, we assess whether the relationship differs by prior achievement level. "
)
METHOD_EN = (
    "Participants were 214 undergraduate students recruited from two public universities. "
    "Data were collected through a validated questionnaire and course grade records. "
    "We estimated a hierarchical regression model to identify significant predictors of achievement. "
)
RESULTS_EN = (
    "The analysis indicates a significant positive effect of structured feedback on final grades. "
    "In contrast, the interaction with prior achievement was not significant in the full sample. "
)
CONCLUSION_EN = (
    "Structured feedback appears to improve performance regardless of prior achievement. "
    "Consequently, instructors should integrate feedback cycles into course design. "
)

IMRAD_EN = "\n".join(
    [
        "Structured Feedback and Student Achievement",
        "Abstract",
        BODY_EN,
        "1. Introduction",
        BODY_EN * 3,
        "2. Methodology",
        METHOD_EN * 3,
        "3. Results",
        RESULTS_EN * 3,
        "4. Conclusion",
        CONCLUSION_EN * 2,
        "References",
        "Smith, J. (2020). Feedback in higher education. Journal of Learning, 4(2), 1-20.",
    ]
)
UNSTRUCTURED_EN = (BODY_EN + METHOD_EN + RESULTS_EN) * 4

IMRAD_TR = "\n".join(
    [
        "Öz",
        "Bu araştırmada dijital geri bildirimin öğrenci başarısı üzerindeki etkisi incelenmiştir. " * 3,
        "Giriş",
        "Alanyazında geri bildirim ile başarı arasındaki ilişki tutarlı değildir. Bu nedenle kuramsal çerçeve ve "
        "araştırmanın kapsamı yeniden değerlendirilmiştir. " * 4,
        "Yöntem",
        "Araştırmanın örneklemi 214 lisans öğrencisinden oluşmaktadır. Veriler geçerlik ve güvenirlik "
        "çalışması yapılmış bir ölçek ile toplanmıştır. " * 4,
        "Bulgular",
        "Analiz sonuçları geri bildirimin başarı üzerinde anlamlı bir etkisi olduğunu göstermektedir. " * 4,
        "Sonuç",
        "Dolayısıyla geri bildirim döngüleri ders tasarımına dahil edilmelidir. " * 3,
        "Kaynakça",
    ]
)


def _minimal_pdf(text: str) -> bytes:
    """pypdf ile okunabilen tek sayfalik, metin katmanli PDF (harici kutuphane gerektirmez)."""
    lines = [text[i : i + 80] for i in range(0, len(text), 80)]
    ops = "BT /F1 10 Tf 40 800 Td 12 TL " + " ".join(
        f"({ln.replace('(', '').replace(')', '')}) Tj T*" for ln in lines
    ) + " ET"
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
        "/Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(ops)} >>\nstream\n{ops}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{obj}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{off:010d} 00000 n \n" for off in offsets).encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


# --- text_utils -------------------------------------------------------------

def test_tokenize_handles_turkish_dotted_i_and_apostrophe():
    assert tokenize("İstanbul'da Türkiye'nin İLK verisi") == ["istanbul'da", "türkiye'nin", "ilk", "verisi"]


def test_detect_language():
    assert detect_language(tokenize(BODY_EN)) == "en"
    assert detect_language(tokenize(IMRAD_TR)) == "tr"


def test_split_sentences_keeps_abbreviations_and_drops_headings():
    text = "Introduction\nSmith et al. reported gains in Fig. 2 of the study. Results were robust overall here."
    sentences = split_sentences(text)
    assert len(sentences) == 2
    assert sentences[0].startswith("Smith et al. reported")


def test_band_score_edges():
    assert band_score(20, ideal=(15, 25), zero=(5, 45)) == 100
    assert band_score(5, ideal=(15, 25), zero=(5, 45)) == 0
    assert band_score(35, ideal=(15, 25), zero=(5, 45)) == pytest.approx(50)


@pytest.mark.parametrize(
    ("score", "verdict"),
    [(90, "accept"), (70, "minor_revision"), (50, "major_revision"), (20, "reject")],
)
def test_verdict_thresholds(score, verdict):
    assert verdict_for(score) == verdict


# --- text_extractor ---------------------------------------------------------

def test_extract_txt(tmp_path):
    path = tmp_path / "paper.txt"
    path.write_text(IMRAD_EN, encoding="utf-8")
    result = extract_text(path)
    assert result.word_count > 300
    assert "Methodology" in result.text


def test_extract_txt_windows_turkish_encoding(tmp_path):
    path = tmp_path / "paper.txt"
    path.write_bytes(IMRAD_TR.encode("cp1254"))
    assert "Kaynakça" in extract_text(path).text


def test_extract_docx(tmp_path):
    import docx

    document = docx.Document()
    for line in IMRAD_EN.split("\n"):
        document.add_paragraph(line)
    path = tmp_path / "paper.docx"
    document.save(path)
    result = extract_text(path)
    assert "Introduction" in result.text
    assert result.word_count > 300


def test_extract_pdf(tmp_path):
    path = tmp_path / "paper.pdf"
    path.write_bytes(_minimal_pdf((BODY_EN + METHOD_EN) * 2))
    result = extract_text(path)
    assert "structured feedback" in result.text
    assert result.word_count >= 50


def test_extract_rejects_short_text_and_unknown_type(tmp_path):
    short = tmp_path / "short.txt"
    short.write_text("too short", encoding="utf-8")
    with pytest.raises(TextExtractionError):
        extract_text(short)
    with pytest.raises(TextExtractionError):
        extract_text(tmp_path / "paper.odt")


def test_extract_corrupt_pdf_raises_extraction_error(tmp_path):
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"not a pdf at all")
    with pytest.raises(TextExtractionError):
        extract_text(path)


# --- modules ----------------------------------------------------------------

def test_structure_detects_imrad_sections():
    result = structure.analyze(IMRAD_EN, "en")
    assert result.metrics["sections_found"] == [
        "abstract", "introduction", "methodology", "results", "conclusion", "references",
    ]
    assert result.score == 100
    assert result.agent_review["verdict"] == "accept"


def test_structure_turkish_headings():
    result = structure.analyze(IMRAD_TR, "tr")
    assert set(result.metrics["sections_found"]) >= {"abstract", "introduction", "methodology", "results", "conclusion"}


def test_structure_penalizes_missing_sections_and_low_confidence():
    result = structure.analyze(UNSTRUCTURED_EN, "en")
    assert result.score < 30
    assert result.agent_review["confidence"] <= 0.3
    assert result.feedback


def test_structure_law_profile_does_not_require_imrad():
    law_text = "\n".join(["Abstract", BODY_EN, "Introduction", BODY_EN, "Conclusion", CONCLUSION_EN, "References"])
    assert structure.analyze(law_text, "en", field="law").score == 100
    assert structure.analyze(law_text, "en", field="education").score < 100


def test_lexical_mattr_is_length_independent():
    tokens = tokenize(BODY_EN + METHOD_EN + RESULTS_EN)
    assert lexical.mattr(tokens * 5) == pytest.approx(lexical.mattr(tokens * 10), abs=0.02)
    assert lexical.mattr(["a"] * 200) == pytest.approx(0.01)


def test_lexical_flags_low_diversity_and_overuse():
    repetitive = tokenize("the data shows the data and the data is data. " * 60)
    result = lexical.analyze(repetitive, "en")
    assert result.score < 60
    assert "data" in result.metrics["overused_words"]


def test_delivery_penalizes_informal_long_sentences():
    academic_tokens = tokenize(IMRAD_EN)
    academic = delivery.analyze(split_sentences(IMRAD_EN), academic_tokens, "en")

    rambling = ("I think this is really great and I don't know why but my results " * 6 + "! ") * 20
    informal = delivery.analyze(split_sentences(rambling), tokenize(rambling), "en")

    assert academic.score > informal.score
    assert informal.metrics["informal_markers_per_1000"] > 0
    assert any("tekil" in f for f in informal.feedback)


# --- engine -----------------------------------------------------------------

def test_engine_report_contract():
    report = analyze_text(IMRAD_EN, field="education")
    assert set(report["modules"]) == set(MODULE_WEIGHTS)
    assert report["rejection_risk_score"] == pytest.approx(100 - report["overall_score"])
    assert report["language"] == "en"
    assert len(report["editorial_board"]["reviews"]) == 3
    for module in report["modules"].values():
        assert 0 <= module["score"] <= 100
        assert {"agent", "verdict", "summary", "key_issues", "confidence"} <= set(module["agent_review"])


def test_engine_structured_paper_beats_unstructured():
    assert analyze_text(IMRAD_EN)["overall_score"] > analyze_text(UNSTRUCTURED_EN)["overall_score"]


# --- service (status transitions) -------------------------------------------

@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(analysis_service, "UPLOAD_DIR", tmp_path)
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _make_analysis(db, tmp_path, file_name: str, content: bytes) -> Analysis:
    analysis = Analysis(id=uuid.uuid4(), user_id=uuid.uuid4(), file_name=file_name, selected_field="education", status="pending")
    db.add(analysis)
    db.commit()
    analysis_service.upload_path(analysis.id, file_name).write_bytes(content)
    return analysis


def test_process_analysis_completes_and_populates_fields(db, tmp_path):
    analysis = _make_analysis(db, tmp_path, "Paper.TXT", IMRAD_EN.encode("utf-8"))

    result = analysis_service.process_analysis(db, str(analysis.id))

    db.refresh(analysis)
    assert result["status"] == analysis.status == "completed"
    assert analysis.word_count > 300
    assert analysis.language == "en"
    assert analysis.title == "Structured Feedback and Student Achievement"
    assert analysis.score_structure == analysis.full_report["modules"]["structure"]["score"]
    assert analysis.score_lexical is not None and analysis.score_delivery is not None
    assert analysis.rejection_risk_score == pytest.approx(100 - analysis.full_report["overall_score"])
    assert set(analysis.revision_suggestions) == set(MODULE_WEIGHTS)
    assert analysis.processing_time_ms >= 0


def test_process_analysis_is_idempotent_for_completed(db, tmp_path):
    analysis = _make_analysis(db, tmp_path, "paper.txt", IMRAD_EN.encode("utf-8"))
    analysis_service.process_analysis(db, analysis.id)
    assert analysis_service.process_analysis(db, analysis.id)["status"] == "skipped_already_completed"


def test_process_analysis_marks_failed_on_extraction_error(db, tmp_path):
    analysis = _make_analysis(db, tmp_path, "scan.pdf", b"not a pdf")

    result = analysis_service.process_analysis(db, analysis.id)

    db.refresh(analysis)
    assert result["status"] == analysis.status == "failed"
    assert analysis.full_report["error"]["type"] == "text_extraction"
    assert analysis.score_structure is None


def test_process_analysis_marks_failed_on_unexpected_error(db, tmp_path, monkeypatch):
    analysis = _make_analysis(db, tmp_path, "paper.txt", IMRAD_EN.encode("utf-8"))

    def boom(*_args, **_kwargs):
        raise RuntimeError("engine crashed")

    monkeypatch.setattr(analysis_service, "analyze_text", boom)
    result = analysis_service.process_analysis(db, analysis.id)

    db.refresh(analysis)
    assert analysis.status == "failed"
    assert result["error"]["type"] == "internal"
    assert "engine crashed" not in analysis.full_report["error"]["message"]


def test_process_analysis_not_found(db):
    assert analysis_service.process_analysis(db, uuid.uuid4())["status"] == "not_found"


# --- API: GET /api/analyses/{id}/report --------------------------------------

@pytest.fixture
def api(tmp_path, monkeypatch):
    """Tek baglantili SQLite (StaticPool) + auth override; TestClient thread'i ayni DB'yi gorur."""
    monkeypatch.setattr(analysis_service, "UPLOAD_DIR", tmp_path)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    user = type("FakeUser", (), {"id": uuid.uuid4()})()

    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: user
    yield TestClient(app), session, user
    app.dependency_overrides.clear()
    session.close()


def test_report_endpoint_returns_completed_report(api, tmp_path):
    client, session, user = api
    analysis = _make_analysis(session, tmp_path, "paper.txt", IMRAD_EN.encode("utf-8"))
    analysis.user_id = user.id
    session.commit()
    analysis_service.process_analysis(session, analysis.id)

    resp = client.get(f"/api/analyses/{analysis.id}/report")

    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {
        "id", "status", "rejection_risk_score", "word_count", "language",
        "score_structure", "score_lexical", "score_delivery", "full_report", "revision_suggestions",
    }
    assert body["id"] == str(analysis.id)
    assert body["status"] == "completed"
    assert body["language"] == "en"
    assert body["word_count"] > 300
    assert body["score_structure"] == body["full_report"]["modules"]["structure"]["score"]
    assert set(body["revision_suggestions"]) == set(MODULE_WEIGHTS)


def test_report_endpoint_pending_returns_null_scores(api, tmp_path):
    client, session, user = api
    analysis = _make_analysis(session, tmp_path, "paper.txt", IMRAD_EN.encode("utf-8"))
    analysis.user_id = user.id
    session.commit()

    body = client.get(f"/api/analyses/{analysis.id}/report").json()

    assert body["status"] == "pending"
    assert body["rejection_risk_score"] is None
    assert body["full_report"] is None


def test_report_endpoint_404_for_missing_or_foreign_analysis(api, tmp_path):
    client, session, _user = api
    foreign = _make_analysis(session, tmp_path, "paper.txt", IMRAD_EN.encode("utf-8"))  # baska user_id

    assert client.get(f"/api/analyses/{uuid.uuid4()}/report").status_code == 404
    assert client.get(f"/api/analyses/{foreign.id}/report").status_code == 404
