"""
Alan profilleri (Domain Strategy): alana ozgu TUM kural parametreleri burada.

Moduller alan adini bilmez; yalnizca kendilerine verilen params sozlugunu okur.
Yeni alan = BASE.extend(...) ile tek bir profil + PROFILES kaydina bir satir.

v1.2.0 davranisi birebir korunur: tum profiller ayni MODULE_WEIGHTS'i kullanir;
yalnizca health ve law, onceden modullerin icinde dagilmis olan farklari tasir.
Alan basina agirliklar (skoru degistiren adim) ayri bir surumle gelecek.
"""
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

MODULE_WEIGHTS: Mapping[str, float] = MappingProxyType({
    "title": 0.05,
    "abstract": 0.10,
    "structure": 0.10,
    "literature": 0.10,
    "originality": 0.10,
    "methodology": 0.15,
    "findings": 0.12,
    "conclusions": 0.08,
    "references": 0.07,
    "lexical": 0.06,
    "delivery": 0.07,
})

Params = Mapping[str, Any]


@dataclass(frozen=True)
class InsightPack:
    """Zengin yol (LLM icgorusu) icin tek cagri tanimi. Skoru ASLA etkilemez.

    modules          : icgorunun ait oldugu kural modulleri (Insight.module bunlardan biri olmali)
    sections         : LLM'e gidecek Context.sections kesitleri (sirali)
    max_input_tokens : kesit butcesi (yaklasik; kirpma deterministik)
    prompt_id        : istem sablonu + surumu, ornegin "claim_evidence@1" (onbellek anahtarina girer)
    """

    name: str
    modules: tuple[str, ...]
    sections: tuple[str, ...]
    max_input_tokens: int
    prompt_id: str


CLAIM_EVIDENCE = InsightPack(
    name="claim_evidence",
    modules=("findings", "conclusions"),
    sections=("results", "discussion", "conclusion"),
    max_input_tokens=1000,
    prompt_id="claim_evidence@1",
)


@dataclass(frozen=True)
class DomainProfile:
    name: str
    weights: Mapping[str, float]
    params: Mapping[str, Params] = field(default_factory=dict)
    insight_packs: tuple[InsightPack, ...] = ()

    def params_for(self, module: str) -> Params:
        """Salt okunur: bir modul parametreleri degistirip sonraki analizi etkileyemez."""
        return MappingProxyType(dict(self.params.get(module, {})))

    def extend(
        self,
        name: str,
        *,
        weights: Mapping[str, float] | None = None,
        params: Mapping[str, Params] | None = None,
        insight_packs: tuple[InsightPack, ...] | None = None,
    ) -> "DomainProfile":
        """Kalitim: yalnizca farki yaz. Modul icinde anahtar bazinda (sig) birlestirilir.

        insight_packs verilmezse ebeveynden miras alinir; verilirse listeyi tamamen degistirir.
        """
        overrides = params or {}
        merged = {
            module: {**self.params.get(module, {}), **overrides.get(module, {})}
            for module in {*self.params, *overrides}
        }
        return DomainProfile(
            name,
            MappingProxyType({**self.weights, **(weights or {})}),
            merged,
            self.insight_packs if insight_packs is None else insight_packs,
        )


