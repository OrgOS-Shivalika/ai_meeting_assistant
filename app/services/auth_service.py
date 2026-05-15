from datetime import datetime, timedelta, timezone
from jose import jwt
from passlib.context import CryptContext
from app.config.settings import settings

SECRET_KEY = settings.AUTH_SECRET_KEY
ALGORITHM = settings.ALGORITHM

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password: str):
    return pwd_context.hash(password)

def verify_password(password: str, hashed: str):
    return pwd_context.verify(password, hashed)

def create_token(data: dict):
    payload = data.copy()
    # 7-day TTL: the 1-day TTL was kicking users out every time they
    # opened a tab the next morning. The Phase 2/3/4 pipelines are
    # long-running enough that "refresh and get 401" is a real annoyance
    # — bump it. Real refresh-token flow can come later if anyone cares.
    payload["exp"] = datetime.now(timezone.utc) + timedelta(days=7)
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)