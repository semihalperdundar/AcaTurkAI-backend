"""
Zengin yol: hedefli LLM icgoruleri (Rule-Based Scorer + Targeted Insight Generator).

Ilkeler:
  - Skor yalnizca kural motorundan gelir; icgoru skoru ASLA degistirmez.
  - Her icgoru makaleden birebir alinti tasir; alintisi metinde bulunmayan icgoru dusurulur.
  - Icgoruler icerik ozetiyle onbelleklenir: ayni makale -> ayni icgoru, 0 token.
"""
