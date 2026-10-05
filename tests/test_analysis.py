"""
Analiz motoru v1 testleri - ag/Postgres/Redis gerektirmez.
Servis testi in-memory SQLite + tmp_path uzerinde calisir.
"""
import uuid
from datetime import date

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
from app.services.analysis.engine import (
    EVALUATED_MODULES,
    MODULE_WEIGHTS,
    NOT_YET_EVALUATED,
    analyze_text,
    effective_weights,
)
from app.services.analysis.modules import (
    abstract,
    conclusions,
    delivery,
    findings,
    lexical,
    literature,
    methodology,
    originality,
    references,
    structure,
    title,
)
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
    assert set(report["modules"]) == set(EVALUATED_MODULES)
    assert report["rejection_risk_score"] == pytest.approx(100 - report["overall_score"])
    assert report["language"] == "en"
    assert len(report["editorial_board"]["reviews"]) == len(EVALUATED_MODULES)
    for module in report["modules"].values():
        assert 0 <= module["score"] <= 100
        assert {"agent", "verdict", "summary", "key_issues", "confidence"} <= set(module["agent_review"])


def test_engine_structured_paper_beats_unstructured():
    assert analyze_text(IMRAD_EN)["overall_score"] > analyze_text(UNSTRUCTURED_EN)["overall_score"]


def test_module_weights_cover_all_11_modules_and_sum_to_one():
    assert len(MODULE_WEIGHTS) == 11
    assert sum(MODULE_WEIGHTS.values()) == pytest.approx(1.0)
    assert set(EVALUATED_MODULES) | set(NOT_YET_EVALUATED) == set(MODULE_WEIGHTS)
    assert NOT_YET_EVALUATED == ()
    assert len(EVALUATED_MODULES) == 11
    assert sum(effective_weights().values()) == pytest.approx(1.0)


def test_engine_overall_is_weighted_mean_of_module_scores():
    report = analyze_text(IMRAD_EN, field="education")
    weights = effective_weights()
    expected = sum(report["modules"][n]["score"] * weights[n] for n in EVALUATED_MODULES)
    assert report["overall_score"] == pytest.approx(expected, abs=0.05)


# --- modules: title / abstract / methodology / references -------------------

RICH_ABSTRACT = (
    "Abstract\n"
    "The aim of this study is to evaluate the effect of structured feedback on student achievement. "
    "Data were collected from 214 participants through a validated survey and analysed with regression. "
    "Results show a significant positive effect of feedback on final grades (β = 0.32, p < .01). "
    "We conclude that instructors should integrate feedback cycles, which has clear implications for course design. "
    * 4
    + "\nKeywords: feedback, achievement, higher education\n"
)
GOOD_REFERENCES = "\n".join(
    f"Author{chr(65 + i % 26)}, B. ({2016 + i % 8}). Feedback study {i}. Journal of Learning, 4(2), 1-20. "
    f"https://doi.org/10.1000/jl.{i}"
    for i in range(30)
)
CITED_BODY = " ".join(f"Prior work supports this (Author{chr(65 + i % 26)}, {2016 + i % 8})." for i in range(30))


def test_title_scores_and_flags_form_issues():
    good = title.analyze(IMRAD_EN, "en")
    assert good.metrics["title"] == "Structured Feedback and Student Achievement"
    assert good.metrics["concept_overlap"] == 1.0

    bad_text = IMRAD_EN.replace(
        "Structured Feedback and Student Achievement", "A NOVEL STUDY OF SOME ASPECTS OF LEARNING."
    )
    bad = title.analyze(bad_text, "en")
    assert bad.score < good.score
    assert bad.metrics["ends_with_period"] and bad.metrics["all_caps"]
    assert bad.metrics["vague_phrase"] and bad.metrics["hype_phrase"]


def test_title_missing_returns_zero_with_low_confidence():
    result = title.analyze(IMRAD_TR, "tr")
    assert result.score == 0 and result.confidence <= 0.3


def test_abstract_detects_moves_keywords_and_numbers():
    result = abstract.analyze(RICH_ABSTRACT + "Introduction\n" + BODY_EN, "en")
    assert all(result.metrics["moves"].values())
    assert result.metrics["has_keywords"] and result.metrics["has_quantitative_result"]
    assert 150 <= result.metrics["word_count"] <= 300
    assert result.score >= 90

    thin = abstract.analyze(IMRAD_EN, "en")
    assert thin.score < result.score
    assert any("eksik hamle" in f for f in thin.feedback)


def test_abstract_law_profile_does_not_require_method_or_numbers():
    law_abstract = (
        "Abstract\nThis article examines the constitutional limits of emergency decrees. "
        "It argues that judicial review must remain available, and therefore proposes a narrower reading. " * 8
    )
    result = abstract.analyze(law_abstract, "en", field="law")
    assert set(result.metrics["moves"]) == {"purpose", "argument", "conclusion"}
    assert not any("nicel" in f for f in result.feedback)


