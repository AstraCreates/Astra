"""Session ID helpers."""

import uuid


def new_session_id() -> str:
    """Return a unique run/session ID.

    Full UUID4 hex keeps every launch distinct, including repeated identical
    prompts from the same founder, without deriving identity from prompt text.
    """
    return uuid.uuid4().hex
