"""
Zengin yol (LLM icgoru) altyapisi: sozlesme, grounding, onbellek, mock pipeline.
Dis API cagrisi yok; MockInsightClient ve sahte istemcilerle calisir.
"""
import dataclasses
import io
import json
import uuid
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models  # noqa: F401  (iliskileri Base.metadata'ya kaydeder)
from app.core.celery_app import celery_app
from app.database import Base
from app.models.analysis import Analysis
from app.models.insight_cache import InsightCache
from app.services import analysis_service
from app.services.analysis.context import build_context
from app.services.analysis.engine import EVALUATED_MODULES
from app.services.analysis.modules.structure import SECTION_PATTERNS
from app.services.analysis.profiles import BASE, CLAIM_EVIDENCE, LAW, PROFILES
from app.services.insights import cache as cache_module
from app.services.insights.cache import insight_cache_key
from app.config import get_settings
from app.core import celery_app as celery_module
from app.services import pdf_service
from app.services.insights.client import AnthropicInsightClient, MockInsightClient, get_insight_client
from app.services.insights.prompts import PROMPTS, get_prompt
from app.services.insights.grounding import validate_grounding
from app.services.insights.schema import Insight, InsightBatch
from app.services.insights.service import generate_insights
from tests.test_analysis import IMRAD_EN, IMRAD_TR

RESULTS_SENTENCE = "The analysis indicates a significant positive effect of structured feedback on final grades."


def make_insight(quote: str, module: str = "findings", **overrides) -> Insight:
    fields = {
        "module": module,
        "severity": "major",
        "issue": "Claim exceeds evidence.",
        "evidence_quote": quote,
        "why_reviewers_care": "Reviewers reject causal claims from correlational data.",
        "concrete_fix": "Rephrase as an association.",
        "example_rewrite": None,
    }
    return Insight(**{**fields, **overrides})


# --- contract ----------------------------------------------------------------

def test_insight_rejects_unknown_severity_and_extra_fields():
    with pytest.raises(ValidationError):
        make_insight(RESULTS_SENTENCE, severity="critical")
    with pytest.raises(ValidationError):
        make_insight(RESULTS_SENTENCE, confidence=0.9)
    with pytest.raises(ValidationError):
        make_insight("   ")


# --- grounding ---------------------------------------------------------------

def test_grounding_ignores_whitespace_and_case_only():
    ctx = build_context(IMRAD_EN)
    variant = "THE ANALYSIS indicates a\n   significant positive    effect of structured feedback"
    result = validate_grounding([make_insight(variant)], ctx)
    assert len(result.accepted) == 1 and not result.rejected


def test_grounding_handles_turkish_case_folding():
    ctx = build_context(IMRAD_TR)
    quote = "BU ARAŞTIRMADA DİJİTAL GERİ BİLDİRİMİN ÖĞRENCİ BAŞARISI"
    assert len(validate_grounding([make_insight(quote)], ctx).accepted) == 1


def test_grounding_drops_fabricated_short_and_out_of_pack_quotes():
    ctx = build_context(IMRAD_EN)
    fabricated = make_insight("The effect was causal and replicated in three countries.")
    paraphrased = make_insight("The analysis shows structured feedback significantly improves grades.")
    too_short = make_insight("the analysis")
    wrong_module = make_insight(RESULTS_SENTENCE, module="title")
    good = make_insight(RESULTS_SENTENCE)

    result = validate_grounding([fabricated, paraphrased, too_short, wrong_module, good], ctx, CLAIM_EVIDENCE.modules)

    assert result.accepted == [good]
    assert [reason for _, reason in result.rejected] == [
        "quote_not_in_text", "quote_not_in_text", "quote_too_short", "module_not_in_pack",
    ]


# --- cache key -----------------------------------------------------------------

