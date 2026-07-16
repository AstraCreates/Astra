"""Regression test: pdf_generator._safe() silently corrupted non-Latin-1 currency
symbols (Euro, Rupee) to "?" via latin-1 errors="replace" -- garbled currency in
investor-facing PDFs (finance_model/finance_fundraise research routinely surfaces
Euro-denominated comps)."""
from backend.tools.pdf_generator import _safe


def test_euro_and_rupee_symbols_survive_as_ascii_codes():
    assert _safe("€50M pre-money") == "EUR50M pre-money"
    assert _safe("₹5Cr ARR") == "INR5Cr ARR"


def test_pound_and_yen_still_pass_through_unchanged():
    # These are within Latin-1's 0-255 range already -- no mapping needed.
    assert _safe("£50M") == "£50M"
    assert _safe("¥5B") == "¥5B"
