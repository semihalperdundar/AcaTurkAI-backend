"""
Icgoru istemcileri. Simdilik yalnizca MockInsightClient var: dis API cagrisi yok, 0 maliyet.

Gercek istemci ayni Protocol'u uygular; servis istemciden bagimsizdir.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Protocol

from app.config import get_settings
from app.services.analysis.text_utils import split_sentences
from app.services.insights.schema import Insight

if TYPE_CHECKING:
    from app.services.analysis.context import Context
    from app.services.analysis.profiles import InsightPack

CHARS_PER_TOKEN = 4  # kaba tahmin; kirpma deterministik oldugu surece kesinlik gerekmez


def build_excerpt(ctx: Context, pack: InsightPack) -> str:
    """Paketin bolumlerini sirayla birlestirip butceye gore kirpar (LLM'e giden tek girdi)."""
    parts = [ctx.sections[name] for name in pack.sections if ctx.sections.get(name)]
    excerpt = "\n\n".join(parts) or ctx.body
    return excerpt[: pack.max_input_tokens * CHARS_PER_TOKEN]


class InsightClient(Protocol):
    def generate(
        self, pack: InsightPack, ctx: Context, rule_modules: Mapping[str, Any]
    ) -> list[Insight]: ...


class MockInsightClient:
    """Deterministik sahte istemci: kesitin ilk cumlesini alinti olarak kullanir,
    bu yuzden GroundingValidator'dan her zaman gecer. Pipeline'i uctan uca test etmek icindir.
    """

    def generate(self, pack: InsightPack, ctx: Context, rule_modules: Mapping[str, Any]) -> list[Insight]:
        sentences = split_sentences(build_excerpt(ctx, pack))
        if not sentences:
            return []
        module = pack.modules[0]
        rule_score = rule_modules.get(module, {}).get("score")
        return [
            Insight(
                module=module,
                severity="minor",
                issue=f"[MOCK] {pack.name} paketi icin ornek icgoru (kural skoru: {rule_score}).",
                evidence_quote=sentences[0],
                why_reviewers_care="[MOCK] Gercek istemci bu alanda hakem gerekcesini uretecek.",
                concrete_fix="[MOCK] Gercek istemci bu alanda uygulanabilir duzeltmeyi uretecek.",
                example_rewrite=None,
            )
        ]


def get_insight_client() -> InsightClient:
    provider = get_settings().INSIGHTS_PROVIDER
    if provider == "mock":
        return MockInsightClient()
    raise NotImplementedError(f"Icgoru saglayicisi henuz uygulanmadi: {provider}")
