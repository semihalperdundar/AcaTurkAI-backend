# AcaTurkAI Backend — Faz 1 / Ay 1 İskeleti + Corpus Modülü

Bu, `AcaTurkAI_Project_Spec.md` dosyasının Bölüm 20 → **Faz 1 → Ay 1: Backend Altyapı**
maddelerine karşılık gelen çalışır durumdaki başlangıç iskeletidir.

## Bu iskelette hazır olan

- FastAPI proje yapısı (`app/main.py`, `config.py`, `database.py`)
- SQLAlchemy 2.0 modelleri — spec Bölüm 14'teki 7 tablo (users, analyses, thesis_projects,
  analysis_versions, journals, subscriptions, usage_logs)
- Alembic migration kurulumu (henüz migration dosyası üretilmedi — aşağıya bakın)
- JWT tabanlı auth: `POST /api/auth/register`, `POST /api/auth/login`, `GET /api/auth/me`
- Dosya yükleme + analiz kaydı: `POST /api/analyses` (PDF/DOCX/TXT kabul eder, Celery task'ini tetikler)
- `GET /api/analyses`, `GET /api/analyses/{id}`, `GET /api/analyses/{id}/status`
- Celery + Redis iskeleti (`app/core/celery_app.py`) — gerçek 11 modüllü analiz motoru henüz yok (Ay 2 kapsamı)
- Docker Compose (Postgres 15 + Redis 7 + api + worker)
- `pytest` ile health-check testi
- **Corpus toplama modülü** (`app/services/corpus/`, `app/models/corpus.py`, `app/routers/corpus.py`) —
  `akademik_kutuphane_projesi.md` sohbetindeki "Akademik Referans Kütüphanesi" planının backend'e
  entegrasyonu. Detaylar aşağıda ayrı bir bölümde.

## Bu iskelette henüz olmayan (bilinçli olarak ertelenen)

- Google OAuth gerçek implementasyonu (`GOOGLE_CLIENT_ID/SECRET` gerektirir — stub 501 döner)
- S3/Cloudflare R2 entegrasyonu (şu an dosyalar `uploads/` klasörüne local yazılıyor)
- 11 analiz modülünün gerçek NLP/LLM mantığı (spec Bölüm 12) — Ay 2
- Stripe entegrasyonu, journals/projects router'ları — Ay 2-3

## Çalıştırma

### 1. Docker Compose ile (önerilen)

```bash
cp .env.example .env   # JWT_SECRET_KEY'i mutlaka degistirin
docker compose up --build
```

API: http://localhost:8000 — Swagger UI: http://localhost:8000/docs

### 2. Local Python ortamıyla (venv)

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# .env icindeki DATABASE_URL'i kendi Postgres'inize gore duzenleyin
# (Postgres yoksa: docker run -d -p 5432:5432 -e POSTGRES_USER=acaturkai \
#   -e POSTGRES_PASSWORD=acaturkai -e POSTGRES_DB=acaturkai postgres:15)

alembic revision --autogenerate -m "init schema"
alembic upgrade head

uvicorn app.main:app --reload
```

### 3. Anaconda ile (VS Code için önerilen)

```bash
conda env create -f environment.yml
conda activate acaturkai

copy .env.example .env   # Windows; Mac/Linux'ta: cp .env.example .env
# .env icindeki DATABASE_URL'i kendi Postgres'inize gore duzenleyin

alembic revision --autogenerate -m "init schema"
alembic upgrade head

uvicorn app.main:app --reload
```

Ortamı güncellemek gerektiğinde (`requirements.txt` değiştiğinde):

```bash
conda env update -f environment.yml --prune
```

**VS Code'da açma:** bu klasörü (`backend/`) VS Code ile aç → `Ctrl+Shift+P` →
"Python: Select Interpreter" → `acaturkai` (conda) ortamını seç. `.vscode/settings.json`
zaten pytest'i test gezgininde otomatik keşfedecek şekilde ayarlı;
`.vscode/extensions.json` Python + Pylance eklentilerini önerir.

### Testleri çalıştırma

```bash
pip install pytest
pytest
```

(Health-check testleri DB gerektirmez; auth/analiz testleri için Postgres'in ayakta olması gerekir.)

## Migration

İlk migration (`alembic/versions/d1f440167fdd_init_schema.py`, 11 tablo) mevcut. Yalnızca
Postgres hedefler (`DEFAULT now()`, `JSONB`); testler migration değil `create_all` kullanır.

```bash
alembic upgrade head
# Gerçek Postgres'e karşı model/şema farkı kontrolü (boş revizyon çıkmalı):
alembic revision --autogenerate -m "drift check"
```

## Analiz Motoru v1 (`app/services/analysis/`)

`run_analysis` task'ı → `analysis_service.process_analysis` → `engine.analyze_text`.

| Modül | Kolon | Ölçülen |
|---|---|---|
| `modules/structure.py` | `score_structure` | IMRAD bölümleri (TR+EN başlıklar), sıra, kaynakça; `law` alanı IMRAD beklemez |
| `modules/lexical.py` | `score_lexical` | MATTR (pencere 100), akademik kök yoğunluğu, aşırı tekrar |
| `modules/delivery.py` | `score_delivery` | cümle uzunluğu ort./CV/uzun oranı, gayriresmî ton, geçiş ifadeleri |

- Genel skor: ağırlıklı ortalama (0.40/0.30/0.30), `rejection_risk_score = 100 - overall`.
- `full_report`: modül metrikleri + `editorial_board` (her modül bir hakem: verdict/summary/key_issues/confidence).
  LLM hakemleri (Ay 2+) aynı `agent_review` şemasını doldurur.
- Durum: `pending → processing → completed | failed`. Hata mesajı `full_report.error`;
  `completed` kayıt yeniden gelirse atlanır (idempotent).
- Bant eşikleri v1 sezgisel — corpus normları oluşunca alan bazlı kalibre edilecek.
- Windows'ta local worker: `celery -A app.core.celery_app.celery_app worker --pool=solo --loglevel=info`
  (prefork Windows'ta desteklenmez).

## Corpus Modülü (Akademik Referans Kütüphanesi entegrasyonu)

`akademik_kutuphane_projesi.md` sohbetinde tasarlanan "OpenAlex + Unpaywall + Scimago ile
toplu metadata/OA-PDF toplama" planı, ayrı bir SQLite + yerel klasör kütüphanesi yerine
doğrudan bu backend'in Postgres veritabanına ve mimarisine taşındı. Amaç: spec Bölüm 12'deki
alan normu hesaplamalarını (Modül 4, 6, 8, 9) besleyecek gerçek bir corpus kurmak — bu da
Faz 0 kapanış raporunda açık bırakılan "corpus'un gerçek durumu bilinmiyor" sorusuna cevap.

**Yeni tablolar** (`app/models/corpus.py`): `corpus_works`, `corpus_authors`,
`corpus_work_authors`, `journal_quartile_history` (dergi quartile'ının yıl bazlı geçmişi —
mevcut `journals` tablosu sadece güncel quartile'ı tutar, ama bir makale kendi yayın
yılındaki quartile'a göre sınıflanmalı, spec Bölüm 3.2).

**Alan kodları** OpenAlex concept ID'lerine eşlenir (`app/services/corpus/areas.py`) ve
`User.primary_field` / `Analysis.selected_field` ile AYNI 6 kodu kullanır: `education`,
`social_sciences`, `engineering`, `health`, `law`, `business`.

**Hukuki ayrım kod seviyesinde korunur**: her `corpus_works` satırı bir `source_tier`
(`open_access` / `tdm` / `local_curated`) ve bir `commercial_use_allowed` bayrağı taşır.
Bayrak, Unpaywall'un döndürdüğü lisans bilgisine göre otomatik hesaplanır (yalnızca
CC-BY/CC0/public-domain gibi lisanslarda `True`) — spec Bölüm 10-11'in altını çizdiği
"TDM ve açık erişimi asla karıştırma" kuralının doğrudan uygulanması. `consent_given` alanı,
KVKK Gizlilik Taslağı Madde 6'daki kullanıcı corpus katkısı için ayrı açık rıza kuralını
yansıtır (yalnızca `source_tier=local_curated` için anlamlı).

**Yeni admin endpoint'leri** (`app/routers/corpus.py`, `User.is_admin=True` gerektirir):

```
GET  /api/corpus/areas                 — gecerli 6 alan kodu
GET  /api/corpus/stats                 — corpus'un fiili durumu (alan/quartile/OA/lisans bazinda sayim)
POST /api/corpus/harvest/openalex      — {area_code, year_from, year_to, max_results} -> Celery task kuyruklar
POST /api/corpus/download-oa-pdfs      — {area_code, limit} -> Unpaywall'dan yasal OA PDF indirir
POST /api/corpus/harvest/scimago       — {csv_path, year, set_as_current} -> Scimago yillik CSV import eder
```

**Kullanım örneği** (worker ayaktayken):

```bash
curl -X POST http://localhost:8000/api/corpus/harvest/openalex \
  -H "Authorization: Bearer <admin_token>" -H "Content-Type: application/json" \
  -d '{"area_code": "education", "year_from": 2020, "year_to": 2025, "max_results": 500}'
```

**Henüz yapılmayan / bilinçli ertelenen:**

- Zotero senkronizasyonu (doc'taki Faz 5 — üçüncü katman, manuel kaydedilen kapalı erişim makaleler)
- arXiv / PMC OAI-PMH özel toplu indirme script'leri (şimdilik yalnızca OpenAlex+Unpaywall üzerinden)
- PDF depolama şu an yerel diske (`corpus_pdfs/`) yazıyor — Ay 1'in S3/R2 işiyle birlikte taşınmalı
- Crossref çapraz doğrulama (doc'ta opsiyonel olarak işaretlenmişti, atlandı)

**Not:** `requirements.txt`'e `requests`, `tenacity`, `pandas` eklendi. `.env`'deki mevcut
`OPENALEX_EMAIL` hem OpenAlex hem Unpaywall polite-pool kimliği için kullanılıyor, yeni bir
değişken gerekmedi.

## Sıradaki adımlar (Ay 1'in kalanı)

1. Google OAuth (`app/routers/auth.py` içindeki `google_oauth` stub'ı)
2. S3/R2 dosya depolama (`app/services/analysis_service.py` VE `app/services/corpus_service.py`
   içindeki local disk yazımlarını değiştirin — ikisi de aynı S3/R2 client'ını paylaşmalı)
3. ~~Celery worker'ın gerçek bir görevi uçtan uca çalıştırması~~ → Analiz Motoru v1 (3/11 modül) hazır
4. Corpus tarafında: gerçek bir Scimago CSV + küçük ölçekli bir alan (örn. sadece Eğitim,
   2020-2024) ile uçtan uca deneme — doc'un Bölüm 14'te önerdiği gibi
