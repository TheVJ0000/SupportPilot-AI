from uuid import UUID

from pydantic import BaseModel


class AuthenticatedUser(BaseModel):
    """Verified identity exposed to application code."""

    user_id: UUID
    email: str | None = None
