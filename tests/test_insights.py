"""
Zengin yol (LLM icgoru) altyapisi: sozlesme, grounding, onbellek, mock pipeline.
Dis API cagrisi yok; MockInsightClient ve sahte istemcilerle calisir.
"""
import dataclasses
import uuid

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
from app.services.insights.client import MockInsightClient
from app.services.insights.grounding import validate_grounding
from app.services.insights.schema import Insight
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
