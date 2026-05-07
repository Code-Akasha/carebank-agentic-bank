from __future__ import annotations

from dataclasses import dataclass

import jwt
from fastapi import HTTPException, Request, status

from .config import get_settings


@dataclass(frozen=True)
class TokenPayload:
    user_id: str
    role: str


def _extract_token(request: Request) -> str:
    header = request.headers.get("Authorization", "").strip()
    if not header or not header.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
        )
    return header.split(" ", 1)[1].strip()


def verify_request_token(request: Request) -> TokenPayload:
    settings = get_settings()
    if not settings.banking_api_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="BANKING_API_SECRET is not configured",
        )

    token = _extract_token(request)
    try:
        payload = jwt.decode(
            token, settings.banking_api_secret, algorithms=["HS256"]
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        ) from exc

    user_id = str(payload.get("user_id") or "").strip()
    role = str(payload.get("role") or "user").strip().lower()
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing user_id",
        )
    return TokenPayload(user_id=user_id, role=role)
