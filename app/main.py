"""
AcaTurkAI backend giris noktasi.
Spec referansi: Bolum 13.1 (Backend: FastAPI), Bolum 20 (Faz 1 -> Ay 1: Backend Altyapi).
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers import analyses, auth, corpus

settings = get_settings()

app = FastAPI(
    title=settings.APP_NAME,
    description="Akademik Metin Kalite Analiz Platformu — Backend API",
    version="0.1.0-faz1",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(analyses.router)
app.include_router(corpus.router)


@app.get("/", tags=["health"])
def root():
    return {"app": settings.APP_NAME, "status": "ok", "phase": "Faz 1 - Ay 1"}


@app.get("/health", tags=["health"])
def health():
    return {"status": "ok"}
