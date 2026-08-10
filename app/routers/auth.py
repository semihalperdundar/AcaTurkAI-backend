"""
Spec Bolum 15 - Authentication endpoint'leri.

Bu iskelette implemente edilenler:
  POST /api/auth/register
  POST /api/auth/login
  GET  /api/auth/me

Henuz stub olanlar (Ay 1 sonunda gercek client ID ile tamamlanacak):
  POST /api/auth/logout   (JWT stateless oldugu icin sunucu tarafinda islem gerekmiyor;
                            gercek implementasyonda refresh token blacklist eklenebilir)
  POST /api/auth/refresh
  POST /api/auth/google
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.routers.deps import get_current_user
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserResponse
from app.services.auth_service import AuthError, authenticate_user, issue_token_for, register_user

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    try:
        user = register_user(db, payload)
    except AuthError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return user


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    try:
        user = authenticate_user(db, payload.email, payload.password)
    except AuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    return TokenResponse(access_token=issue_token_for(user))


@router.get("/me", response_model=UserResponse)
def me(current_user=Depends(get_current_user)):
    return current_user


@router.post("/google", status_code=status.HTTP_501_NOT_IMPLEMENTED)
def google_oauth():
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Google OAuth henuz baglanmadi — GOOGLE_CLIENT_ID/SECRET .env'e girildikten sonra implemente edilecek.",
    )