def test_cache_key_is_deterministic_and_sensitive_to_every_component(monkeypatch):
    ctx = build_context(IMRAD_EN)
    key = insight_cache_key(ctx, BASE, CLAIM_EVIDENCE)

    assert key == insight_cache_key(build_context(IMRAD_EN), BASE, CLAIM_EVIDENCE)
    assert key != insight_cache_key(build_context(IMRAD_EN + " "), BASE, CLAIM_EVIDENCE)
    assert key != insight_cache_key(ctx, LAW, CLAIM_EVIDENCE)
    assert key != insight_cache_key(ctx, BASE, dataclasses.replace(CLAIM_EVIDENCE, prompt_id="claim_evidence@2"))
    monkeypatch.setattr(cache_module, "ENGINE_VERSION", "9.9.9")
    assert key != insight_cache_key(ctx, BASE, CLAIM_EVIDENCE)


# --- profiles ------------------------------------------------------------------

@pytest.mark.parametrize("profile", [BASE, *PROFILES.values()], ids=lambda p: p.name)
def test_every_profile_inherits_valid_insight_packs(profile):
    assert profile.insight_packs == (CLAIM_EVIDENCE,)
    for pack in profile.insight_packs:
        assert set(pack.modules) <= set(EVALUATED_MODULES)
        assert set(pack.sections) <= set(SECTION_PATTERNS)


def test_mock_client_output_always_passes_grounding():
    ctx = build_context(IMRAD_EN)
    insights = MockInsightClient().generate(CLAIM_EVIDENCE, ctx, {})
    assert len(insights) == 1
    assert insights[0].evidence_quote == RESULTS_SENTENCE
    assert validate_grounding(insights, ctx, CLAIM_EVIDENCE.modules).accepted == insights


# --- service / task ------------------------------------------------------------

@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(analysis_service, "UPLOAD_DIR", tmp_path)
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _completed_analysis(db, text: str = IMRAD_EN) -> Analysis:
    analysis = Analysis(
        id=uuid.uuid4(), user_id=uuid.uuid4(), file_name="paper.txt", selected_field="education", status="pending"
    )
    db.add(analysis)
    db.commit()
    analysis_service.upload_path(analysis.id, analysis.file_name).write_text(text, encoding="utf-8")
    analysis_service.process_analysis(db, analysis.id)
    db.refresh(analysis)
    return analysis


def _score_snapshot(analysis: Analysis) -> dict:
    return {
        "columns": {name: getattr(analysis, f"score_{name}") for name in EVALUATED_MODULES},
        "risk": analysis.rejection_risk_score,
        "modules": analysis.full_report["modules"],
        "overall": analysis.full_report["overall_score"],
    }


class SpyClient:
    def __init__(self, inner=None, error: Exception | None = None):
        self.inner = inner or MockInsightClient()
        self.error = error
        self.calls = 0

    def generate(self, pack, ctx, rule_modules):
        self.calls += 1
        if self.error:
            raise self.error
        return self.inner.generate(pack, ctx, rule_modules)


def test_generate_insights_writes_grounded_mock_insight_without_touching_scores(db):
    analysis = _completed_analysis(db)
    before = _score_snapshot(analysis)

    result = generate_insights(db, analysis.id, client=MockInsightClient())

    db.refresh(analysis)
    insights = analysis.full_report["insights"]
    assert result["status"] == insights["status"] == "ready"
    assert insights["profile"] == "education"
    assert len(insights["items"]) == 1
    assert insights["items"][0]["evidence_quote"] == RESULTS_SENTENCE
    assert insights["packs"] == [
        {"name": "claim_evidence", "prompt_id": "claim_evidence@1", "cache_hit": False, "rejected": 0}
    ]
    assert analysis.status == "completed"
    assert _score_snapshot(analysis) == before
    assert db.query(InsightCache).count() == 1


def test_second_run_is_served_from_cache_with_zero_client_calls(db):
    first = _completed_analysis(db)
    generate_insights(db, first.id, client=MockInsightClient())

    # Ayni metin, farkli analiz kaydi (ornegin ayni makale tekrar yuklendi).
    second = _completed_analysis(db)
    spy = SpyClient()
    generate_insights(db, second.id, client=spy)

    db.refresh(first)
    db.refresh(second)
    assert spy.calls == 0
    assert second.full_report["insights"]["packs"][0]["cache_hit"] is True
    assert second.full_report["insights"]["items"] == first.full_report["insights"]["items"]


