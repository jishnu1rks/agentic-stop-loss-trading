"""
Single shared-login gate (HTTP Basic Auth) for production deployment.
Section 9 already requires credentials to never live in the DB or
dashboard - this extends the same principle to the app itself: if
BASIC_AUTH_USERNAME/PASSWORD aren't set, auth is a no-op (local dev stays
frictionless); once set (in production), every route except /health
requires them.
"""
import secrets

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.config import settings

security = HTTPBasic(auto_error=False)


def require_auth(credentials: HTTPBasicCredentials | None = Depends(security)) -> None:
    if not settings.basic_auth_username or not settings.basic_auth_password:
        return  # auth not configured - local dev

    valid = credentials is not None and (
        secrets.compare_digest(credentials.username, settings.basic_auth_username)
        and secrets.compare_digest(credentials.password, settings.basic_auth_password)
    )
    if not valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
