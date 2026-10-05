import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class AnalysisCreateResponse(BaseModel):
    id: uuid.UUID
    status: str
    file_name: str | None = None
    selected_field: str | None = None

    model_config = {"from_attributes": True}


class AnalysisSummary(BaseModel):
    id: uuid.UUID
    title: str | None = None
    selected_field: str | None = None
    rejection_risk_score: float | None = None
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class AnalysisReportResponse(BaseModel):
    """GET /api/analyses/{id}/report - pending/processing iken skor/rapor alanlari null doner."""

    id: uuid.UUID
    status: str
    rejection_risk_score: float | None = None
    word_count: int | None = None
    language: str | None = None
    score_structure: float | None = None
    score_lexical: float | None = None
    score_delivery: float | None = None
    full_report: dict[str, Any] | None = None
    revision_suggestions: dict[str, Any] | None = None

    model_config = {"from_attributes": True}