BASE = DomainProfile(
    "default",
    weights=MODULE_WEIGHTS,
    params={
        "title": {},
        "abstract": {
            "moves": ("purpose", "method", "results", "conclusion"),
            "require_quantitative": True,
            "weights": {"moves": 0.50, "length": 0.30, "keywords": 0.10, "quantitative": 0.10},
            "profile_label": "empirical",
        },
        "structure": {
            "core_weights": {"abstract": 20, "introduction": 20, "methodology": 25, "results": 20, "conclusion": 15},
            "profile_label": "imrad",
        },
        "literature": {
            "scope": "review",  # alanyazin bolumu, yoksa giris
            "density_band": {"ideal": (1.0, 4.0), "zero": (0.1, 8.0)},
        },
        "originality": {"gap_pattern_sets": ("general",)},
        "methodology": {
            "scope": "section",  # yontem bolumu; yoksa tum metin (cezali)
            "elements": {"design": 20, "sample": 20, "instruments": 20, "analysis": 25, "validity": 10, "ethics": 5},
            "ethics_warning": False,
            "profile_label": "default",
        },
        "findings": {"evidence_profile": "auto", "profile_label": None},  # nicel/nitel metinden secilir
        "conclusions": {
            "citation_penalty": 25,
            "weights": {
                "citations": 0.20, "limitations": 0.15, "future": 0.15,
                "implications": 0.15, "alignment": 0.20, "length": 0.15,
            },
            "expect_limitations": True,
            "profile_label": "default",
        },
        "references": {
            "count_band": {"ideal": (25, 70), "zero": (3, 200)},
            "check_recency": True,
            "check_doi": True,
            "profile_label": "default",
        },
        "lexical": {},
        "delivery": {},
    },
    insight_packs=(CLAIM_EVIDENCE,),
)

HEALTH = BASE.extend(
    "health",
    params={
        "methodology": {
            "elements": {"design": 15, "sample": 20, "instruments": 15, "analysis": 20, "validity": 10, "ethics": 20},
            "ethics_warning": True,  # etik kurul/onam yoksa masa basi ret uyarisi
            "profile_label": "health",
        },
        "references": {"count_band": {"ideal": (20, 60), "zero": (3, 150)}, "profile_label": "health"},
    },
)

LAW = BASE.extend(
    "law",
    params={
        "abstract": {
            "moves": ("purpose", "argument", "conclusion"),
            "require_quantitative": False,
            "weights": {"moves": 0.60, "length": 0.30, "keywords": 0.10, "quantitative": 0.0},
            "profile_label": "law",
        },
        "structure": {
            "core_weights": {"abstract": 30, "introduction": 35, "conclusion": 35},
            "profile_label": "law",
        },
        "literature": {
            "scope": "body",  # alanyazin argumantasyona yayilir; oran olculmez
            "density_band": {"ideal": (0.5, 4.0), "zero": (0.05, 8.0)},
        },
        "originality": {"gap_pattern_sets": ("general", "legal_dispute")},
        "methodology": {
            "scope": "body",  # ayri yontem bolumu beklenmez
            "elements": {"approach": 60, "sources": 40},
            "profile_label": "law",
        },
        "findings": {"evidence_profile": "legal", "profile_label": "law"},
        "conclusions": {
            "citation_penalty": 10,
            "weights": {
                "citations": 0.15, "limitations": 0.05, "future": 0.15,
                "implications": 0.25, "alignment": 0.25, "length": 0.15,
            },
            "expect_limitations": False,
            "profile_label": "law",
        },
        "references": {
            "count_band": {"ideal": (30, 150), "zero": (5, 300)},
            "check_recency": False,  # mevzuat/ictihat ve temel eserler eski olabilir
            "check_doi": False,
            "profile_label": "law",
        },
    },
)

# Kullanici alanlari (app/models/user.py ile ayni 6 kod). Simdilik BASE ile ayni davranir.
EDUCATION = BASE.extend("education")
SOCIAL_SCIENCES = BASE.extend("social_sciences")
ENGINEERING = BASE.extend("engineering")
BUSINESS = BASE.extend("business")

PROFILES: Mapping[str, DomainProfile] = MappingProxyType(
    {p.name: p for p in (EDUCATION, SOCIAL_SCIENCES, ENGINEERING, HEALTH, LAW, BUSINESS)}
)


def get_profile(field_name: str | None) -> DomainProfile:
    """selected_field -> profil. Bilinmeyen/bos alan BASE'e duser (v1.2.0 ile ayni)."""
    return PROFILES.get(field_name or "", BASE)
