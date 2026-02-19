"""Symbol-to-theme classifier for crypto assets (Phase 2.5)."""

from __future__ import annotations

from typing import Dict


THEME_MAP: Dict[str, str] = {
    # Majors
    "BTC": "Major",
    "ETH": "Major",
    "BNB": "Major",
    "XRP": "Major",
    "SOL": "L1",
    "ADA": "L1",
    "AVAX": "L1",
    "DOT": "L1",
    "ATOM": "L1",
    "NEAR": "L1",
    "MATIC": "L2",
    # DeFi
    "UNI": "DeFi",
    "AAVE": "DeFi",
    "MKR": "DeFi",
    "SNX": "DeFi",
    "CRV": "DeFi",
    # Infra / Oracle
    "LINK": "Infra",
    # Meme
    "DOGE": "Meme",
    "SHIB": "Meme",
    "PEPE": "Meme",
}


def classify_symbol_theme(symbol: str) -> str:
    """Classify symbol to a broad crypto theme.

    Args:
        symbol: Symbol in format BTC-USD, ETHUSDT, BTC/KRW, or BTC

    Returns:
        Theme label such as Major, L1, DeFi, Meme, Infra, or Other.
    """
    if not symbol:
        return "Other"

    s = symbol.upper().strip()
    if "-" in s:
        base = s.split("-")[0]
    elif "/" in s:
        base = s.split("/")[0]
    elif s.endswith("USDT"):
        base = s[:-4]
    elif s.endswith("KRW"):
        base = s[:-3]
    else:
        base = s

    return THEME_MAP.get(base, "Other")

