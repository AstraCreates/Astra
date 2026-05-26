import os
import subprocess
import tempfile
import time
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.api.routes import router

logger = logging.getLogger(__name__)

_CDP_PORT = 9222
_chrome_proc: subprocess.Popen | None = None


def _start_headed_chrome() -> None:
    """Launch a visible Chrome instance with remote debugging so Hermes can connect."""
    global _chrome_proc
    # Skip if already running or env already set externally
    if os.environ.get("BROWSER_CDP_URL"):
        return

    chrome_bin = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    if not os.path.exists(chrome_bin):
        logger.warning("Chrome not found at %s — Hermes will use headless fallback", chrome_bin)
        return

    user_data_dir = os.path.join(tempfile.gettempdir(), "astra-chrome-profile")
    os.makedirs(user_data_dir, exist_ok=True)

    try:
        _chrome_proc = subprocess.Popen(
            [
                chrome_bin,
                f"--remote-debugging-port={_CDP_PORT}",
                f"--user-data-dir={user_data_dir}",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-features=PrivacySandboxSettings4",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(1.5)  # let Chrome initialize
        os.environ["BROWSER_CDP_URL"] = f"http://localhost:{_CDP_PORT}"
        logger.info("Headed Chrome launched (PID %d) on CDP port %d", _chrome_proc.pid, _CDP_PORT)
    except Exception as e:
        logger.warning("Could not launch headed Chrome: %s — using headless fallback", e)


_start_headed_chrome()

app = FastAPI(title="Astra API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Type", "Cache-Control", "X-Accel-Buffering"],
)

app.include_router(router)


@app.get("/health")
async def health():
    return {"status": "ok"}
