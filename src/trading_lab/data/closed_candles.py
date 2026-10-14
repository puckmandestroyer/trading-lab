"""Pure hourly market observations; no strategy, clock, broker or storage I/O."""

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
import re


INTERVAL_MS = 3_600_000
MAX_TIME_MS = 2**63 - 1
MAX_CANDLES = 100_000


class MarketDataError(RuntimeError):
    """Safe public market-data failure, without external payloads."""


class MarketDataInputError(MarketDataError):
    """Invalid caller configuration or explicit time input."""


class MarketDataReadFailureKind(str, Enum):
    """Public read-failure facts; retry policy belongs to the runtime."""

    TRANSIENT = "TRANSIENT"
    PERMANENT = "PERMANENT"


class MarketDataTransportError(MarketDataError):
    """A sanitized HTTP/API failure; unclassified failures default permanent."""

    __slots__ = ("_kind",)

    def __init__(self, message="Public market read failed.", *, kind=MarketDataReadFailureKind.PERMANENT):
        if not isinstance(kind, MarketDataReadFailureKind):
            raise TypeError("An explicit MarketDataReadFailureKind is required.")
        if hasattr(self, "_kind"):
            raise AttributeError("Market read failure classification is immutable.")
        object.__setattr__(self, "_kind", kind)
        super().__init__(message)

    @property
    def kind(self) -> MarketDataReadFailureKind:
        return self._kind

    def __setattr__(self, name, value):
        if name in ("kind", "_kind"):
            raise AttributeError("Market read failure classification is immutable.")
        super().__setattr__(name, value)

    def __delattr__(self, name):
        if name in ("kind", "_kind"):
            raise AttributeError("Market read failure classification is immutable.")
        super().__delattr__(name)


class MarketDataResponseError(MarketDataError):
    """A public response cannot be interpreted safely."""


class MarketDataIntegrityError(MarketDataError):
    """Malformed or conflicting normalized candle facts."""


class MarketDataContinuityError(MarketDataIntegrityError):
    """Requested hourly history is incomplete or pagination did not progress."""


class StaleMarketDataError(MarketDataError):
    """The newest requested closed candle exceeds the explicit age limit."""


def _time(value, *, grid=False):
    if (type(value) is not int
            or not 0 <= value <= MAX_TIME_MS
            or (grid and (value % INTERVAL_MS or value > MAX_TIME_MS - INTERVAL_MS))):
        raise MarketDataInputError("Expected valid integer UTC milliseconds on the required grid.")
    return value


def _context(symbol, timeframe):
    if (not isinstance(symbol, str) or re.fullmatch(r"[A-Z0-9]{1,32}", symbol) is None
            or timeframe != "60" or not isinstance(timeframe, str)):
        raise MarketDataInputError("Expected an uppercase ASCII symbol and hourly timeframe 60.")


def _amount(value, *, positive=False):
    if (not isinstance(value, Decimal) or not value.is_finite()
            or (value != 0 and len(value.as_tuple().digits) + abs(value.as_tuple().exponent) + 3 > 4096)
            or value < 0 or (positive and value == 0)):
        raise MarketDataIntegrityError("Expected bounded finite Decimal OHLCV values with valid signs.")


@dataclass(frozen=True, slots=True)
class MarketCandle:
    """Exact public OHLCV facts with the same identity/bounds as durable candles.

    Unlike runtime.store.CandleRecord, this observation has no persistence
    fingerprint. Keeping it separate avoids importing SQLite into the feed.
    """

    symbol: str
    timeframe: str
    candle_open_ms: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal

    def __post_init__(self):
        _context(self.symbol, self.timeframe)
        _time(self.candle_open_ms, grid=True)
        for value in (self.open, self.high, self.low, self.close):
            _amount(value, positive=True)
        _amount(self.volume)
        if not self.low <= min(self.open, self.close) <= max(self.open, self.close) <= self.high:
            raise MarketDataIntegrityError("Candle prices violate OHLC bounds.")

    @property
    def candle_close_ms(self) -> int:
        return self.candle_open_ms + INTERVAL_MS


@dataclass(frozen=True, slots=True)
class MarketCandlePage:
    """Normalized page and its reported server observation time, never raw JSON."""

    symbol: str
    timeframe: str
    observed_at_ms: int
    candles: tuple[MarketCandle, ...]

    def __post_init__(self):
        _context(self.symbol, self.timeframe)
        _time(self.observed_at_ms)
        _validate_sequence(self.candles, self.symbol, self.timeframe)


