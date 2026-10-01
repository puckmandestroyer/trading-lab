"""Read public Bybit V5 candles; no credentials or trading endpoints."""

import requests


KLINE_URL = "https://api.bybit.com/v5/market/kline"


def fetch_kline_page(session, *, category, symbol, interval, start_ms, end_ms, limit=1000):
    """Fetch one page, preserving Bybit's seven-field candle arrays."""
    params = {
        "category": category,
        "symbol": symbol,
        "interval": interval,
        "start": start_ms,
        "end": end_ms,
        "limit": limit,
    }
    try:
        response = session.get(KLINE_URL, params=params, timeout=30)
        response.raise_for_status()
    except requests.RequestException as error:
        raise RuntimeError(f"Bybit public Kline request failed: {error}") from error

    try:
        payload = response.json()
    except ValueError as error:
        raise RuntimeError("Bybit returned invalid JSON for the Kline request.") from error
    if not isinstance(payload, dict) or payload.get("retCode") != 0:
        raise RuntimeError(f"Unexpected Bybit Kline response: {payload!r}")

    result = payload.get("result")
    if not isinstance(result, dict):
        raise RuntimeError("Bybit response is missing the result object.")
    if result.get("symbol") != symbol or result.get("category") != category:
        raise RuntimeError(f"Bybit returned an unexpected symbol or category: {result!r}")
    rows = result.get("list")
    if not isinstance(rows, list) or len(rows) > limit:
        raise RuntimeError("Bybit result.list must be a list within the requested page limit.")
    for row in rows:
        if not isinstance(row, list) or len(row) != 7:
            raise RuntimeError(f"Unexpected Bybit candle (expected seven fields): {row!r}")
        if not isinstance(row[0], str) or not row[0].isdigit():
            raise RuntimeError(f"Invalid Bybit candle timestamp: {row[0]!r}")
    return rows
