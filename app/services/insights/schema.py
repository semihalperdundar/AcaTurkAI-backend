"""Icgoru sozlesmesi: LLM (veya mock) ciktisi bu semaya uymak zorundadir."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Severity = Literal["blocker", "major", "minor"]


class Insight(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    module: str = Field(min_length=1)  # ait oldugu kural modulu (InsightPack.modules'ten biri)
    severity: Severity  # hakemin ret olasiligina etkisi
    issue: str = Field(min_length=1)  # tek cumle: hakem ne gorecek
    evidence_quote: str = Field(min_length=1)  # makaleden BIREBIR alinti (GroundingValidator dogrular)
    why_reviewers_care: str = Field(min_length=1)
    concrete_fix: str = Field(min_length=1)
    example_rewrite: str | None = None
