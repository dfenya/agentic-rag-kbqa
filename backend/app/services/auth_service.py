import jwt
from datetime import datetime, timezone, timedelta
from passlib.context import CryptContext

from app.stores.sqlite_store import SqliteStore
from app.domain.models import User

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

SECRET_KEY = "change-me-in-production-use-env-var"
ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 72


class AuthService:

    def __init__(self, sqlite: SqliteStore):
        self._db = sqlite

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
        return _create_token(user.id, user.username)

    def get_user(self, user_id: str) -> User | None:
        return self._db.user_by_id(user_id)

    def get_user_by_username(self, username: str) -> User | None:
        return self._db.user_by_username(username)


def _create_token(user_id: str, username: str) -> str:
    payload = {
        "sub": user_id,
        "username": username,
        "exp": datetime.now(timezone.utc) + timedelta(hours=TOKEN_EXPIRE_HOURS),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
