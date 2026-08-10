import uuid
from datetime import datetime

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
