import asyncio
import uuid
from typing import Annotated

from fastapi import Depends, Header, HTTPException

from config import MAX_SESSIONS
from services import store
from services.pipeline import JOBS


def _session_id(x_session_id: Annotated[str | None, Header()] = None) -> str:
    """The X-Session-Id header names this user's Qdrant collection, so it must be a real UUID."""
    if not x_session_id:
        raise HTTPException(400, "Missing X-Session-Id header.")
    try:
        return str(uuid.UUID(x_session_id))
    except ValueError:
        raise HTTPException(400, "X-Session-Id must be a UUID.")


Session = Annotated[str, Depends(_session_id)]


_recent: dict[str, None] = {}  # sessions with a document on this instance, least recently used first


async def keep(session: str) -> None:
    """Mark the session as just used, and drop the least recently used ones beyond MAX_SESSIONS.

    shortcut: each instance holds at most MAX_SESSIONS documents in memory and an evicted user sees
    "session expired"; move to a shared vector store when one instance must serve more.
    """
    _recent.pop(session, None)
    _recent[session] = None
    while len(_recent) > MAX_SESSIONS:
        old = next(iter(_recent))
        del _recent[old]
        for job in [j for j in JOBS.values() if j.session_id == old]:
            if job.task and not job.task.done():
                job.task.cancel()
            del JOBS[job.id]
        await asyncio.to_thread(store.delete_collection, old)