def test_ungrounded_client_output_is_dropped_before_caching(db):
    class FabricatingClient:
        def generate(self, pack, ctx, rule_modules):
            return [make_insight("This sentence does not appear anywhere in the paper at all.")]

    analysis = _completed_analysis(db)
    generate_insights(db, analysis.id, client=FabricatingClient())

    db.refresh(analysis)
    assert analysis.full_report["insights"]["items"] == []
    assert analysis.full_report["insights"]["packs"][0]["rejected"] == 1
    assert db.query(InsightCache).one().insights == []


def test_client_failure_marks_insights_failed_but_keeps_analysis(db):
    analysis = _completed_analysis(db)
    before = _score_snapshot(analysis)

    result = generate_insights(db, analysis.id, client=SpyClient(error=RuntimeError("provider down")))

    db.refresh(analysis)
    assert result["status"] == analysis.full_report["insights"]["status"] == "failed"
    assert analysis.status == "completed"
    assert _score_snapshot(analysis) == before
    assert db.query(InsightCache).count() == 0


def test_generate_insights_skips_unfinished_and_missing_analyses(db):
    pending = Analysis(id=uuid.uuid4(), user_id=uuid.uuid4(), file_name="paper.txt", status="pending")
    db.add(pending)
    db.commit()
    spy = SpyClient()

    assert generate_insights(db, pending.id, client=spy)["status"] == "skipped_not_completed"
    assert generate_insights(db, uuid.uuid4(), client=spy)["status"] == "not_found"
    assert spy.calls == 0


def test_generate_insights_task_is_registered():
    assert "acaturkai.generate_insights" in celery_app.tasks


# --- Anthropic client (API cagrisi yok: sahte SDK istemcisi) -------------------

class FakeAnthropic:
    """beta.messages.parse imzasini taklit eder; gelen istegi kaydeder."""

    def __init__(self, response):
        self.requests = []
        self.response = response
        self.beta = SimpleNamespace(messages=SimpleNamespace(parse=self._parse))

    def _parse(self, **kwargs):
        self.requests.append(kwargs)
        return self.response


def _response(stop_reason="end_turn", parsed=None, category=None):
    stop_details = SimpleNamespace(category=category) if stop_reason == "refusal" else None
    return SimpleNamespace(stop_reason=stop_reason, stop_details=stop_details, parsed_output=parsed)


RULE_MODULES = {
    "findings": {"score": 33.3, "metrics": {"stat_marker_groups": 1}, "feedback": ["az istatistik"]},
    "conclusions": {"score": 53.3, "metrics": {"has_limitations": False}, "feedback": []},
    "title": {"score": 73.0, "metrics": {}, "feedback": []},
}


def test_anthropic_client_request_enforces_schema_and_assembles_prompt():
    fake = FakeAnthropic(_response(parsed=InsightBatch(insights=[make_insight(RESULTS_SENTENCE)])))
    client = AnthropicInsightClient(client=fake)
    ctx = build_context(IMRAD_EN)

    insights = client.generate(CLAIM_EVIDENCE, ctx, RULE_MODULES)

    assert [i.evidence_quote for i in insights] == [RESULTS_SENTENCE]
    request = fake.requests[0]
    assert request["model"] == "claude-opus-5-5"
    assert request["output_format"] is InsightBatch
    assert request["output_config"] == {"effort": "medium"}
    assert request["betas"] == ["server-side-fallback-2026-07-01"] and request["fallbacks"] == "default"
    assert "findings, conclusions" in request["system"]  # izinli moduller istemde
    user = request["messages"][0]["content"]
    assert RESULTS_SENTENCE in user  # paket kesiti
    findings = json.loads(user.split("<kural_bulgulari>\n", 1)[1].split("\n</kural_bulgulari>", 1)[0])
    assert set(findings) == {"findings", "conclusions"}  # paket disi modul (title) gonderilmez


def test_anthropic_client_request_is_byte_stable_for_same_input():
    ctx = build_context(IMRAD_EN)
    client = AnthropicInsightClient(client=FakeAnthropic(_response()))
    first = client.build_request(CLAIM_EVIDENCE, ctx, RULE_MODULES)
    second = client.build_request(CLAIM_EVIDENCE, build_context(IMRAD_EN), dict(reversed(RULE_MODULES.items())))
    assert first["system"] == second["system"]
    assert first["messages"] == second["messages"]


