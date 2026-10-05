"""
Analiz raporunun PDF'e donusturulmesi: full_report (JSON) -> Jinja2 HTML -> WeasyPrint PDF.

Guvenlik:
  - Jinja2 autoescape acik: baslik/geri bildirim gibi kullanici metninden turetilen
    alanlar HTML olarak yorumlanmaz.
  - WeasyPrint url_fetcher tum dis kaynaklari reddeder: enjekte edilmis bir
    <img src="file:///..."> veya http istegi yerel dosya okuma / SSRF'ye donusemez.
Turkce karakterler: HTML UTF-8, font-family Turkce glif iceren fontlarla baslar;
WeasyPrint kullanilan fontlari PDF'e gomer (subset).
"""
from datetime import datetime, timezone

from jinja2 import Environment, select_autoescape

from app.models.analysis import Analysis

MODULE_LABELS = {
    "structure": "Yapı (IMRaD)",
    "lexical": "Sözcük Çeşitliliği",
    "delivery": "Anlatım ve Üslup",
    "title": "Başlık",
    "abstract": "Öz",
    "literature": "Alanyazın",
    "originality": "Özgünlük",
    "methodology": "Yöntem",
    "findings": "Bulgular",
    "conclusions": "Sonuçlar",
    "references": "Kaynakça",
}
VERDICT_LABELS = {
    "accept": "Kabul",
    "minor_revision": "Küçük revizyon",
    "major_revision": "Büyük revizyon",
    "reject": "Ret",
}

REPORT_TEMPLATE = """<!doctype html>
<html lang="tr">
<head>
<meta charset="utf-8">
<title>AcaTurkAI Analiz Raporu</title>
<style>
  @page { size: A4; margin: 18mm 16mm 20mm;
          @bottom-center { content: "AcaTurkAI · Sayfa " counter(page) " / " counter(pages);
                           font-family: "DejaVu Sans", "Noto Sans", "Segoe UI", Arial, sans-serif;
                           font-size: 8pt; color: #6b7280; } }
  body { font-family: "DejaVu Sans", "Noto Sans", "Segoe UI", Arial, sans-serif;
         font-size: 10pt; line-height: 1.45; color: #111827; }
  h1 { font-size: 18pt; margin: 0 0 2mm; }
  h2 { font-size: 13pt; margin: 8mm 0 3mm; padding-bottom: 1mm; border-bottom: 1px solid #d1d5db; }
  h3 { font-size: 11pt; margin: 5mm 0 2mm; }
  .meta { color: #4b5563; font-size: 9pt; }
  .kpis { display: flex; gap: 4mm; margin-top: 4mm; }
  .kpi { flex: 1; border: 1px solid #d1d5db; border-radius: 2mm; padding: 3mm; }
  .kpi .label { font-size: 8pt; color: #6b7280; letter-spacing: 0.3pt; }
  .kpi .value { font-size: 16pt; font-weight: bold; }
  table { width: 100%; border-collapse: collapse; }
  th, td { text-align: left; padding: 1.5mm 2mm; border-bottom: 1px solid #e5e7eb; vertical-align: top; }
  th { font-size: 8.5pt; color: #374151; background: #f3f4f6; }
  td.num { text-align: right; white-space: nowrap; }
  .muted { color: #6b7280; }
  ul { margin: 1mm 0 0 5mm; padding: 0; }
  li { margin-bottom: 1mm; }
</style>
</head>
<body>
  <h1>Analiz Raporu</h1>
  <div class="meta">
    {{ title or file_name or "Başlıksız çalışma" }}<br>
    Analiz No: {{ analysis_id }} · Alan: {{ field or "-" }} · Dil: {{ language | upper }}
    · Sözcük: {{ word_count }} · Oluşturulma: {{ generated_at }}
  </div>

  <h2>Yönetici Özeti</h2>
  <div class="kpis">
    <div class="kpi"><div class="label">Genel Skor</div><div class="value">{{ overall_score }} / 100</div></div>
    <div class="kpi"><div class="label">Ret Riski</div><div class="value">%{{ rejection_risk_score }}</div></div>
    <div class="kpi"><div class="label">Yayın Kurulu Kararı</div><div class="value">{{ decision }}</div></div>
  </div>

  <h2>Modül Skorları</h2>
  <table>
    <tr><th>Modül</th><th>Ağırlık</th><th>Skor</th><th>Karar</th></tr>
    {% for m in modules %}
    <tr><td>{{ m.label }}</td><td class="num">%{{ m.weight }}</td>
        <td class="num">{{ m.score }}</td><td>{{ m.verdict }}</td></tr>
    {% endfor %}
  </table>
  {% if not_yet_evaluated %}
  <p class="muted">Henüz değerlendirilmeyen modüller: {{ not_yet_evaluated | join(", ") }}.</p>
  {% endif %}

  <h2>Yayın Kurulu Değerlendirmeleri</h2>
  {% for r in reviews %}
  <h3>{{ r.agent }} — {{ r.verdict }} <span class="muted">(güven: {{ r.confidence }})</span></h3>
  <p>{{ r.summary }}</p>
  {% if r.key_issues %}<ul>{% for issue in r.key_issues %}<li>{{ issue }}</li>{% endfor %}</ul>{% endif %}
  {% endfor %}

  <h2>Revizyon Önerileri</h2>
  {% for s in suggestions %}
  <h3>{{ s.label }}</h3>
  {% if s.entries %}<ul>{% for item in s.entries %}<li>{{ item }}</li>{% endfor %}</ul>
  {% else %}<p class="muted">Bu modül için öneri yok.</p>{% endif %}
  {% endfor %}
</body>
</html>
"""

