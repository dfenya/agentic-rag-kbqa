from fastapi import APIRouter, Request, HTTPException
from app.api.v1.deps import get_container
from app.domain.auth_schemas import RegisterRequest, LoginRequest, TokenResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse)
async def register(body: RegisterRequest, request: Request):
    container = get_container(request)
    try:
        user = container.auth_service.register(body.username, body.password)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    token = container.auth_service.login(body.username, body.password)
    return TokenResponse(access_token=token, user_id=user.id, username=user.username)


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, request: Request):
    container = get_container(request)
    try:
        token = container.auth_service.login(body.username, body.password)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))
    user = container.auth_service.get_user_by_username(body.username)
    return TokenResponse(access_token=token, user_id=user.id, username=user.username)
