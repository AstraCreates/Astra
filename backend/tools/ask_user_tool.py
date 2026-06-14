"""ask_user — let an agent pause and ask the founder a question in the UI."""
from __future__ import annotations

import uuid
from typing import Optional


async def ask_user(
    session_id: str,
    question: str,
    options: Optional[list] = None,
    hint: str = "",
    timeout: int = 300,
) -> dict:
    """Ask the founder a question and wait for their response (blocks until answered or timeout).

    question: the question text to show
    options:  optional list of choice strings — shows as buttons instead of free text
    hint:     placeholder text for free-text input
    timeout:  seconds to wait (default 300)

    Returns {"answer": str, "ok": True} or {"ok": False, "error": "timeout"}.
    """
    from backend.core.events import publish, input_response_wait

    request_id = str(uuid.uuid4())

    await publish(session_id, {
        "type": "agent_question",
        "request_id": request_id,
        "question": question,
        "options": options or [],
        "hint": hint,
    })

    response = await input_response_wait(request_id, timeout=float(timeout))
    if response is None:
        return {"ok": False, "error": "timeout — founder did not respond"}

    answer = response.get("answer", "")
    return {"ok": True, "answer": answer}