def test_abstract_missing():
    assert abstract.analyze(UNSTRUCTURED_EN, "en").score == 0


def test_methodology_detects_sample_size_and_penalizes_missing_section():
    structured = methodology.analyze(IMRAD_EN, "en", field="education")
    unstructured = methodology.analyze(UNSTRUCTURED_EN, "en", field="education")
    assert structured.metrics["sample_size"] == 214
    assert structured.metrics["has_section"] and not unstructured.metrics["has_section"]
    assert structured.score > unstructured.score
    assert unstructured.confidence < structured.confidence


def test_methodology_health_profile_requires_ethics():
    default = methodology.analyze(IMRAD_EN, "en", field="education")
    health = methodology.analyze(IMRAD_EN, "en", field="health")
    assert health.score < default.score
    assert any("etik kurul" in f.lower() for f in health.feedback)

    with_ethics = IMRAD_EN.replace(
        "Participants were 214", "The study was approved by the ethics committee and informed consent was obtained. Participants were 214"
    )
    assert methodology.analyze(with_ethics, "en", field="health").score > health.score


def test_methodology_law_profile_searches_whole_text_for_legal_method():
    law_text = "Introduction\n" + (
        "This article adopts a doctrinal and comparative approach, analysing statute law and court decisions. " * 5
    )
    result = methodology.analyze(law_text, "en", field="law")
    assert result.metrics["field_profile"] == "law"
    assert result.metrics["elements_found"] == {"approach": True, "sources": True}
    assert result.score == 100


def test_references_scores_well_formed_cited_bibliography():
    text = "Introduction\n" + CITED_BODY + "\nReferences\n" + GOOD_REFERENCES
    result = references.analyze(text, "en", today=date(2026, 10, 5))
    assert result.metrics["entry_count"] == 30
    assert result.metrics["in_text_citations"] == 30
    assert result.metrics["style"] == "author_year" and result.metrics["style_consistency"] == 1.0
    assert result.metrics["doi_share"] == 1.0
    assert result.score >= 90


def test_references_flags_old_uncited_mixed_style_entries():
    entries = "\n".join(
        [f"[{i}] Author{i}, B. Old study. Journal, 1(1), 1-9, {1990 + i}." for i in range(1, 6)]
        + [f"Writer{i}, C. ({1995 + i}). Another study. Journal, 2(1), 1-9." for i in range(5)]
    )
    result = references.analyze("Introduction\nNo citations here.\nReferences\n" + entries, "en", today=date(2026, 10, 5))
    assert result.metrics["entry_count"] == 10
    assert result.metrics["recent_share"] == 0
    assert result.metrics["style_consistency"] == 0.5
    assert result.score < 40
    assert any("Metin ici atif" in f for f in result.feedback)


def test_references_heading_without_entries():
    result = references.analyze(IMRAD_TR, "tr")
    assert result.score == 0
    assert result.feedback[0] == "Kaynakca basligi var ama girdi bulunamadi."


def test_references_law_ignores_recency_and_doi():
    old_refs = "\n".join(f"Jurist{chr(65 + i % 26)}, A. ({1960 + i}). Treatise on law {i}. Ankara." for i in range(40))
    body = " ".join(f"(Jurist{chr(65 + i % 26)}, {1960 + i})" for i in range(40))
    text = "Introduction\n" + body + "\nReferences\n" + old_refs
    law = references.analyze(text, "tr", field="law", today=date(2026, 10, 5))
    default = references.analyze(text, "tr", field="education", today=date(2026, 10, 5))
    assert law.score > default.score
    assert not any("DOI" in f for f in law.feedback)


# --- modules: literature / originality / findings / conclusions -------------

LIT_REVIEW_EN = (
    "Literature Review\n"
    + " ".join(
        f"Previous studies reported mixed effects of feedback (Author{chr(65 + i)}, {2015 + i}; Writer{chr(65 + i)}, {2018 + i}). "
        "In contrast, recent research suggests that timing matters more than volume. "
        for i in range(8)
    )
)
GAP_INTRO_EN = (
    "Introduction\n"
    "Feedback has been widely studied in schools, yet little is known about structured feedback in large lectures. "
    "To our knowledge, no study has examined weekly feedback cycles across two universities. "
    "This study contributes to the literature by testing a scalable feedback design with a new cohort.\n"
)
RICH_RESULTS_EN = (
    "Results\n"
    "Table 1 reports descriptive statistics: mean score was 72.4 (SD = 8.1) in the treatment group and 65.2 (SD = 9.3) "
    "in the control group. The difference was significant, t(212) = 4.31, p < .001, with a medium effect size "
    "(Cohen's d = 0.59, 95% CI [0.31, 0.86]). Regression results in Figure 2 show β = 0.32 for feedback frequency, "
    "explaining 18% of variance in final grades across 214 students.\n"
)
GOOD_CONCLUSION_EN = (
    "Conclusion\n"
    "Structured feedback improved final grades and the effect was significant across both universities. "
    "These results have practical implications: instructors should schedule weekly feedback cycles. "
    "A limitation of this study is the short observation period. "
    "Future research should examine long-term retention and other disciplines.\n"
)


