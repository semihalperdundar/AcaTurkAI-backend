"""
Icgoru istemcileri (ayni Protocol, servis istemciden bagimsiz):
  - AnthropicInsightClient: Claude API, yapilandirilmis cikti (Insight semasi)
  - MockInsightClient     : dis API yok, 0 maliyet; test ve yerel gelistirme icin
"""
from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Protocol

import anthropic

from app.config import get_settings
from app.services.analysis.text_utils import split_sentences
from app.services.insights.prompts import get_prompt, render_user_message
from app.services.insights.schema import Insight, InsightBatch

logger = logging.getLogger(__name__)

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


class AnthropicInsightClient:
    """Claude API istemcisi. Tek paket = tek istek; cikti Insight semasina zorlanir.

    - Yapilandirilmis cikti: beta.messages.parse(output_format=InsightBatch) -> parsed_output
      SDK tarafinda Pydantic ile dogrulanir; sema disi cikti istisna firlatir.
    - Guvenlik siniflandiricisi reddederse (stop_reason="refusal") sunucu tarafli
      fallbacks="default" istegi uygun modelde yeniden calistirir; zincir yine reddederse bos liste.
    - API/ag hatalari yukari firlatilir: servis icgoruyu "failed" isaretler, analiz bozulmaz.
      (SDK 408/409/429/5xx ve baglanti hatalarini zaten max_retries kadar yeniden dener.)
    """

    FALLBACK_BETA = "server-side-fallback-2026-07-01"

    def __init__(
        self,
        client: anthropic.Anthropic | None = None,
        model: str | None = None,
        effort: str | None = None,
        max_tokens: int = 16000,
    ) -> None:
        settings = get_settings()
        self.client = client or (
            anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
            if settings.ANTHROPIC_API_KEY
            else anthropic.Anthropic()  # ANTHROPIC_API_KEY env / `ant auth login` profili
        )
        self.model = model or settings.INSIGHTS_MODEL
        self.effort = effort or settings.INSIGHTS_EFFORT
        self.max_tokens = max_tokens

    def build_request(self, pack: InsightPack, ctx: Context, rule_modules: Mapping[str, Any]) -> dict[str, Any]:
        """Istek govdesi (ayri fonksiyon: istem birlesimi API cagrisi olmadan test edilir)."""
        prompt = get_prompt(pack.prompt_id)
        return {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": prompt.render_system(pack),
            "messages": [
                {"role": "user", "content": render_user_message(pack, build_excerpt(ctx, pack), rule_modules)}
            ],
            "output_config": {"effort": self.effort},
            "output_format": InsightBatch,
            "betas": [self.FALLBACK_BETA],
            "fallbacks": "default",
        }

    def generate(self, pack: InsightPack, ctx: Context, rule_modules: Mapping[str, Any]) -> list[Insight]:
        response = self.client.beta.messages.parse(**self.build_request(pack, ctx, rule_modules))

        if response.stop_reason == "refusal":
            category = response.stop_details.category if response.stop_details else None
            logger.warning("Icgoru istegi reddedildi (pack=%s, category=%s)", pack.name, category)
            return []
        if response.stop_reason == "max_tokens" or response.parsed_output is None:
            logger.warning("Icgoru ciktisi eksik (pack=%s, stop_reason=%s)", pack.name, response.stop_reason)
            return []
        return list(response.parsed_output.insights)


def get_insight_client() -> InsightClient:
    provider = get_settings().INSIGHTS_PROVIDER
    if provider == "anthropic":
        return AnthropicInsightClient()
    if provider == "mock":
        return MockInsightClient()
    raise ValueError(f"Bilinmeyen INSIGHTS_PROVIDER: {provider}")
