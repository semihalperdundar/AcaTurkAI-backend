"""Icgoru sozlesmesi: LLM (veya mock) ciktisi bu semaya uymak zorundadir.

Field aciklamalari yapilandirilmis cikti semasiyla modele de gider (Anthropic SDK
Pydantic modelini JSON semasina cevirir; kisitlar istemci tarafinda dogrulanir).
"""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Severity = Literal["blocker", "major", "minor"]


class Insight(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    module: str = Field(min_length=1, description="Icgorunun ait oldugu kural modulu (paketteki modullerden biri).")
    severity: Severity = Field(
        description="blocker: tek basina ret gerekcesi; major: buyuk revizyon gerektirir; minor: kucuk duzeltme."
    )
    issue: str = Field(min_length=1, description="Tek cumle: hakemin gorecegi sorun.")
    evidence_quote: str = Field(
        min_length=1, description="Makaleden harfi harfine kopyalanmis alinti (en az 4 kelime, tek cumle)."
    )
    why_reviewers_care: str = Field(min_length=1, description="Bu sorunun neden ret/revizyon gerekcesi oldugu.")
    concrete_fix: str = Field(min_length=1, description="Yazarin uygulayabilecegi somut duzeltme adimi.")
    example_rewrite: str | None = Field(
        default=None, description="Varsa alintinin duzeltilmis ornek yazimi; yoksa null."
    )


class InsightBatch(BaseModel):
    """Yapilandirilmis cikti kok nesnesi (API dizi degil nesne bekler)."""

    model_config = ConfigDict(extra="forbid")

    insights: list[Insight] = Field(description="En fazla 3 icgoru; gercek bir sorun yoksa bos liste.")
