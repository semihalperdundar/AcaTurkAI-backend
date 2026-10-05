"""
Spec Bolum 15 - Analyses endpoint'leri.

Bu iskelette implemente edilenler:
  POST /api/analyses          — dosya yukleme + analiz kaydi olusturma + Celery tetikleme
  GET  /api/analyses          — kullanicinin analiz listesi
  GET  /api/analyses/{id}     — analiz detayi
  GET  /api/analyses/{id}/status — islem durumu
  GET  /api/analyses/{id}/report — skorlar + tam rapor (pending/processing iken null alanlarla)
  GET  /api/analyses/{id}/pdf    — PDF rapor (completed: 200, pending/processing: 409, failed: 422)
"""
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.analysis import Analysis
from app.routers.deps import get_current_user
from app.schemas.analysis import AnalysisCreateResponse, AnalysisReportResponse, AnalysisSummary
from app.services.analysis_service import AnalysisError, create_analysis_from_upload
from app.services.pdf_service import render_pdf

router = APIRouter(prefix="/api/analyses", tags=["analyses"])


@router.post("", response_model=AnalysisCreateResponse, status_code=status.HTTP_201_CREATED)
def create_analysis(
    file: UploadFile = File(...),
    selected_field: str = Form(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    try:
        analysis = create_analysis_from_upload(db, current_user.id, file, selected_field)
    except AnalysisError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return analysis


@router.get("", response_model=list[AnalysisSummary])
def list_analyses(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    return (
        db.query(Analysis)
        .filter(Analysis.user_id == current_user.id)
        .order_by(Analysis.created_at.desc())
        .all()
    )


@router.get("/{analysis_id}", response_model=AnalysisSummary)
def get_analysis(analysis_id: uuid.UUID, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    analysis = db.get(Analysis, analysis_id)
    if analysis is None or analysis.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analiz bulunamadi.")
    return analysis


@router.get("/{analysis_id}/status")
def get_analysis_status(analysis_id: uuid.UUID, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    analysis = db.get(Analysis, analysis_id)
    if analysis is None or analysis.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analiz bulunamadi.")
    return {"id": str(analysis.id), "status": analysis.status}


@router.get("/{analysis_id}/report", response_model=AnalysisReportResponse)
def get_analysis_report(analysis_id: uuid.UUID, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    analysis = db.get(Analysis, analysis_id)
    if analysis is None or analysis.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analiz bulunamadi.")
    return analysis


@router.get(
    "/{analysis_id}/pdf",
    response_class=Response,
    responses={
        200: {"content": {"application/pdf": {}}},
        404: {"description": "Analiz bulunamadi (yok veya baska kullaniciya ait)."},
        409: {"description": "Analiz henuz tamamlanmadi."},
        422: {"description": "Analiz basarisiz; rapor uretilemez."},
    },
)
def get_analysis_pdf(analysis_id: uuid.UUID, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    analysis = db.get(Analysis, analysis_id)
    if analysis is None or analysis.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analiz bulunamadi.")
    if analysis.status == "failed":
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Analiz basarisiz oldu; rapor uretilemez.")
    if analysis.status != "completed":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Rapor henuz hazir degil.")

    return Response(
        content=render_pdf(analysis),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="acaturk_analysis_{analysis.id}.pdf"'},
    )
