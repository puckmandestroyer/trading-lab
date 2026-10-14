"""Bounded unauthenticated Bybit Spot time/Kline reads for the runtime gate.

The frozen historical loader remains independent: its float64 schema, local
clock check and raw diagnostics cannot establish this gate's exact contract.
We reuse its fixed Kline endpoint and backward pagination direction, without
changing historical APIs. No authenticated session or arbitrary URL is accepted.
"""

from decimal import Decimal, InvalidOperation
import re

import requests

from trading_lab.data.closed_candles import (
    INTERVAL_MS, MAX_CANDLES, MAX_TIME_MS, ClosedCandlePrefix, MarketCandle,
    MarketCandlePage, MarketDataContinuityError, MarketDataInputError,
    MarketDataIntegrityError, MarketDataReadFailureKind, MarketDataResponseError,
    MarketDataTransportError,
    _context, _time, validate_candle_freshness,
    validate_closed_prefix,
)
from trading_lab.exchange.bybit_market_data import KLINE_URL


SERVER_TIME_URL = "https://api.bybit.com/v5/market/time"
_TRANSIENT_TRANSPORT_ERRORS = (
    TimeoutError, ConnectionError, requests.exceptions.Timeout, requests.exceptions.ConnectionError,
)


def _result(payload):
    if (not isinstance(payload, dict) or not isinstance(payload.get("retCode"), int)
            or isinstance(payload["retCode"], bool)):
        raise MarketDataResponseError("Public response is missing a valid success code.")
    if payload["retCode"] != 0:
        raise MarketDataTransportError("Bybit rejected the public market read.")
    if not isinstance(payload.get("result"), dict):
        raise MarketDataResponseError("Public response is missing its result object.")
    return payload["result"]


def _digits(value, *, maximum):
    if (not isinstance(value, str) or len(value) > 32
            or re.fullmatch(r"[0-9]+", value) is None):
        raise MarketDataResponseError("Public timestamp must be an unsigned integer string.")
    number = int(value)
    if number > maximum:
        raise MarketDataResponseError("Public timestamp exceeds the supported range.")
    return number


def _response_time(payload):
    try:
        return _time(payload.get("time"))
    except MarketDataInputError:
        raise MarketDataResponseError("Public response is missing valid UTC millisecond time.") from None


