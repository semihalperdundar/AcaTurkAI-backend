"""
Unpaywall client - DOI basina yasal acik erisim (OA) PDF linki sorgular.

akademik_kutuphane_projesi.md Bolum 4.1 ve 7.3'e dayanir. Guvenli hiz siniri
(Bolum 8.3): 5 req/sn - bu client istekler arasi bekleme uygular.
"""
import time

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

BASE_URL = "https://api.unpaywall.org/v2/{doi}"
MIN_REQUEST_INTERVAL_SECONDS = 0.25  # ~4 req/sn


class UnpaywallError(Exception):
    pass


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(min=2, max=30),
    retry=retry_if_exception_type((requests.RequestException, UnpaywallError)),
)
def get_oa_location(doi: str, email: str) -> dict | None:
    """
    DOI icin Unpaywall'dan en iyi OA konumunu doner:
    {"is_oa": bool, "pdf_url": str|None, "license": str|None, "host_type": str|None}
    veya bulunamazsa None.
    """
    resp = requests.get(BASE_URL.format(doi=doi), params={"email": email}, timeout=20)
    if resp.status_code == 404:
        return None
    if resp.status_code >= 500:
        raise UnpaywallError(f"Unpaywall 5xx: {resp.status_code}")
    resp.raise_for_status()
    data = resp.json()
    time.sleep(MIN_REQUEST_INTERVAL_SECONDS)

    if not data.get("is_oa"):
        return {"is_oa": False, "pdf_url": None, "license": None, "host_type": None}

    best = data.get("best_oa_location") or {}
    return {
        "is_oa": True,
        "pdf_url": best.get("url_for_pdf") or best.get("url"),
        "license": best.get("license"),
        "host_type": best.get("host_type"),
    }


# Spec Bolum 10 / KVKK Madde 6 baglaminda: ticari kullanima izin veren lisanslar.
# Diger her lisans (veya lisans bilgisi eksikse) commercial_use_allowed=False kalir.
COMMERCIAL_FRIENDLY_LICENSES = {"cc-by", "cc-by-sa", "cc0", "public-domain", "pd"}


def is_commercial_use_allowed(license_str: str | None) -> bool:
    if not license_str:
        return False
    return license_str.lower() in COMMERCIAL_FRIENDLY_LICENSES