@pytest.mark.parametrize(
    "response",
    [_response("refusal", category="cyber"), _response("max_tokens"), _response("end_turn", parsed=None)],
    ids=["refusal", "max_tokens", "unparsed"],
)
def test_anthropic_client_returns_nothing_on_refusal_or_incomplete_output(response):
    client = AnthropicInsightClient(client=FakeAnthropic(response))
    assert client.generate(CLAIM_EVIDENCE, build_context(IMRAD_EN), RULE_MODULES) == []


def test_prompt_registry_covers_every_pack_and_rejects_unknown_ids():
    packs = {pack for profile in [BASE, *PROFILES.values()] for pack in profile.insight_packs}
    assert {pack.prompt_id for pack in packs} <= set(PROMPTS)
    with pytest.raises(KeyError):
        get_prompt("claim_evidence@999")


def test_insight_client_factory(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "INSIGHTS_PROVIDER", "mock")
    assert isinstance(get_insight_client(), MockInsightClient)
    monkeypatch.setattr(settings, "INSIGHTS_PROVIDER", "openai")
    with pytest.raises(ValueError):
        get_insight_client()


# --- trigger: run_analysis -> generate_insights_task ----------------------------

@pytest.mark.parametrize(
    ("status", "enabled", "expected_calls"),
    [("completed", True, 1), ("skipped_already_completed", True, 0), ("failed", True, 0), ("completed", False, 0)],
)
def test_run_analysis_enqueues_insights_only_after_fresh_completion(monkeypatch, status, enabled, expected_calls):
    analysis_id = str(uuid.uuid4())
    queued: list[str] = []
    monkeypatch.setattr(analysis_service, "process_analysis", lambda db, aid: {"status": status, "analysis_id": aid})
    monkeypatch.setattr(celery_module.generate_insights_task, "delay", queued.append)
    monkeypatch.setattr(celery_module.settings, "INSIGHTS_ENABLED", enabled)

    result = celery_module.run_analysis(analysis_id)

    assert result["status"] == status
    assert queued == [analysis_id] * expected_calls


# --- PDF: "Editor Gorusu" --------------------------------------------------------

def _analysis_with_insights(status: str, items: list[dict]) -> Analysis:
    return Analysis(
        id=uuid.uuid4(), status="completed", language="en", word_count=500, title="Başlık",
        full_report={"modules": {}, "insights": {"status": status, "items": items}}, revision_suggestions={},
    )


def test_pdf_html_renders_ready_insights_sorted_by_severity_and_escaped():
    minor = make_insight(RESULTS_SENTENCE, severity="minor", issue="Küçük sorun")
    blocker = make_insight('<b>"Nedensel" iddia</b> ileri sürülüyor', severity="blocker", issue="Nedensellik hatası")
    html = pdf_service.render_html(_analysis_with_insights("ready", [minor.model_dump(), blocker.model_dump()]))

    assert "Editör Görüşü" in html
    assert html.index("Engelleyici") < html.index("Küçük</span>")  # once en agir
    assert "<blockquote>" in html and RESULTS_SENTENCE in html
    assert "<b>" not in html and "&lt;b&gt;" in html  # alinti kullanici metni -> kacirilir
    assert "Öneri:" in html


@pytest.mark.parametrize("status", ["failed", "pending", None])
def test_pdf_html_omits_editor_section_unless_ready(status):
    analysis = _analysis_with_insights(status, [make_insight(RESULTS_SENTENCE).model_dump()])
    if status is None:
        analysis.full_report = {"modules": {}}
    assert "Editör Görüşü" not in pdf_service.render_html(analysis)


def test_pdf_contains_editor_view_with_turkish_text():
    from pypdf import PdfReader

    insight = make_insight(RESULTS_SENTENCE, issue="İddia kanıtın ötesine geçiyor: nedensellik çıkarımı yapılmış.")
    pdf = pdf_service.render_pdf(_analysis_with_insights("ready", [insight.model_dump()]))

    text = "".join(page.extract_text() for page in PdfReader(io.BytesIO(pdf)).pages)
    assert "Editör Görüşü" in text
    assert "İddia kanıtın ötesine geçiyor" in text
