import uuid

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    full_name: str | None = None
    # spec Bolum 3.2: kayit sirasinda alan secimi zorunlu
    primary_field: str = Field(
        description="education | social_sciences | engineering | health | law | business | other"
    )


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: uuid.UUID
    email: EmailStr
    full_name: str | None = None
    primary_field: str | None = None
    subscription_tier: str

    model_config = {"from_attributes": True}
