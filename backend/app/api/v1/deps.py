from fastapi import Request, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.services.auth_service import decode_token

security = HTTPBearer()


def get_container(request: Request):
    return request.app.state.container


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> str:
    try:
        payload = decode_token(credentials.credentials)
        user_id = payload["sub"]
    except Exception:
        raise HTTPException(status_code=401, detail="无效的认证令牌")

    user = request.app.state.container.auth_service.get_user(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在")

    return user_id
