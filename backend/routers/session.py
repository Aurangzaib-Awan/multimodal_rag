import uuid
from typing import Annotated

from fastapi import Depends, Header, HTTPException


def _session_id(x_session_id: Annotated[str | None, Header()] = None) -> str:
    """The X-Session-Id header names this user's Qdrant collection, so it must be a real UUID."""
    if not x_session_id:
        raise HTTPException(400, "Missing X-Session-Id header.")
    try:
        return str(uuid.UUID(x_session_id))
    except ValueError:
        raise HTTPException(400, "X-Session-Id must be a UUID.")


Session = Annotated[str, Depends(_session_id)]