def test_literature_rewards_cited_synthesised_review():
    text = GAP_INTRO_EN + LIT_REVIEW_EN + "\n" + METHOD_EN * 4 + "\n" + RICH_RESULTS_EN
    result = literature.analyze(text, "en", field="education")
    assert result.metrics["scope"] == "literature"
    assert result.metrics["multi_source_citations"] == 8
    assert result.metrics["synthesis_phrase_groups"] >= 2
    assert result.score > literature.analyze(IMRAD_EN, "en", field="education").score


def test_literature_falls_back_to_introduction_and_flags_missing_citations():
    result = literature.analyze(IMRAD_EN, "en", field="education")
    assert result.metrics["scope"] == "introduction"
    assert result.metrics["in_text_citations"] == 0
    assert any("atif yok" in f for f in result.feedback)
    assert literature.analyze(UNSTRUCTURED_EN, "en").score == 0


def test_literature_law_scans_body_without_ratio():
    result = literature.analyze(LIT_REVIEW_EN + "\nConclusion\n" + CONCLUSION_EN, "en", field="law")
    assert result.metrics["scope"] == "body"
    assert result.metrics["section_ratio"] is None


def test_originality_repetition_ratio():
    assert originality.repetition_ratio(tokenize("a b c d e f g h i j k l")) == 0
    assert originality.repetition_ratio(tokenize("a b c d e f " * 10)) == pytest.approx(1.0)


def test_originality_rewards_gap_contribution_and_low_repetition():
    text = "Abstract\n" + RICH_ABSTRACT + GAP_INTRO_EN + LIT_REVIEW_EN + "\n" + RICH_RESULTS_EN
    strong = originality.analyze(text, "en")
    weak = originality.analyze(IMRAD_EN, "en")
    assert strong.metrics["gap_indicator_groups"] >= 2
    assert strong.metrics["has_contribution_statement"]
    assert weak.metrics["repetition_ratio"] > 0.5  # fixture tekrarli bloklardan olusuyor
    assert strong.score > weak.score
    assert strong.confidence == 0.5


def test_originality_law_accepts_unsettled_case_law_as_gap():
    text = "Introduction\nThe question remains controversial and the case law is unsettled in Turkish doctrine.\n"
    assert originality.analyze(text, "en", field="law").metrics["gap_indicator_groups"] == 1
    assert originality.analyze(text, "en", field="education").metrics["gap_indicator_groups"] == 0


def test_findings_quantitative_profile_rewards_statistics():
    text = "Introduction\n" + BODY_EN * 2 + "\nMethodology\n" + METHOD_EN * 2 + "\n" + RICH_RESULTS_EN
    rich = findings.analyze(text, "en", field="health")
    assert rich.metrics["profile"] == "quantitative"
    assert rich.metrics["stat_marker_groups"] >= 4
    assert rich.metrics["table_figure_refs"]
    assert rich.score > findings.analyze(IMRAD_EN, "en", field="health").score


def test_findings_qualitative_profile_uses_quotes_and_themes():
    quote = '"I finally understood what the instructor expected from my weekly assignments"'
    results = "Results\n" + " ".join(
        f"Theme {i}: participants valued timely comments. P{i} said {quote}." for i in range(1, 6)
    )
    text = "Methodology\nWe conducted semi-structured interviews and a thematic analysis.\n" + results
    result = findings.analyze(text, "en", field="education")
    assert result.metrics["profile"] == "qualitative"
    assert result.metrics["quotes"] == 5 and result.metrics["participant_codes"] == 5
    assert result.score >= 70


def test_findings_law_profile_counts_legal_references():
    text = "Introduction\n" + " ".join(
        f"Under Article {i} of the Code, Yargıtay held in E. 2019/{i} that the clause is void." for i in range(1, 7)
    )
    result = findings.analyze(text, "en", field="law")
    assert result.metrics["profile"] == "law"
    assert result.metrics["legal_references"] >= 6
    assert "section_ratio" not in result.metrics


def test_findings_missing_section_is_halved():
    result = findings.analyze(UNSTRUCTURED_EN, "en")
    assert result.metrics["scope"] is None
    assert result.confidence == 0.4


