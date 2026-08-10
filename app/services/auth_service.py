"""Kayit/giris is mantigi. Router ince kalsin diye burada tutulur."""
from sqlalchemy.orm import Session

from app.core.security import hash_password, verify_password, create_access_token
from app.models.user import User
from app.schemas.auth import RegisterRequest


class AuthError(Exception):
    pass


def register_user(db: Session, data: RegisterRequest) -> User:
    existing = db.query(User).filter(User.email == data.email).first()
    if existing:
        raise AuthError("Bu e-posta ile zaten kayitli bir kullanici var.")

    user = User(
        email=data.email,
        hashed_password=hash_password(data.password),
        full_name=data.full_name,
        primary_field=data.primary_field,
        subscription_tier="free",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate_user(db: Session, email: str, password: str) -> User:
    user = db.query(User).filter(User.email == email).first()
    if not user or not user.hashed_password or not verify_password(password, user.hashed_password):
        raise AuthError("E-posta veya sifre hatali.")
    return user


def issue_token_for(user: User) -> str:
    return create_access_token(subject=str(user.id))
