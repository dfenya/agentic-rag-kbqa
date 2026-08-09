from pydantic import BaseModel, Field


class RegisterRequest(BaseModel):
    username: str = Field(min_length=11, max_length=11, pattern=r"^1[3-9]\d{9}$")
    password: str = Field(min_length=6, max_length=128)


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    username: str
