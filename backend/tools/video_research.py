"""YouTube and TikTok competitor content analysis via yt-dlp + youtube-transcript-api."""
from __future__ import annotations

import json
import re
import subprocess
import sys
import textwrap
from typing import Any

_VIDEO_ID_RE = re.compile(
    r"(?:youtu\.be/|youtube\.com/(?:watch\?v=|shorts/|live/|embed/))([A-Za-z0-9_-]{11})"
)
_BARE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


def _extract_video_id(url_or_id: str) -> str | None:
    url_or_id = (url_or_id or "").strip()
    if _BARE_ID_RE.match(url_or_id):
        return url_or_id
    m = _VIDEO_ID_RE.search(url_or_id)
    return m.group(1) if m else None


def _yt_dlp(*args: str) -> dict[str, Any] | list[Any] | None:
    cmd = [sys.executable, "-m", "yt_dlp", "--no-warnings", "--quiet", *args]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            return None
        return json.loads(result.stdout) if result.stdout.strip() else None
    except (subprocess.TimeoutExpired, json.JSONDecodeError, Exception):
        return None


def _fetch_transcript(video_id: str, max_chars: int | None = 4000) -> str:
    """youtube-transcript-api rewrote its API in v1.0 (static .get_transcript()
    classmethod -> instance .fetch()) and requirements.txt pins an open-ended
    >=0.6.2, so which shape is installed depends on when the image was last
    built. Try the current API first, fall back to the pre-1.0 one."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        try:
            fetched = YouTubeTranscriptApi().fetch(video_id, languages=["en", "en-US"])
            return " ".join(s.text for s in fetched)[:max_chars]
        except AttributeError:
            segments = YouTubeTranscriptApi.get_transcript(video_id, languages=["en", "en-US"])
            return " ".join(s["text"] for s in segments)[:max_chars]
    except Exception:
        return ""


def _get_transcript(video_id: str) -> str:
    return _fetch_transcript(video_id, max_chars=4000)


def youtube_get_transcript(url_or_video_id: str, max_chars: int = 30_000) -> dict[str, Any]:
    """Fetch one YouTube video's full transcript + basic metadata by URL or video ID.
    Public videos only, no login/cookies — for "summarize this video" style requests
    where youtube_research's search-and-summarize flow doesn't fit (you already have
    the exact video).

    max_chars defaults to 30,000 (~40-45 min of speech) — enough to cover most videos
    in full without every call spending tokens on a worst-case multi-hour transcript by
    default. If total_chars > max_chars, the response is marked truncated AND reports
    the true total_chars — call again with a higher max_chars only if you actually need
    the rest (e.g. the founder explicitly asked for the full transcript of a long video).
    Don't default to a huge max_chars "just in case" — that trades a real cutoff risk
    for wasting tokens on every short video too."""
    video_id = _extract_video_id(url_or_video_id)
    if not video_id:
        return {"ok": False, "error": f"Could not parse a YouTube video ID from: {url_or_video_id}"}

    full_transcript = _fetch_transcript(video_id, max_chars=None)
    if not full_transcript:
        return {
            "ok": False,
            "video_id": video_id,
            "url": f"https://youtu.be/{video_id}",
            "error": "No transcript available for this video (captions may be disabled).",
        }

    meta = _yt_dlp(f"https://youtu.be/{video_id}", "--dump-json", "--no-playlist", "--skip-download") or {}
    total_chars = len(full_transcript)
    return {
        "ok": True,
        "video_id": video_id,
        "url": f"https://youtu.be/{video_id}",
        "title": meta.get("title", ""),
        "channel": meta.get("uploader") or meta.get("channel", ""),
        "duration": _format_duration(meta.get("duration")),
        "transcript": full_transcript[:max_chars],
        "total_chars": total_chars,
        "truncated": total_chars > max_chars,
    }


def _format_duration(seconds: int | None) -> str:
    if not seconds:
        return "unknown"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h}h{m}m{s}s" if h else f"{m}m{s}s"


def youtube_research(query: str, max_results: int = 5) -> str:
    """Search YouTube for competitor/topic videos; return metadata + transcript summaries."""
    search_data = _yt_dlp(
        f"ytsearch{max_results}:{query}",
        "--dump-json",
        "--flat-playlist",
        "--no-playlist",
    )

    if not search_data:
        return f"[youtube_research] No results for: {query}"

    entries: list[dict] = []
    if isinstance(search_data, dict):
        entries = search_data.get("entries", [])
    elif isinstance(search_data, list):
        entries = search_data

    if not entries:
        # yt-dlp flat-playlist may output one JSON per line
        return f"[youtube_research] No entries parsed for: {query}"

    sections: list[str] = [f"## YouTube Research: {query}\n"]
    for entry in entries[:max_results]:
        vid_id = entry.get("id") or entry.get("display_id", "")
        title = entry.get("title", "untitled")
        channel = entry.get("uploader") or entry.get("channel", "unknown")
        views = entry.get("view_count")
        likes = entry.get("like_count")
        duration = _format_duration(entry.get("duration"))
        url = entry.get("webpage_url") or f"https://youtu.be/{vid_id}"
        description = (entry.get("description") or "")[:800]
        transcript = _get_transcript(vid_id) if vid_id else ""

        block = [
            f"### {title}",
            f"**Channel:** {channel} | **Views:** {views:,} | **Likes:** {likes} | **Duration:** {duration}" if views else f"**Channel:** {channel} | **Duration:** {duration}",
            f"**URL:** {url}",
        ]
        if description:
            block.append(f"**Description:** {description[:400]}")
        if transcript:
            block.append(f"**Transcript excerpt:**\n{textwrap.shorten(transcript, 1200, placeholder='...')}")
        sections.append("\n".join(block))

    return "\n\n".join(sections)


def tiktok_research(query: str, max_results: int = 5) -> str:
    """Search TikTok for competitor/topic videos; return metadata + captions."""
    search_data = _yt_dlp(
        f"tiktoksearch{max_results}:{query}",
        "--dump-json",
        "--flat-playlist",
        "--no-playlist",
    )

    if not search_data:
        # Fallback: hashtag search
        tag = query.replace(" ", "").lower()
        search_data = _yt_dlp(
            f"https://www.tiktok.com/tag/{tag}",
            "--dump-json",
            "--flat-playlist",
            "--playlist-items", f"1-{max_results}",
        )

    if not search_data:
        return f"[tiktok_research] No results for: {query}"

    entries: list[dict] = []
    if isinstance(search_data, dict):
        entries = search_data.get("entries", [search_data]) if "entries" in search_data else [search_data]
    elif isinstance(search_data, list):
        entries = search_data

    sections: list[str] = [f"## TikTok Research: {query}\n"]
    for entry in entries[:max_results]:
        title = entry.get("title") or entry.get("description", "untitled")
        creator = entry.get("uploader") or entry.get("creator") or entry.get("channel", "unknown")
        views = entry.get("view_count")
        likes = entry.get("like_count")
        url = entry.get("webpage_url") or entry.get("url", "")
        description = (entry.get("description") or "")[:600]
        # TikTok captions stored in subtitles/automatic_captions
        caption = ""
        subtitles = entry.get("subtitles") or entry.get("automatic_captions") or {}
        for lang_data in subtitles.values():
            if isinstance(lang_data, list) and lang_data:
                raw = lang_data[0].get("data", "") or ""
                caption = str(raw)[:1000]
                break

        block = [f"### {title[:120]}"]
        meta_parts = [f"**Creator:** {creator}"]
        if views:
            meta_parts.append(f"**Views:** {views:,}")
        if likes:
            meta_parts.append(f"**Likes:** {likes:,}")
        if url:
            meta_parts.append(f"**URL:** {url}")
        block.append(" | ".join(meta_parts))
        if description and description != title:
            block.append(f"**Caption:** {description[:400]}")
        if caption:
            block.append(f"**Subtitles excerpt:** {textwrap.shorten(caption, 600, placeholder='...')}")
        sections.append("\n".join(block))

    return "\n\n".join(sections)