def test_conclusions_rewards_limitations_future_work_and_no_new_citations():
    base = "Introduction\n" + BODY_EN * 3 + "\n" + RICH_RESULTS_EN
    good = conclusions.analyze(base + GOOD_CONCLUSION_EN, "en")
    assert good.metrics["has_limitations"] and good.metrics["has_future_research"] and good.metrics["has_implications"]
    assert good.metrics["new_citations"] == 0

    cited = conclusions.analyze(
        base + GOOD_CONCLUSION_EN.replace("disciplines.", "disciplines (Smith, 2021; Lee, 2022)."), "en"
    )
    assert cited.metrics["new_citations"] == 1
    assert cited.score < good.score
    assert "yeni kaynak" in cited.feedback[0]


def test_conclusions_detects_turkish_obligation_mood_as_implication():
    result = conclusions.analyze(IMRAD_TR, "tr")
    assert result.metrics["has_implications"]  # "dahil edilmelidir"


def test_conclusions_law_profile_and_missing_section():
    text = "Introduction\n" + BODY_EN + "\nConclusion\nThe legislature should amend the statute.\n"
    law = conclusions.analyze(text, "en", field="law")
    assert law.metrics["profile"] == "law"
    assert not any("sinirliliklari" in f for f in law.feedback)
    assert conclusions.analyze(UNSTRUCTURED_EN, "en").score == 0


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
    assert set(analysis.revision_suggestions) == set(EVALUATED_MODULES)
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
        "score_title", "score_abstract", "score_structure", "score_literature", "score_originality",
        "score_methodology", "score_findings", "score_conclusions", "score_references",
        "score_lexical", "score_delivery", "full_report", "revision_suggestions",
    }
    assert body["id"] == str(analysis.id)
    assert body["status"] == "completed"
    assert body["language"] == "en"
    assert body["word_count"] > 300
    assert body["score_structure"] == body["full_report"]["modules"]["structure"]["score"]
    assert set(body["revision_suggestions"]) == set(EVALUATED_MODULES)


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


# --- API: GET /api/analyses/{id}/pdf -----------------------------------------

def _owned_analysis(session, tmp_path, user, status_: str | None = None) -> Analysis:
    analysis = _make_analysis(session, tmp_path, "paper.txt", IMRAD_EN.encode("utf-8"))
    analysis.user_id = user.id
    if status_:
        analysis.status = status_
    session.commit()
    return analysis


def test_pdf_endpoint_returns_pdf_for_completed_analysis(api, tmp_path):
    import io

    from pypdf import PdfReader

    client, session, user = api
    analysis = _owned_analysis(session, tmp_path, user)
    analysis_service.process_analysis(session, analysis.id)
    analysis.title = "Dijital Geri Bildirim ve Öğrenci Başarısı: Çığır Açan Şişli Örneği"
    session.commit()

    resp = client.get(f"/api/analyses/{analysis.id}/pdf")

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.headers["content-disposition"] == f'attachment; filename="acaturk_analysis_{analysis.id}.pdf"'
    assert resp.content.startswith(b"%PDF-")
    text = "".join(page.extract_text() for page in PdfReader(io.BytesIO(resp.content)).pages)
    assert "Öğrenci Başarısı: Çığır Açan Şişli" in text
    assert "Yönetici Özeti" in text and "Revizyon Önerileri" in text


@pytest.mark.parametrize("state", ["pending", "processing"])
def test_pdf_endpoint_409_when_not_ready(api, tmp_path, state):
    client, session, user = api
    analysis = _owned_analysis(session, tmp_path, user, state)

    assert client.get(f"/api/analyses/{analysis.id}/pdf").status_code == 409


def test_pdf_endpoint_422_when_failed(api, tmp_path):
    client, session, user = api
    analysis = _owned_analysis(session, tmp_path, user, "failed")

    assert client.get(f"/api/analyses/{analysis.id}/pdf").status_code == 422


def test_pdf_endpoint_404_for_missing_or_foreign_analysis(api, tmp_path):
    client, session, _user = api
    foreign = _make_analysis(session, tmp_path, "paper.txt", IMRAD_EN.encode("utf-8"))
    foreign.status = "completed"  # tamamlanmis olsa bile sahibi degilse 404 (403 degil)
    session.commit()

    assert client.get(f"/api/analyses/{uuid.uuid4()}/pdf").status_code == 404
    assert client.get(f"/api/analyses/{foreign.id}/pdf").status_code == 404


def test_pdf_html_escapes_user_content_and_blocks_external_fetch():
    from app.services import pdf_service

    analysis = Analysis(
        id=uuid.uuid4(), status="completed", language="en", word_count=1,
        title='<img src="file:///etc/passwd">', full_report={}, revision_suggestions={},
    )
    html = pdf_service.render_html(analysis)

    assert '<img src="file:///etc/passwd">' not in html
    assert "&lt;img" in html
    with pytest.raises(ValueError):
        pdf_service._deny_url_fetcher("file:///etc/passwd")
