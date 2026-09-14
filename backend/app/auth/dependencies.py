from functools import lru_cache
from typing import Annotated, Protocol

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth.models import AuthenticatedUser
from app.auth.verifier import (
    AuthenticationError,
    AuthenticationServiceUnavailableError,
    SupabaseTokenVerifier,
)
from app.core.config import get_settings

bearer_scheme = HTTPBearer(auto_error=False)


class TokenVerifier(Protocol):
    async def verify(self, token: str) -> AuthenticatedUser: ...


class UnavailableTokenVerifier:
    async def verify(self, token: str) -> AuthenticatedUser:
        del token
        raise AuthenticationServiceUnavailableError


@lru_cache
def get_token_verifier() -> TokenVerifier:
    settings = get_settings()
    if settings.supabase_url is None or not settings.supabase_publishable_key:
        return UnavailableTokenVerifier()

    return SupabaseTokenVerifier(
        supabase_url=str(settings.supabase_url),
        publishable_key=settings.supabase_publishable_key,
    )


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    verifier: Annotated[TokenVerifier, Depends(get_token_verifier)],
) -> AuthenticatedUser:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        return await verifier.verify(credentials.credentials)
    except AuthenticationError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from error
    except AuthenticationServiceUnavailableError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service is temporarily unavailable",
        ) from error
