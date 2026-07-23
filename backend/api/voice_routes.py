"""Cheap voice utilities for Astra.

This is intentionally not a realtime voice-agent surface. It is a small
speech-to-text bridge so the frontend can route a spoken utterance through the
normal Copilot APIs.
"""
from __future__ import annotations

import base64
import os
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from backend.config import settings
from backend.tenant_auth import require_founder_access

router = APIRouter(prefix="/voice", tags=["voice"])

_AUDIO_SUFFIXES = {
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/mp4": ".mp4",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/webm": ".webm",
    "audio/ogg": ".ogg",
    "audio/flac": ".flac",
    "video/mp4": ".mp4",
}


class TranscribeAudioBody(BaseModel):
    founder_id: str
    filename: str = Field(default="speech.webm", max_length=240)
    mime: str = Field(default="audio/webm", max_length=120)
    data_base64: str = Field(min_length=1)
    language: str | None = Field(default=None, max_length=16)
    prompt: str | None = Field(default=None, max_length=2_000)
    model: str | None = Field(default=None, max_length=80)


def _suffix(filename: str, mime: str) -> str:
    guessed = Path(filename or "").suffix.lower()
    if guessed in {".flac", ".m4a", ".mp3", ".mp4", ".mpeg", ".mpga", ".oga", ".ogg", ".wav", ".webm"}:
        return guessed
    return _AUDIO_SUFFIXES.get((mime or "").split(";", 1)[0].strip().lower(), ".webm")


def _extract_text(transcription: Any) -> str:
    if isinstance(transcription, str):
        return transcription.strip()
    text = getattr(transcription, "text", None)
    if text is not None:
        return str(text).strip()
    if isinstance(transcription, dict):
        return str(transcription.get("text") or "").strip()
    return str(transcription or "").strip()


@router.post("/transcribe")
async def transcribe_audio(body: TranscribeAudioBody, request: Request):
    require_founder_access(request, body.founder_id, min_role="operator")

    try:
        audio = base64.b64decode(body.data_base64, validate=True)
    except Exception as exc:
        raise HTTPException(status_code=422, detail="data_base64 must be valid base64 audio") from exc

    max_bytes = int(settings.voice_transcription_max_bytes or 0) or 25 * 1024 * 1024
    if len(audio) > max_bytes:
        raise HTTPException(status_code=413, detail=f"Audio file exceeds {max_bytes} bytes")

    api_key = settings.openai_api_key or os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY is not configured")

    model = (body.model or settings.voice_transcription_model or "whisper-1").strip()
    kwargs: dict[str, Any] = {"model": model, "response_format": "text"}
    if body.language:
        kwargs["language"] = body.language.strip()
    if body.prompt:
        kwargs["prompt"] = body.prompt

    tmp_name = ""
    try:
        from openai import OpenAI

        with tempfile.NamedTemporaryFile(suffix=_suffix(body.filename, body.mime), delete=False) as tmp:
            tmp.write(audio)
            tmp_name = tmp.name

        client = OpenAI(api_key=api_key)
        with open(tmp_name, "rb") as fh:
            transcription = client.audio.transcriptions.create(file=fh, **kwargs)
        text = _extract_text(transcription)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Transcription failed: {exc}") from exc
    finally:
        if tmp_name:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass

    return {
        "ok": True,
        "filename": body.filename,
        "mime": body.mime,
        "model": model,
        "text": text,
        "size_bytes": len(audio),
    }
