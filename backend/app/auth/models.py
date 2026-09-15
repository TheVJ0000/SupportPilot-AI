from dataclasses import dataclass, field
from uuid import UUID

from pydantic import BaseModel


class AuthenticatedUser(BaseModel):
    """Verified identity exposed to application code."""

    user_id: UUID
    email: str | None = None


@dataclass(frozen=True)
class AuthenticatedRequestContext:
    """Verified identity plus a request-scoped token that is never serialized or logged."""

    user: AuthenticatedUser
    access_token: str = field(repr=False)