def normalize_server_time(payload) -> int:
    """Use documented timeNano // 1,000,000; cross-check seconds and envelope ms.

    Flooring nanoseconds is conservative at the close boundary. Contradictory
    representations fail without falling back to any local wall clock.
    """
    result = _result(payload)
    nano = _digits(result.get("timeNano"), maximum=MAX_TIME_MS * 1_000_000 + 999_999)
    second = _digits(result.get("timeSecond"), maximum=MAX_TIME_MS // 1000)
    ms = nano // 1_000_000
    if second != nano // 1_000_000_000 or _response_time(payload) != ms:
        raise MarketDataResponseError("Public server-time representations contradict each other.")
    return ms


def _decimal(value):
    # Bybit returns plain decimal strings. Limit representation size before
    # parsing; reject whitespace, exponent notation, float coercion and NaN.
    if (not isinstance(value, str) or len(value) > 4096
            or re.fullmatch(r"-?[0-9]+(?:\.[0-9]+)?", value) is None):
        raise MarketDataResponseError("Public candle contains an invalid decimal string.")
    try:
        return Decimal(value)
    except InvalidOperation:
        raise MarketDataResponseError("Public candle contains an invalid decimal value.") from None


def normalize_public_klines(payload, *, symbol: str, timeframe: str = "60") -> MarketCandlePage:
    """Validate seven-string rows, deduplicate identical OHLCV, sort ascending.

    Bybit documents no interval echo: the explicit request context owns it.
    An optional echo must agree. Turnover is checked as finite/nonnegative but
    omitted from our OHLCV model; it is not part of accepted candle identity.
    """
    _context(symbol, timeframe)
    result = _result(payload)
    if (result.get("category") != "spot" or result.get("symbol") != symbol
            or ("interval" in result and result["interval"] != timeframe)):
        raise MarketDataResponseError("Public Kline response has unexpected market context.")
    rows = result.get("list")
    if not isinstance(rows, list) or len(rows) > 1000:
        raise MarketDataResponseError("Public Kline response must contain a bounded row list.")
    unique = {}
    for row in rows:
        if not isinstance(row, list) or len(row) != 7:
            raise MarketDataResponseError("Public Kline row must contain exactly seven fields.")
        timestamp = _digits(row[0], maximum=MAX_TIME_MS - INTERVAL_MS)
        values = [_decimal(value) for value in row[1:]]
        if values[-1] < 0:
            raise MarketDataIntegrityError("Public Kline turnover cannot be negative.")
        try:
            candle = MarketCandle(symbol, timeframe, timestamp, *values[:5])
        except MarketDataInputError:
            raise MarketDataResponseError("Public candle timestamp is not on the UTC hourly grid.") from None
        previous = unique.get(timestamp)
        if previous is not None and previous != candle:
            raise MarketDataIntegrityError("Conflicting duplicate public candle.")
        unique[timestamp] = candle
    return MarketCandlePage(symbol, timeframe, _response_time(payload), tuple(unique[t] for t in sorted(unique)))


class BybitPublicMarketReader:
    """One bounded public read operation per call; no retries, sleeps or state.

    Sessions are created internally without environment/netrc authentication or
    proxy settings. Redirects are refused; only the two fixed public GET URLs
    are reachable. timeout_seconds is a per-request timeout, not a scheduler.
    """

    def __init__(self, *, timeout_seconds: float = 10.0):
        if (isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float))
                or not 0 < timeout_seconds <= 30):
            raise MarketDataInputError("Public request timeout must be finite and within (0, 30] seconds.")
        self._timeout_seconds = timeout_seconds

    def _read(self, session, *, time_request=False, params=None):
        url = SERVER_TIME_URL if time_request else KLINE_URL
        failure = None
        try:
            response = session.get(url, params=params, timeout=self._timeout_seconds, allow_redirects=False)
        except _TRANSIENT_TRANSPORT_ERRORS:
            failure = MarketDataTransportError("Public market connection/timeout failed.",
                                               kind=MarketDataReadFailureKind.TRANSIENT)
        except Exception:
            failure = MarketDataTransportError("Public market transport failed.")
        # Raise outside the external handler so neither cause nor context keeps
        # the original request/exception. Only verified send failures are transient.
        if failure is not None:
            raise failure from None
        try:
            if response.status_code != 200:
                failure = MarketDataTransportError("Public market HTTP read failed or redirected.")
            else:
                return response.json()
        except ValueError:
            failure = MarketDataResponseError("Public market response is not valid JSON.")
        except Exception:
            failure = MarketDataTransportError("Public market response read failed.")
        raise failure from None

    @staticmethod
    def _public_session():
        session = requests.Session()
        session.trust_env = False
        session.auth = None
        return session

    def get_server_time(self) -> int:
        with self._public_session() as session:
            return normalize_server_time(self._read(session, time_request=True))

    def get_closed_candles(
        self, *, symbol: str, history_anchor_ms: int, max_data_age_ms: int,
        timeframe: str = "60", end_ms: int | None = None,
        page_limit: int = 1000, max_pages: int = 100,
    ) -> ClosedCandlePrefix:
        """Read complete anchored history or fail; never return partial success.

        Server time is sampled BEFORE candle reads so any just-closing candle
        is conservatively excluded. Each page's server timestamp must be at
        least that sample. Freshness uses the latest page timestamp, accounting
        for elapsed pagination without consulting a local clock.
        """
        _context(symbol, timeframe)
        _time(history_anchor_ms, grid=True)
        _time(max_data_age_ms)
        if end_ms is not None:
            _time(end_ms, grid=True)
            if end_ms <= history_anchor_ms:
                raise MarketDataInputError("Requested history end must follow its anchor.")
        for value, maximum in ((page_limit, 1000), (max_pages, 100)):
            if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= maximum:
                raise MarketDataInputError("Invalid public pagination bound.")
        with self._public_session() as session:
            server_ms = normalize_server_time(self._read(session, time_request=True))
            stop = server_ms // INTERVAL_MS * INTERVAL_MS if end_ms is None else end_ms
            if stop > server_ms:
                raise MarketDataInputError("Requested history includes an unclosed hour.")
            count = (stop - history_anchor_ms) // INTERVAL_MS
            if count <= 0:
                raise MarketDataContinuityError("No closed history is available at the requested anchor.")
            if count > min(MAX_CANDLES, page_limit * max_pages):
                raise MarketDataInputError("Requested history exceeds the configured pagination capacity.")
            # The default request may include the forming candle. It is parsed
            # and checked but never delivered as part of the closed prefix.
            cursor = server_ms if end_ms is None else stop - 1
            initial_cursor = cursor
            collected = {}
            observed_ms = server_ms
            for _ in range(max_pages):
                payload = self._read(session, params={
                    "category": "spot", "symbol": symbol, "interval": timeframe,
                    "start": history_anchor_ms, "end": cursor, "limit": page_limit,
                })
                page = normalize_public_klines(payload, symbol=symbol, timeframe=timeframe)
                if len(payload["result"]["list"]) > page_limit:
                    raise MarketDataResponseError("Public page exceeds the requested row limit.")
                if page.observed_at_ms < observed_ms:
                    raise MarketDataIntegrityError("Public page observation time regressed.")
                observed_ms = page.observed_at_ms
                if not page.candles:
                    raise MarketDataContinuityError("Public history ended before full anchor coverage.")
                for candle in page.candles:
                    timestamp = candle.candle_open_ms
                    previous = collected.get(timestamp)
                    if previous is not None and previous != candle:
                        raise MarketDataIntegrityError("Conflicting public candle overlap across pages.")
                    if (timestamp < history_anchor_ms or timestamp > initial_cursor
                            or (timestamp > cursor and previous is None)):
                        raise MarketDataIntegrityError("Public page contains an unexpected out-of-range candle.")
                    collected[timestamp] = candle
                oldest = page.candles[0].candle_open_ms
                if oldest > cursor:
                    raise MarketDataContinuityError("Public pagination did not make backward progress.")
                cursor = oldest - 1
                if oldest == history_anchor_ms:
                    prefix = validate_closed_prefix(
                        tuple(collected[t] for t in sorted(collected)), symbol=symbol,
                        history_anchor_ms=history_anchor_ms, timeframe=timeframe,
                        server_time_ms=server_ms, end_ms=stop, observed_at_ms=observed_ms,
                    )
                    validate_candle_freshness(
                        newest_closed_candle_open_ms=prefix.candles[-1].candle_open_ms,
                        server_time_ms=observed_ms, max_data_age_ms=max_data_age_ms,
                    )
                    return prefix
            raise MarketDataContinuityError("Public history exceeded the configured page budget.")
