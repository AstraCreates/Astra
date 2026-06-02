"""Fetch and cache the daily gold spot price (USD/troy oz).

Used to peg credit cost to gold: credits = tokens / (gold_price / 1000)
"""
from __future__ import annotations
import json
import logging
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_FALLBACK_PRICE = 3300.0  # USD/oz fallback if fetch fails
_CACHE_TTL = 3600 * 6     # refresh every 6 hours
_cache_lock = threading.Lock()
_cache: dict = {}          # {"price": float, "fetched_at": float}


def _fetch_price() -> float:
    """Fetch gold spot price from a free public API."""
    import urllib.request
    # metals-api free tier / exchangerate-api gold endpoint
    urls = [
        "https://data-asg.goldprice.org/dbXRates/USD",
        "https://api.metals.live/v1/spot/gold",
    ]
    for url in urls:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
            # goldprice.org format: {"items":[{"xauPrice":3280.5,...}]}
            if "items" in data and data["items"]:
                price = float(data["items"][0].get("xauPrice") or data["items"][0].get("price", 0))
                if price > 100:
                    return price
            # metals.live format: [{"gold": 3280.5}] or {"price": 3280.5}
            if isinstance(data, list) and data:
                price = float(data[0].get("gold") or data[0].get("price", 0))
                if price > 100:
                    return price
            if isinstance(data, dict) and "price" in data:
                price = float(data["price"])
                if price > 100:
                    return price
        except Exception as e:
            logger.debug("Gold price fetch failed (%s): %s", url, e)
    return 0.0


def get_gold_price() -> float:
    """Return current gold price in USD/oz, cached for 6 hours."""
    with _cache_lock:
        now = time.time()
        if _cache.get("price") and (now - _cache.get("fetched_at", 0)) < _CACHE_TTL:
            return _cache["price"]

    price = _fetch_price()
    if price <= 0:
        price = _FALLBACK_PRICE
        logger.warning("Gold price fetch failed — using fallback $%.0f/oz", price)
    else:
        logger.info("Gold price: $%.2f/oz", price)

    with _cache_lock:
        _cache["price"] = price
        _cache["fetched_at"] = time.time()

    return price


def tokens_to_credits(tokens: int) -> int:
    """Convert token count to credits using live gold price.

    Formula: credits = tokens / (gold_price / 1000)
    At $3000/oz: 1000 tokens = 333 credits
    At $2000/oz: 1000 tokens = 500 credits
    """
    gold = get_gold_price()
    divisor = gold / 1000.0
    return max(1, round(tokens / divisor))
