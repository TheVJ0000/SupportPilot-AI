import asyncio
from typing import Any, Protocol
from uuid import UUID

import httpx
import jwt
from jwt import PyJWKClient
from jwt.exceptions import InvalidTokenError, PyJWKClientConnectionError, PyJWKClientError

from app.auth.models import AuthenticatedUser

ASYMMETRIC_ALGORITHMS = ("ES256", "RS256")
LEGACY_ALGORITHM = "HS256"


class AuthenticationError(Exception):
    """The supplied credential cannot be trusted."""


class AuthenticationServiceUnavailableError(Exception):
    """The configured identity provider cannot currently validate credentials."""


class SigningKeyClient(Protocol):
    def get_signing_key_from_jwt(self, token: str) -> Any: ...


class SupabaseTokenVerifier:
    """Validate Supabase access tokens without storing any JWT signing secret."""

    def __init__(
        self,
        supabase_url: str,
        publishable_key: str,
        signing_key_client: SigningKeyClient | None = None,
    ) -> None:
        self._supabase_url = supabase_url.rstrip("/")
        self._issuer = f"{self._supabase_url}/auth/v1"
        self._jwks_url = f"{self._issuer}/.well-known/jwks.json"
        self._user_url = f"{self._issuer}/user"
        self._publishable_key = publishable_key
        self._signing_keys = signing_key_client or PyJWKClient(
            self._jwks_url,
            cache_jwk_set=True,
            cache_keys=True,
            lifespan=600,
            timeout=5,
        )

    async def verify(self, token: str) -> AuthenticatedUser:
        try:
            algorithm = jwt.get_unverified_header(token).get("alg")
        except InvalidTokenError as error:
            raise AuthenticationError from error

        if algorithm in ASYMMETRIC_ALGORITHMS:
            return await asyncio.to_thread(self._verify_asymmetric, token)

        if algorithm == LEGACY_ALGORITHM:
            return await self._verify_with_auth_server(token)

        raise AuthenticationError

    def _verify_asymmetric(self, token: str) -> AuthenticatedUser:
        try:
            signing_key = self._signing_keys.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=list(ASYMMETRIC_ALGORITHMS),
                audience="authenticated",
                issuer=self._issuer,
                options={"require": ["exp", "iss", "aud", "sub"]},
            )
        except PyJWKClientConnectionError as error:
            raise AuthenticationServiceUnavailableError from error
        except (
            InvalidTokenError,
            PyJWKClientError,
            AttributeError,
            TypeError,
            OverflowError,
        ) as error:
            raise AuthenticationError from error

        return self._identity_from_claims(claims)

    async def _verify_with_auth_server(self, token: str) -> AuthenticatedUser:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.get(
                    self._user_url,
                    headers={
                        "apikey": self._publishable_key,
                        "Authorization": f"Bearer {token}",
                    },
                )
        except httpx.RequestError as error:
            raise AuthenticationServiceUnavailableError from error

        if response.status_code in {401, 403}:
            raise AuthenticationError
        if response.status_code != 200:
            raise AuthenticationServiceUnavailableError

        try:
            user_data = response.json()
        except ValueError as error:
            raise AuthenticationServiceUnavailableError from error
        if not isinstance(user_data, dict):
            raise AuthenticationServiceUnavailableError
        # The Auth server above verifies the HS256 signature. Only after its
        # success, independently enforce our business issuer/audience/expiry and
        # bind the signed subject to the server-verified identity. Never use
        # unverified decoding alone as authorization.
        try:
            claims = jwt.decode(
                token,
                algorithms=[LEGACY_ALGORITHM],
                audience="authenticated",
                issuer=self._issuer,
                options={
                    "verify_signature": False,
                    "verify_exp": True,
                    "verify_aud": True,
                    "verify_iss": True,
                    "verify_sub": True,
                    "require": ["exp", "iss", "aud", "sub"],
                },
            )
        except (InvalidTokenError, TypeError, OverflowError) as error:
            raise AuthenticationError from error
        identity = self._identity_from_claims(
            {"sub": user_data.get("id"), "email": user_data.get("email")}
        )
        if self._identity_from_claims(claims).user_id != identity.user_id:
            raise AuthenticationError
        return identity

    @staticmethod
    def _identity_from_claims(claims: dict[str, Any]) -> AuthenticatedUser:
        try:
            user_id = UUID(str(claims["sub"]))
        except (KeyError, TypeError, ValueError) as error:
            raise AuthenticationError from error

        email = claims.get("email")
        if email is not None and not isinstance(email, str):
            raise AuthenticationError

        return AuthenticatedUser(user_id=user_id, email=email)