_env = Environment(autoescape=select_autoescape(default=True, default_for_string=True))
_template = _env.from_string(REPORT_TEMPLATE)


def _deny_url_fetcher(url: str, *_args, **_kwargs):
    raise ValueError(f"Dis kaynak erisimi kapali: {url}")


def _verdict(value: str | None) -> str:
    return VERDICT_LABELS.get(value or "", value or "-")


def build_context(analysis: Analysis) -> dict:
    report = analysis.full_report or {}
    modules = report.get("modules", {})
    weights = report.get("weights", {})
    suggestions = analysis.revision_suggestions or {}

    return {
        "analysis_id": str(analysis.id),
        "title": analysis.title,
        "file_name": analysis.file_name,
        "field": report.get("field") or analysis.selected_field,
        "language": analysis.language or report.get("language", ""),
        "word_count": analysis.word_count or report.get("word_count", 0),
        "generated_at": datetime.now(timezone.utc).strftime("%d.%m.%Y %H:%M UTC"),
        "overall_score": report.get("overall_score", "-"),
        "rejection_risk_score": analysis.rejection_risk_score,
        "decision": _verdict(report.get("editorial_board", {}).get("decision")),
        "modules": [
            {
                "label": MODULE_LABELS.get(name, name),
                "weight": round(weights.get(name, 0) * 100),
                "score": m.get("score"),
                "verdict": _verdict(m.get("agent_review", {}).get("verdict")),
            }
            for name, m in modules.items()
        ],
        "reviews": [
            {**r, "verdict": _verdict(r.get("verdict"))}
            for r in report.get("editorial_board", {}).get("reviews", [])
        ],
        "suggestions": [
            {"label": MODULE_LABELS.get(name, name), "entries": items or []}
            for name, items in suggestions.items()
        ],
        "not_yet_evaluated": [MODULE_LABELS.get(n, n) for n in report.get("not_yet_evaluated", [])],
    }


def render_html(analysis: Analysis) -> str:
    return _template.render(**build_context(analysis))


def render_pdf(analysis: Analysis) -> bytes:
    # Gec import: WeasyPrint yuklemesi agir ve Pango sistem kutuphanesi ister;
    # uygulamanin geri kalani (ve PDF disi testler) buna bagimli olmasin.
    from weasyprint import HTML

    return HTML(string=render_html(analysis), url_fetcher=_deny_url_fetcher).write_pdf()
