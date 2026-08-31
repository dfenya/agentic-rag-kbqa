import jwt
from datetime import datetime, timezone, timedelta
from passlib.context import CryptContext

from app.stores.sqlite_store import SqliteStore
from app.domain.models import User
from app.core.config import Settings, get_settings

# 新密码用 bcrypt_sha256，避免 bcrypt 的 72-byte 限制；仍可验证已有 bcrypt 哈希。
pwd_context = CryptContext(schemes=["bcrypt_sha256", "bcrypt"], deprecated="auto")

ALGORITHM = "HS256"


class AuthService:

    def __init__(self, sqlite: SqliteStore, settings: Settings):
        self._db = sqlite
        self._settings = settings

    def register(self, username: str, password: str) -> User:
        existing = self._db.user_by_username(username)
        if existing:
            raise ValueError("用户名已存在")
        return self._db.user_create(
            username=username,
            password_hash=pwd_context.hash(password),
        )

    def login(self, username: str, password: str) -> str:
        user = self._db.user_by_username(username)
        if not user or not pwd_context.verify(password, user.password_hash):
            raise ValueError("用户名或密码错误")
        return _create_token(user.id, user.username, self._settings)

    def get_user(self, user_id: str) -> User | None:
        return self._db.user_by_id(user_id)

    def get_user_by_username(self, username: str) -> User | None:
        return self._db.user_by_username(username)


def _create_token(user_id: str, username: str, settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    payload = {
        "sub": user_id,
        "username": username,
        "exp": datetime.now(timezone.utc) + timedelta(hours=settings.auth.token_expire_hours),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.auth.jwt_secret, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    return jwt.decode(token, get_settings().auth.jwt_secret, algorithms=[ALGORITHM])