@dataclass(frozen=True, slots=True)
class ClosedCandlePrefix:
    """Complete [anchor, end) history at an explicit closure-time snapshot.

    observed_at_ms is the latest supplied page observation, not local time.
    This record asserts coverage/closure, never strategy/action eligibility.
    """

    symbol: str
    timeframe: str
    history_anchor_ms: int
    end_ms: int
    server_time_ms: int
    observed_at_ms: int
    candles: tuple[MarketCandle, ...]

    def __post_init__(self):
        _context(self.symbol, self.timeframe)
        _time(self.history_anchor_ms, grid=True)
        _time(self.end_ms, grid=True)
        _time(self.server_time_ms)
        _time(self.observed_at_ms)
        if (self.end_ms < self.history_anchor_ms or self.end_ms > self.server_time_ms
                or self.observed_at_ms < self.server_time_ms):
            raise MarketDataInputError("History boundaries and authoritative observations disagree.")
        _validate_sequence(self.candles, self.symbol, self.timeframe)
        count = (self.end_ms - self.history_anchor_ms) // INTERVAL_MS
        if count > MAX_CANDLES or len(self.candles) != count:
            raise MarketDataContinuityError("Requested hourly prefix has missing coverage.")
        for index, candle in enumerate(self.candles):
            if candle.candle_open_ms != self.history_anchor_ms + index * INTERVAL_MS:
                raise MarketDataContinuityError("Requested hourly prefix contains a gap or boundary mismatch.")

    @property
    def data_age_ms(self) -> int | None:
        if not self.candles:
            return None
        return self.observed_at_ms - self.candles[-1].candle_close_ms


def _validate_sequence(candles, symbol, timeframe):
    if not isinstance(candles, tuple) or len(candles) > MAX_CANDLES:
        raise MarketDataIntegrityError("Expected a bounded immutable candle sequence.")
    previous = -1
    for candle in candles:
        if (not isinstance(candle, MarketCandle) or candle.symbol != symbol
                or candle.timeframe != timeframe or candle.candle_open_ms <= previous):
            raise MarketDataIntegrityError("Candles must match context and be unique and ascending.")
        previous = candle.candle_open_ms


def validate_closed_prefix(
    candles: tuple[MarketCandle, ...], *, symbol: str, history_anchor_ms: int,
    server_time_ms: int, timeframe: str = "60", end_ms: int | None = None,
    observed_at_ms: int | None = None,
) -> ClosedCandlePrefix:
    """Exclude unfinished candles, then require every hour in [anchor, end).

    Equality closes a candle: server_time_ms >= open_ms + INTERVAL_MS.
    Only broker normalization may sort/deduplicate; this function rejects
    unordered/duplicate normalized inputs. No missing hour is manufactured.
    """
    _context(symbol, timeframe)
    _time(history_anchor_ms, grid=True)
    _time(server_time_ms)
    if end_ms is None:
        end_ms = server_time_ms // INTERVAL_MS * INTERVAL_MS
    _time(end_ms, grid=True)
    _validate_sequence(candles, symbol, timeframe)
    closed = []
    for candle in candles:
        if candle.candle_close_ms <= server_time_ms:
            if not history_anchor_ms <= candle.candle_open_ms < end_ms:
                raise MarketDataIntegrityError("Closed candle lies outside the requested history.")
            closed.append(candle)
    return ClosedCandlePrefix(
        symbol, timeframe, history_anchor_ms, end_ms, server_time_ms,
        server_time_ms if observed_at_ms is None else observed_at_ms, tuple(closed),
    )


def validate_candle_freshness(
    *, newest_closed_candle_open_ms: int, server_time_ms: int, max_data_age_ms: int,
) -> int:
    """Return age = server time - newest close; accept age <= explicit limit.

    A forming candle is invalid, rather than fresh with a negative age.
    The caller supplies its configured limit; there is no default health bound.
    """
    _time(newest_closed_candle_open_ms, grid=True)
    _time(server_time_ms)
    _time(max_data_age_ms)
    age = server_time_ms - (newest_closed_candle_open_ms + INTERVAL_MS)
    if age < 0:
        raise MarketDataInputError("Freshness requires an already closed candle.")
    if age > max_data_age_ms:
        raise StaleMarketDataError("Newest closed candle exceeds the configured data age.")
    return age
