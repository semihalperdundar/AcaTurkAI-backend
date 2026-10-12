"""
Istem sablonlari: prompt_id -> sistem istemi + gorev talimati.

Yeni surum = yeni anahtar ("claim_evidence@2"); eski anahtar silinmez ki onbellekteki
eski icgorulerin hangi istemle uretildigi izlenebilsin. prompt_id onbellek anahtarina
girdigi icin surum degisikligi eski ciktiyi otomatik olarak gecersiz kilar.
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.services.analysis.profiles import InsightPack

COMMON_RULES = """\
Kurallar:
- Yalnizca <makale_kesiti> icindeki metne dayan; kesitte olmayan bir sey hakkinda yorum yapma.
- evidence_quote alanina kesitten TEK bir cumleyi (veya en az 4 kelimelik ardisik bir parcayi) \
harfi harfine kopyala. Yeniden ifade etme, kisaltma, uc nokta ekleme: alinti metinde birebir \
aranir, bulunamazsa icgoru atilir.
- module alani yalnizca su degerlerden biri olabilir: {modules}.
- issue, why_reviewers_care, concrete_fix ve example_rewrite alanlarini Turkce yaz; alinti \
makalenin kendi dilinde kalir.
- En fazla 3 icgoru ver ve en onemlisinden basla. Gercek bir sorun yoksa bos liste dondur; \
liste doldurmak icin zayif bir icgoru uretme.
- <kural_bulgulari> kural tabanli motorun on bulgularidir; sayim yapmana gerek yok, onlari \
anlamsal yargin icin baglam olarak kullan.
"""


@dataclass(frozen=True)
class PromptTemplate:
    prompt_id: str
    system: str
    task: str

    def render_system(self, pack: InsightPack) -> str:
        return f"{self.system}\n\n{self.task}\n\n{COMMON_RULES.format(modules=', '.join(pack.modules))}"


PROMPTS: dict[str, PromptTemplate] = {
    "claim_evidence@1": PromptTemplate(
        prompt_id="claim_evidence@1",
        system=(
            "Sen hakemli akademik dergilerde deneyimli bir hakemsin. Gorevin, bir makalenin "
            "bulgular ve sonuc bolumlerini okuyup hakemlerin ret ya da buyuk revizyon gerekcesi "
            "yapacagi iddia-kanit uyumsuzluklarini bulmak."
        ),
        task=(
            "Ozellikle sunlara bak:\n"
            "- Kanitin otesine gecen iddialar (korelasyonel desenden nedensellik cikarmak, "
            "orneklemin otesine genelleme).\n"
            "- Sonucta ileri surulen ama bulgularda raporlanmamis sonuclar.\n"
            "- Istatistiksel olarak anlamsiz ya da raporlanmamis bir etkiyi kanitlanmis gibi sunmak.\n"
            "- Bulgularin arastirma sorusunu yanitlayip yanitlamadigi."
        ),
    ),
}


def get_prompt(prompt_id: str) -> PromptTemplate:
    try:
        return PROMPTS[prompt_id]
    except KeyError:
        raise KeyError(f"Tanimsiz prompt_id: {prompt_id}") from None


def rule_findings(pack: InsightPack, rule_modules: Mapping[str, Any]) -> dict:
    """Paketin modulleri icin kural motoru on bulgulari (skor, metrikler, geri bildirim)."""
    return {
        name: {key: rule_modules[name].get(key) for key in ("score", "metrics", "feedback")}
        for name in pack.modules
        if name in rule_modules
    }


def render_user_message(pack: InsightPack, excerpt: str, rule_modules: Mapping[str, Any]) -> str:
    # sort_keys: ayni girdi -> ayni bayt dizisi (istem onbellegi ve tekrarlanabilirlik).
    findings = json.dumps(rule_findings(pack, rule_modules), ensure_ascii=False, sort_keys=True)
    return f"<kural_bulgulari>\n{findings}\n</kural_bulgulari>\n\n<makale_kesiti>\n{excerpt}\n</makale_kesiti>"
