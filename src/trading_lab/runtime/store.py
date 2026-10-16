"""Local SQLite journal primitives under Decision 017, never orchestration.

Caller supplies validated facts and checkpoints. This layer binds references,
preserves exact money and commits related records together; it does not discover
ownership, authorize orders, or verify broker finality. Risk persistence derives
its exact book/state through the frozen pure engine, never from wallet balances.
Use RuntimeAccountLock first, then open the store; close the store before the
lock. Fresh initialization is explicit and refuses every existing file.
"""

from contextlib import contextmanager
from dataclasses import dataclass, fields, replace
from decimal import Decimal, InvalidOperation
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import sys

from .locking import RuntimeAccountLock
from ..risk.runtime_risk import (
    RuntimeRiskConfiguration, RuntimeRiskError, RiskBook, RiskState,
    RiskExecution, RiskExecutionSide, RiskActionKind, RiskActionProposal, RiskVerdict, RiskReason,
    initial_risk_book, apply_owned_execution, calculate_risk_equity,
    initialize_risk_state, advance_risk_state, evaluate_risk, rearm_risk_state, DAY_MS,
)
from .state import (
    PendingAction, PendingActionKind, PositionEvidence, RuntimeReason,
    RuntimeState, RuntimeStateError, RuntimeStateSnapshot, RuntimeEvent,
    RuntimeEventType, transition_runtime_state,
)

SCHEMA_VERSION = 2
RUNTIME_CONTRACT_VERSION = 1
_OPEN_DATABASES = {}  # Canonical paths/counts only; prevents in-process migration.
_HOUR_MS = 3_600_000
_MAX_ROWS = 100_000  # Bounded full validation; no truncation/partial success.
_MAX_DATABASE_BYTES = 256 * 1024 * 1024
_MAX_BATCH_FILLS = 10_000
_MAX_DECIMAL_CHARS = 4096


class RuntimeStoreError(RuntimeError):
    """Safe persistence/record diagnostic; no raw SQL, file or exception text."""


class RuntimeStoreIntegrityError(RuntimeStoreError):
    """Unsupported, malformed or inconsistent durable evidence."""


class RuntimeStoreMigrationRequiredError(RuntimeStoreIntegrityError):
    """Recognized legacy v1; only explicit migration may upgrade it."""


class RuntimeStoreConflictError(RuntimeStoreError):
    """Identity, duplicate, reference, sequence or phase conflict."""


def _require(condition, message):
    if not condition:
        raise RuntimeStoreError(message)


def _text(value, *, limit=64):
    _require(isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{1," + str(limit) + "}", value) is not None, "Invalid safe identifier.")


def _digest(value):
    _require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None, "Invalid SHA256 identity.")


def _integer(value, *, minimum=0, maximum=2**63 - 1):
    _require(type(value) is int and minimum <= value <= maximum, "Invalid bounded integer.")


def _time(value, *, optional=False, candle=False):
    if optional and value is None:
        return
    _integer(value)
    if candle:
        _require(value % _HOUR_MS == 0, "Candle time must be integer UTC milliseconds on the hourly grid.")


def _choice(value, allowed):
    _require(type(value) is str and value in allowed, "Invalid explicit value.")


def _enum(value, cls):
    _require(isinstance(value, cls), "An explicit enum is required.")


def serialize_decimal(value: Decimal) -> str:
    """Canonical plain TEXT, exact numeric value; no context rounding or float.

    Insignificant trailing fractional zeroes and signed zero canonicalize.
    Values requiring more than 4096 plain characters fail before allocation.
    """
    _require(isinstance(value, Decimal) and value.is_finite(), "A finite Decimal is required.")
    if value == 0:
        return "0"
    digits = value.as_tuple()
    length = len(digits.digits) + abs(digits.exponent) + 3
    _require(length <= _MAX_DECIMAL_CHARS, "Decimal exceeds the supported exact storage bound.")
    result = format(value, "f")
    if "." in result:
        result = result.rstrip("0").rstrip(".")
    return result


def deserialize_decimal(value: str) -> Decimal:
    """Reject malformed, noncanonical, scientific, whitespace or nonfinite TEXT."""
    if not isinstance(value, str) or len(value) > _MAX_DECIMAL_CHARS or re.fullmatch(r"-?(0|[1-9][0-9]*)(\.[0-9]+)?", value) is None:
        raise RuntimeStoreIntegrityError("Malformed stored Decimal.")
    try:
        result = Decimal(value)
        if serialize_decimal(result) != value:
            raise RuntimeStoreIntegrityError("Noncanonical stored Decimal.")
        return result
    except (InvalidOperation, RuntimeStoreError):
        raise RuntimeStoreIntegrityError("Malformed or noncanonical stored Decimal.") from None


def _amount(value, *, positive=False):
    serialize_decimal(value)
    _require(value > 0 if positive else value >= 0, "Invalid financial amount.")


class ActionPhase(str, Enum):
    PREPARED = "PREPARED"
    ATTEMPT_STARTED = "ATTEMPT_STARTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    UNKNOWN_OUTCOME = "UNKNOWN_OUTCOME"
    TERMINAL_CONFIRMED = "TERMINAL_CONFIRMED"
    REJECTED = "REJECTED"
    ABANDONED_UNSENT = "ABANDONED_UNSENT"


class JournalActionKind(str, Enum):
    ENTRY = "ENTRY"
    EXIT = "EXIT"
    CANCEL = "CANCEL"


class DecisionDisposition(str, Enum):
    BOOTSTRAP = "BOOTSTRAP"
    REPLAY_ONLY = "REPLAY_ONLY"
    NOOP = "NOOP"
    WAIT = "WAIT"
    ACTION = "ACTION"
    HALT = "HALT"


@dataclass(frozen=True, slots=True)
class RuntimeConfiguration:
    broker_id: str
    account_binding: str
    bot_id: str
    strategy_id: str
    strategy_implementation_digest: str
    strategy_parameters: tuple[tuple[str, int], ...]
    symbol: str
    base_currency: str
    quote_currency: str
    timeframe: str
    interval_ms: int
    configuration_digest: str
    buy_quote_budget: Decimal
    history_anchor_ms: int
    decision_max_age_ms: int
    observation_max_age_ms: int
    reconciliation_timeout_ms: int
    reconciliation_round_limit: int
    read_attempt_limit: int
    request_timeout_ms: int
    max_clock_skew_ms: int
    broker_account_id: str | None = None
    schema_version: int = SCHEMA_VERSION
    runtime_contract_version: int = RUNTIME_CONTRACT_VERSION

    def __post_init__(self):
        _validate_runtime_configuration(self, SCHEMA_VERSION)


def _validate_runtime_configuration(self, schema_version):
    _require(self.broker_id == "bybit-demo", "Demo broker identity required.")
    _text(self.account_binding)
    _require(isinstance(self.bot_id, str) and re.fullmatch(r"[a-z0-9]{1,12}", self.bot_id) is not None, "Invalid bot namespace.")
    _require(self.strategy_id == "ema_trend", "Initial runtime strategy must be ema_trend.")
    _digest(self.strategy_implementation_digest)
    _digest(self.configuration_digest)
    _require(type(self.strategy_parameters) is tuple and all(type(pair) is tuple and len(pair) == 2 for pair in self.strategy_parameters), "Immutable strategy parameters required.")
    _require(self.strategy_parameters == (("fast_span", 20), ("slow_span", 50), ("warmup_candles", 50)) and all(type(pair[1]) is int for pair in self.strategy_parameters), "Initial anchored EMA20/50 parameters required.")
    for value in (self.symbol, self.base_currency, self.quote_currency):
        _text(value)
        _require(value.isupper(), "Uppercase instrument identifiers required.")
    _require(self.base_currency != self.quote_currency and self.symbol == self.base_currency + self.quote_currency, "Instrument currency binding mismatch.")
    _require(type(self.timeframe) is str and self.timeframe == "60", "Initial timeframe must be 60.")
    _integer(self.interval_ms)
    _require(self.interval_ms == _HOUR_MS, "Initial interval must be one hour.")
    _amount(self.buy_quote_budget, positive=True)
    _time(self.history_anchor_ms, candle=True)
    for value in (self.decision_max_age_ms, self.observation_max_age_ms, self.reconciliation_timeout_ms, self.request_timeout_ms, self.max_clock_skew_ms):
        _integer(value, minimum=1)
    _integer(self.reconciliation_round_limit, minimum=1, maximum=1000)
    _integer(self.read_attempt_limit, minimum=1, maximum=3)
    if self.broker_account_id is not None:
        _text(self.broker_account_id)
    _integer(self.schema_version)
    _integer(self.runtime_contract_version)
    _require(self.schema_version == schema_version and self.runtime_contract_version == RUNTIME_CONTRACT_VERSION, "Unsupported runtime schema/contract version.")


@dataclass(frozen=True, slots=True)
class _LegacyConfiguration(RuntimeConfiguration):
    """Frozen v1 identity decoder, never a public v2 configuration."""

    def __post_init__(self):
        _validate_runtime_configuration(self, 1)


@dataclass(frozen=True, slots=True)
class RuntimeCheckpoint:
    sequence: int
    snapshot: RuntimeStateSnapshot
    last_processed_candle_ms: int | None = None
    last_reconciled_at_ms: int | None = None
    observed_at_ms: int | None = None
    coverage_start_ms: int | None = None
    coverage_end_ms: int | None = None
    halted_at_ms: int | None = None
    shutdown_at_ms: int | None = None
    rearmed_at_ms: int | None = None
    bootstrap_until_ms: int | None = None
    replay_until_ms: int | None = None

    def __post_init__(self):
        _integer(self.sequence)
        _require(isinstance(self.snapshot, RuntimeStateSnapshot), "Validated runtime snapshot required.")
        for name in ("last_processed_candle_ms", "bootstrap_until_ms", "replay_until_ms"):
            _time(getattr(self, name), optional=True, candle=True)
        for name in ("last_reconciled_at_ms", "observed_at_ms", "coverage_start_ms", "coverage_end_ms", "halted_at_ms", "shutdown_at_ms", "rearmed_at_ms"):
            _time(getattr(self, name), optional=True)
        _require((self.coverage_start_ms is None) == (self.coverage_end_ms is None), "Coverage needs both boundaries or neither.")
        if self.coverage_start_ms is not None:
            _require(self.coverage_start_ms <= self.coverage_end_ms, "Invalid observation coverage.")
        halted = self.snapshot.state == RuntimeState.HALTED or self.snapshot.stopped_from == RuntimeState.HALTED
        _require(halted == (self.halted_at_ms is not None), "HALT timestamp must match the retained latch.")
        _require((self.snapshot.state == RuntimeState.STOPPING) == (self.shutdown_at_ms is not None), "Shutdown timestamp must match STOPPING.")


@dataclass(frozen=True, slots=True)
class CandleRecord:
    symbol: str
    timeframe: str
    candle_open_ms: int
    input_fingerprint: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal

    def __post_init__(self):
        _text(self.symbol)
        _choice(self.timeframe, {"60"})
        _time(self.candle_open_ms, candle=True)
        _digest(self.input_fingerprint)
        for value in (self.open, self.high, self.low, self.close):
            _amount(value, positive=True)
        _amount(self.volume)
        _require(self.low <= min(self.open, self.close) <= max(self.open, self.close) <= self.high, "Invalid supplied candle price bounds.")


@dataclass(frozen=True, slots=True)
class DecisionRecord:
    symbol: str
    timeframe: str
    candle_open_ms: int
    input_fingerprint: str
    signal: str
    desired_position: int
    disposition: DecisionDisposition
    available_at_ms: int
    action_id: str | None = None

    def __post_init__(self):
        _text(self.symbol)
        _choice(self.timeframe, {"60"})
        _time(self.candle_open_ms, candle=True)
        _digest(self.input_fingerprint)
        _choice(self.signal, {"LONG_ENTRY", "LONG_EXIT", "HOLD"})
        _integer(self.desired_position, maximum=1)
        _enum(self.disposition, DecisionDisposition)
        _time(self.available_at_ms)
        _require(self.available_at_ms == self.candle_open_ms + _HOUR_MS, "Decision availability must follow the hourly candle.")
        if self.signal != "HOLD":
            _require(self.desired_position == int(self.signal == "LONG_ENTRY"), "Signal/intent mismatch.")
        _require((self.disposition == DecisionDisposition.ACTION) == (self.action_id is not None), "Only ACTION decisions reference an action.")
        if self.action_id is not None:
            _digest(self.action_id)


@dataclass(frozen=True, slots=True)
class ActionRecord:
    logical_action_id: str
    kind: JournalActionKind
    symbol: str
    reconciliation_deadline_ms: int
    remaining_reconciliation_rounds: int
    remaining_read_attempts: int
    order_link_id: str | None = None
    candle_open_ms: int | None = None
    control_id: str | None = None
    parent_action_id: str | None = None
    target_broker_order_id: str | None = None
    side: str | None = None
    amount_unit: str | None = None
    currency: str | None = None
    authorized_amount: Decimal | None = None
    phase: ActionPhase = ActionPhase.PREPARED
    attempt_count: int = 0
    broker_order_id: str | None = None
    submitted_amount: Decimal | None = None
    acknowledgement_broker_ms: int | None = None
    acknowledgement_observed_ms: int | None = None
    observed_at_ms: int | None = None
    order_status: str | None = None
    external_status: str | None = None
    terminal_at_ms: int | None = None
    safe_reason: RuntimeReason | None = None
    rejection_code: int | None = None

    def __post_init__(self):
        _digest(self.logical_action_id)
        _enum(self.kind, JournalActionKind)
        _enum(self.phase, ActionPhase)
        _text(self.symbol)
        _time(self.reconciliation_deadline_ms)
        _integer(self.remaining_reconciliation_rounds, maximum=1000)
        _integer(self.remaining_read_attempts, maximum=3)
        _integer(self.attempt_count, maximum=1)
        unsent = self.phase in (ActionPhase.PREPARED, ActionPhase.ABANDONED_UNSENT)
        _require(self.attempt_count == (0 if unsent else 1), "Action phase/attempt count mismatch.")
        if self.kind == JournalActionKind.CANCEL:
            _require(self.candle_open_ms is None and all(value is None for value in (self.order_link_id, self.side, self.amount_unit, self.currency, self.authorized_amount, self.submitted_amount, self.broker_order_id)), "Cancellation is a subordinate control, not a new placement.")
            _text(self.control_id)
            _digest(self.parent_action_id)
            _text(self.target_broker_order_id)
        else:
            _require(all(value is None for value in (self.control_id, self.parent_action_id, self.target_broker_order_id)), "Placement cannot carry cancellation control fields.")
            _time(self.candle_open_ms, candle=True)
            _text(self.order_link_id, limit=36)
            entry = self.kind == JournalActionKind.ENTRY
            _require(self.side == ("BUY" if entry else "SELL") and self.amount_unit == ("QUOTE" if entry else "BASE"), "Action direction/unit mismatch.")
            _text(self.currency)
            _amount(self.authorized_amount, positive=True)
        if self.submitted_amount is not None:
            _amount(self.submitted_amount, positive=True)
            _require(self.submitted_amount <= self.authorized_amount, "Submitted amount exceeds authorization.")
        for value in (self.broker_order_id, self.external_status):
            if value is not None:
                _text(value)
        for value in (self.acknowledgement_broker_ms, self.acknowledgement_observed_ms, self.observed_at_ms, self.terminal_at_ms):
            _time(value, optional=True)
        _require((self.acknowledgement_broker_ms is None) == (self.acknowledgement_observed_ms is None), "Incomplete acknowledgement timestamps.")
        if self.acknowledgement_broker_ms is not None:
            _require(not unsent and (self.kind == JournalActionKind.CANCEL or (self.broker_order_id is not None and self.submitted_amount is not None)), "Acknowledgement requires matching submitted identity/amount.")
        if unsent:
            _require(all(value is None for value in (self.broker_order_id, self.submitted_amount, self.acknowledgement_broker_ms, self.observed_at_ms, self.order_status, self.external_status, self.rejection_code)), "Unsent action cannot contain broker observations.")
        if self.order_status is not None:
            _choice(self.order_status, {"NEW", "OPEN", "PARTIALLY_FILLED", "FILLED", "CANCELLED", "REJECTED", "EXPIRED", "UNKNOWN"})
            _require(self.observed_at_ms is not None, "Status requires observation time.")
        if self.safe_reason is not None:
            _enum(self.safe_reason, RuntimeReason)
        terminal = self.phase in _TERMINAL_PHASES
        _require(terminal == (self.terminal_at_ms is not None), "Terminal phase requires terminal evidence time.")
        if self.phase == ActionPhase.ACKNOWLEDGED:
            _require(self.acknowledgement_broker_ms is not None, "ACKNOWLEDGED needs an acceptance receipt.")
        if self.phase == ActionPhase.UNKNOWN_OUTCOME:
            _require(self.safe_reason is not None, "Unknown outcome needs a safe reason.")
        if self.phase == ActionPhase.TERMINAL_CONFIRMED:
            _require(self.order_status in {"FILLED", "CANCELLED", "REJECTED", "EXPIRED"}, "Terminal confirmation needs known terminal status.")
            _require(self.kind == JournalActionKind.CANCEL or self.broker_order_id is not None, "Terminal placement evidence needs the exact broker order ID.")
        if self.phase == ActionPhase.REJECTED:
            _integer(self.rejection_code, minimum=-(2**63))
            _require(self.rejection_code != 0, "Confirmed rejection needs a nonzero broker code.")
        else:
            _require(self.rejection_code is None, "Rejection code belongs only to REJECTED.")


_TERMINAL_PHASES = frozenset({ActionPhase.TERMINAL_CONFIRMED, ActionPhase.REJECTED, ActionPhase.ABANDONED_UNSENT})


@dataclass(frozen=True, slots=True)
class OwnedFillRecord:
    broker_id: str
    account_binding: str
    broker_execution_id: str
    action_id: str
    broker_order_id: str
    order_link_id: str
    symbol: str
    side: str
    executed_quantity: Decimal
    execution_price: Decimal
    execution_fee: Decimal
    fee_currency: str | None
    executed_at_ms: int
    observed_at_ms: int

    def __post_init__(self):
        _require(self.broker_id == "bybit-demo", "Demo fill identity required.")
        for value in (self.account_binding, self.broker_execution_id, self.broker_order_id, self.symbol):
            _text(value)
        _text(self.order_link_id, limit=36)
        _digest(self.action_id)
        _choice(self.side, {"BUY", "SELL"})
        _amount(self.executed_quantity, positive=True)
        _amount(self.execution_price, positive=True)
        serialize_decimal(self.execution_fee)  # Signed fees/rebates are preserved.
        if self.fee_currency is not None:
            _text(self.fee_currency)
            _require(self.fee_currency.isupper(), "Fee currency must be explicit uppercase text.")
        _time(self.executed_at_ms)
        _time(self.observed_at_ms)


# Persistence records deliberately flatten exact SQL columns. The pure engine
# remains the only source of accounting and risk-transition formulas.
class RiskValuationMode(str, Enum):
    ACTIVATION = "ACTIVATION"
    REPLAY_ONLY = "REPLAY_ONLY"
    LIVE = "LIVE"


def _canonical_hash(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True).encode("utf-8")).hexdigest()


@contextmanager
def _risk_validation():
    try:
        yield
    except RuntimeRiskError:
        raise RuntimeStoreIntegrityError("Invalid exact risk accounting evidence.") from None


def _risk_exact(record, cls):
    _require(type(record) is cls, "An exact validated risk record is required.")
    try:
        with _risk_validation():
            replace(record)
    except (AttributeError, TypeError):
        raise RuntimeStoreError("A complete validated risk record is required.") from None


def _risk_shape(record):
    # Reject subclasses/coercion at the new persistence boundary. Optional and
    # enum relationships are validated explicitly by each record below.
    for field in fields(record):
        if field.type in (str, int, Decimal):
            _require(type(getattr(record, field.name)) is field.type,
                     "Exact risk persistence field types are required.")


@dataclass(frozen=True, slots=True)
class RiskConfigurationRecord:
    risk_configuration_digest: str
    risk_contract_version: int
    risk_capital_quote: Decimal
    buy_quote_budget: Decimal
    max_entry_notional_quote: Decimal
    max_position_notional_quote: Decimal
    max_daily_loss_fraction: Decimal
    max_drawdown_fraction: Decimal
    max_entries_per_utc_day: int
    base_currency: str
    quote_currency: str

    def __post_init__(self):
        _risk_shape(self)
        _digest(self.risk_configuration_digest)
        _integer(self.risk_contract_version, minimum=1, maximum=1)
        _integer(self.max_entries_per_utc_day, minimum=1)
        with _risk_validation():
            self.configuration
        payload = _encode(self)
        payload.pop("risk_configuration_digest")
        _require(self.risk_configuration_digest == _canonical_hash(payload), "Risk configuration digest/content mismatch.")

    @property
    def configuration(self) -> RuntimeRiskConfiguration:
        return RuntimeRiskConfiguration(**{field.name: getattr(self, field.name)
                                           for field in fields(RuntimeRiskConfiguration)})


def _risk_configuration_record(configuration):
    _risk_exact(configuration, RuntimeRiskConfiguration)
    values = {"risk_contract_version": 1, **_encode(configuration)}
    digest = _canonical_hash(values)
    return RiskConfigurationRecord(digest, 1, **{field.name: getattr(configuration, field.name)
                                               for field in fields(configuration)})


@dataclass(frozen=True, slots=True)
class RiskEpochRecord:
    epoch_id: str
    epoch_sequence: int
    risk_configuration_digest: str
    started_at_ms: int
    parent_epoch_id: str | None = None

    def __post_init__(self):
        _risk_shape(self)
        _digest(self.epoch_id)
        _digest(self.risk_configuration_digest)
        _integer(self.epoch_sequence, minimum=1)
        _time(self.started_at_ms, candle=True)
        _require((self.epoch_sequence == 1) == (self.parent_epoch_id is None), "Risk epoch parent/sequence mismatch.")
        if self.parent_epoch_id is not None:
            _digest(self.parent_epoch_id)
        payload = _encode(self)
        payload.pop("epoch_id")
        _require(self.epoch_id == _canonical_hash(payload), "Risk epoch digest/content mismatch.")


def _initial_risk_epoch(configuration, started_at_ms, *, parent=None):
    values = dict(risk_configuration_digest=configuration.risk_configuration_digest,
                  epoch_sequence=1 if parent is None else parent.epoch_sequence + 1,
                  started_at_ms=started_at_ms,
                  parent_epoch_id=None if parent is None else parent.epoch_id)
    return RiskEpochRecord(epoch_id=_canonical_hash(values), **values)


@dataclass(frozen=True, slots=True)
class RiskValuationRecord:
    epoch_id: str
    valued_at_ms: int
    mode: RiskValuationMode
    symbol: str
    timeframe: str
    candle_open_ms: int
    risk_configuration_digest: str
    mark_price: Decimal
    virtual_quote_cash: Decimal
    owned_base_quantity: Decimal
    risk_equity: Decimal
    peak_risk_equity: Decimal
    utc_day_start_ms: int
    utc_day_start_risk_equity: Decimal
    daily_pnl: Decimal
    entries_this_utc_day: int
    trip_reason: RiskReason | None
    tripped_at_ms: int | None
    trip_pending_report: bool
    fill_evidence_count: int
    fill_evidence_digest: str

    def __post_init__(self):
        _risk_shape(self)
        for value in (self.epoch_id, self.risk_configuration_digest, self.fill_evidence_digest):
            _digest(value)
        _require(type(self.mode) is RiskValuationMode, "An explicit valuation mode is required.")
        _text(self.symbol)
        _choice(self.timeframe, {"60"})
        _time(self.candle_open_ms, candle=True)
        _time(self.valued_at_ms, candle=True)
        _require(self.valued_at_ms == self.candle_open_ms + _HOUR_MS, "Risk valuation must bind its candle close boundary.")
        _require(type(self.mark_price) is Decimal, "Exact Decimal risk mark required.")
        _amount(self.mark_price, positive=True)
        _integer(self.fill_evidence_count, maximum=_MAX_ROWS)
        _integer(self.entries_this_utc_day)
        with _risk_validation():
            state = self.state(0)  # The real epoch lower bound is checked on load.
            _require(calculate_risk_equity(self.book, self.mark_price) == state.risk_equity,
                     "Risk book/mark/equity mismatch.")

    @property
    def book(self) -> RiskBook:
        return RiskBook(self.virtual_quote_cash, self.owned_base_quantity)

    def state(self, epoch_started_at_ms: int) -> RiskState:
        return RiskState(epoch_started_at_ms=epoch_started_at_ms,
                         **{field.name: getattr(self, field.name) for field in fields(RiskState)
                            if field.name != "epoch_started_at_ms"})


def _risk_valuation(epoch, mode, candle, book, state, evidence):
    values = {field.name: getattr(state, field.name) for field in fields(state)
              if field.name != "epoch_started_at_ms"}
    return RiskValuationRecord(epoch_id=epoch.epoch_id, mode=mode, symbol=candle.symbol,
        timeframe=candle.timeframe, candle_open_ms=candle.candle_open_ms,
        risk_configuration_digest=epoch.risk_configuration_digest, mark_price=candle.close,
        virtual_quote_cash=book.virtual_quote_cash, owned_base_quantity=book.owned_base_quantity,
        fill_evidence_count=evidence[0], fill_evidence_digest=evidence[1], **values)


@dataclass(frozen=True, slots=True)
class RiskVerdictRecord:
    symbol: str
    timeframe: str
    candle_open_ms: int
    epoch_id: str
    valued_at_ms: int
    risk_configuration_digest: str
    proposal_kind: RiskActionKind | None
    authorized_amount: Decimal | None
    verdict: RiskVerdict
    reason: RiskReason | None
    action_id: str | None
    evaluated_at_ms: int

    def __post_init__(self):
        _risk_shape(self)
        _text(self.symbol)
        _choice(self.timeframe, {"60"})
        _time(self.candle_open_ms, candle=True)
        _time(self.valued_at_ms, candle=True)
        _time(self.evaluated_at_ms)
        _require(self.valued_at_ms == self.candle_open_ms + _HOUR_MS
                 and self.evaluated_at_ms >= self.valued_at_ms, "Risk verdict timing mismatch.")
        for value in (self.epoch_id, self.risk_configuration_digest):
            _digest(value)
        _require(type(self.verdict) is RiskVerdict, "An explicit risk verdict is required.")
        _require((self.proposal_kind is None) == (self.authorized_amount is None), "Risk proposal requires both kind and amount.")
        if self.proposal_kind is not None:
            _require(type(self.proposal_kind) is RiskActionKind and type(self.authorized_amount) is Decimal,
                     "An explicit exact risk proposal is required.")
            _amount(self.authorized_amount, positive=True)
        if self.action_id is not None:
            _digest(self.action_id)
        if self.verdict is RiskVerdict.ALLOW:
            _require(self.reason is None and (self.action_id is not None) == (self.proposal_kind is not None),
                     "ALLOW binds its action or is accounting only.")
        else:
            _require(self.action_id is None and type(self.reason) is RiskReason
                     and self.proposal_kind is not RiskActionKind.EXIT, "Refusal cannot authorize an action or refuse a valid EXIT.")
            trip = self.reason in (RiskReason.DAILY_LOSS_LIMIT, RiskReason.MAX_DRAWDOWN)
            _require(trip == (self.verdict is RiskVerdict.TRIP)
                     and (self.verdict is not RiskVerdict.BLOCK or self.proposal_kind is RiskActionKind.ENTRY),
                     "Risk refusal reason/proposal mismatch.")


def _fill_evidence(fills, valued_at_ms):
    selected = tuple(sorted((fill for fill in fills if fill.executed_at_ms <= valued_at_ms),
                            key=lambda fill: (fill.executed_at_ms, fill.broker_execution_id)))
    return selected, (len(selected), _canonical_hash([_encode(fill) for fill in selected]))


def _risk_book(configuration, fills):
    with _risk_validation():
        book = initial_risk_book(configuration)
        for fill in fills:
            book = apply_owned_execution(configuration, book, RiskExecution(
                fill.broker_execution_id, RiskExecutionSide(fill.side), fill.executed_quantity,
                fill.execution_price, fill.execution_fee, fill.fee_currency, fill.executed_at_ms))
        return book


# Explicit columns: all financial values are TEXT, all time/sequence values INTEGER.
_SCHEMA_V1 = {
    "identity": """CREATE TABLE identity (
        singleton INTEGER PRIMARY KEY CHECK(singleton=1),
        broker_id TEXT NOT NULL, account_binding TEXT NOT NULL, bot_id TEXT NOT NULL,
        strategy_id TEXT NOT NULL, strategy_implementation_digest TEXT NOT NULL,
        strategy_parameters TEXT NOT NULL, symbol TEXT NOT NULL, base_currency TEXT NOT NULL,
        quote_currency TEXT NOT NULL, timeframe TEXT NOT NULL, interval_ms INTEGER NOT NULL,
        configuration_digest TEXT NOT NULL, buy_quote_budget TEXT NOT NULL,
        history_anchor_ms INTEGER NOT NULL, decision_max_age_ms INTEGER NOT NULL,
        observation_max_age_ms INTEGER NOT NULL, reconciliation_timeout_ms INTEGER NOT NULL,
        reconciliation_round_limit INTEGER NOT NULL, read_attempt_limit INTEGER NOT NULL,
        request_timeout_ms INTEGER NOT NULL, max_clock_skew_ms INTEGER NOT NULL,
        broker_account_id TEXT, schema_version INTEGER NOT NULL,
        runtime_contract_version INTEGER NOT NULL,
        UNIQUE(broker_id, account_binding, bot_id), UNIQUE(broker_id, account_binding)
    )""",
    "candles": """CREATE TABLE candles (
        symbol TEXT NOT NULL, timeframe TEXT NOT NULL, candle_open_ms INTEGER NOT NULL,
        input_fingerprint TEXT NOT NULL, open TEXT NOT NULL, high TEXT NOT NULL,
        low TEXT NOT NULL, close TEXT NOT NULL, volume TEXT NOT NULL,
        PRIMARY KEY(symbol, timeframe, candle_open_ms), UNIQUE(symbol, candle_open_ms)
    )""",
    "actions": """CREATE TABLE actions (
        logical_action_id TEXT PRIMARY KEY NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('ENTRY','EXIT','CANCEL')),
        symbol TEXT NOT NULL, reconciliation_deadline_ms INTEGER NOT NULL,
        remaining_reconciliation_rounds INTEGER NOT NULL CHECK(remaining_reconciliation_rounds>=0),
        remaining_read_attempts INTEGER NOT NULL CHECK(remaining_read_attempts BETWEEN 0 AND 3),
        order_link_id TEXT UNIQUE, candle_open_ms INTEGER, control_id TEXT UNIQUE,
        parent_action_id TEXT REFERENCES actions(logical_action_id), target_broker_order_id TEXT,
        side TEXT, amount_unit TEXT, currency TEXT, authorized_amount TEXT,
        phase TEXT NOT NULL CHECK(phase IN ('PREPARED','ATTEMPT_STARTED','ACKNOWLEDGED','UNKNOWN_OUTCOME','TERMINAL_CONFIRMED','REJECTED','ABANDONED_UNSENT')),
        attempt_count INTEGER NOT NULL CHECK(attempt_count IN (0,1)), broker_order_id TEXT UNIQUE,
        submitted_amount TEXT, acknowledgement_broker_ms INTEGER,
        acknowledgement_observed_ms INTEGER, observed_at_ms INTEGER, order_status TEXT,
        external_status TEXT, terminal_at_ms INTEGER, safe_reason TEXT, rejection_code INTEGER,
        UNIQUE(logical_action_id, broker_order_id, order_link_id),
        FOREIGN KEY(symbol, candle_open_ms) REFERENCES candles(symbol, candle_open_ms)
    )""",
    "decisions": """CREATE TABLE decisions (
        symbol TEXT NOT NULL, timeframe TEXT NOT NULL, candle_open_ms INTEGER NOT NULL,
        input_fingerprint TEXT NOT NULL, signal TEXT NOT NULL, desired_position INTEGER NOT NULL CHECK(desired_position IN (0,1)),
        disposition TEXT NOT NULL, available_at_ms INTEGER NOT NULL,
        action_id TEXT UNIQUE REFERENCES actions(logical_action_id),
        PRIMARY KEY(symbol, timeframe, candle_open_ms),
        FOREIGN KEY(symbol, timeframe, candle_open_ms) REFERENCES candles(symbol, timeframe, candle_open_ms)
    )""",
    "fills": """CREATE TABLE fills (
        broker_id TEXT NOT NULL, account_binding TEXT NOT NULL,
        broker_execution_id TEXT NOT NULL, action_id TEXT NOT NULL,
        broker_order_id TEXT NOT NULL, order_link_id TEXT NOT NULL,
        symbol TEXT NOT NULL, side TEXT NOT NULL, executed_quantity TEXT NOT NULL,
        execution_price TEXT NOT NULL, execution_fee TEXT NOT NULL, fee_currency TEXT,
        executed_at_ms INTEGER NOT NULL, observed_at_ms INTEGER NOT NULL,
        PRIMARY KEY(broker_id, account_binding, broker_execution_id),
        FOREIGN KEY(broker_id, account_binding) REFERENCES identity(broker_id, account_binding),
        FOREIGN KEY(action_id, broker_order_id, order_link_id) REFERENCES actions(logical_action_id, broker_order_id, order_link_id)
    )""",
    "checkpoint": """CREATE TABLE checkpoint (
        singleton INTEGER PRIMARY KEY CHECK(singleton=1), sequence INTEGER NOT NULL CHECK(sequence>=0),
        state TEXT NOT NULL, owned_base_quantity TEXT, position_evidence TEXT NOT NULL,
        desired_position INTEGER CHECK(desired_position IN (0,1)),
        pending_action_id TEXT REFERENCES actions(logical_action_id), pending_action_kind TEXT,
        reason TEXT, stopped_from TEXT, last_processed_candle_ms INTEGER,
        last_reconciled_at_ms INTEGER, observed_at_ms INTEGER, coverage_start_ms INTEGER,
        coverage_end_ms INTEGER, halted_at_ms INTEGER, shutdown_at_ms INTEGER,
        rearmed_at_ms INTEGER, bootstrap_until_ms INTEGER, replay_until_ms INTEGER
    )""",
}
_INDEXES_V1 = {
    "one_pending_placement": "CREATE UNIQUE INDEX one_pending_placement ON actions((1)) WHERE kind IN ('ENTRY','EXIT') AND phase IN ('PREPARED','ATTEMPT_STARTED','ACKNOWLEDGED','UNKNOWN_OUTCOME')",
    "one_pending_cancel": "CREATE UNIQUE INDEX one_pending_cancel ON actions(parent_action_id) WHERE kind='CANCEL' AND phase IN ('PREPARED','ATTEMPT_STARTED','ACKNOWLEDGED','UNKNOWN_OUTCOME')",
}
# v1 is literal above, not inferred by subtracting risk tables from v2.
_RISK_SCHEMA = {
    "risk_configurations": """CREATE TABLE risk_configurations (
        risk_configuration_digest TEXT PRIMARY KEY NOT NULL,
        risk_contract_version INTEGER NOT NULL,
        risk_capital_quote TEXT NOT NULL, buy_quote_budget TEXT NOT NULL,
        max_entry_notional_quote TEXT NOT NULL, max_position_notional_quote TEXT NOT NULL,
        max_daily_loss_fraction TEXT NOT NULL, max_drawdown_fraction TEXT NOT NULL,
        max_entries_per_utc_day INTEGER NOT NULL,
        base_currency TEXT NOT NULL, quote_currency TEXT NOT NULL
    )""",
    "risk_epochs": """CREATE TABLE risk_epochs (
        epoch_id TEXT PRIMARY KEY NOT NULL, epoch_sequence INTEGER UNIQUE NOT NULL,
        risk_configuration_digest TEXT NOT NULL REFERENCES risk_configurations(risk_configuration_digest),
        started_at_ms INTEGER NOT NULL, parent_epoch_id TEXT REFERENCES risk_epochs(epoch_id)
    )""",
    "risk_valuations": """CREATE TABLE risk_valuations (
        epoch_id TEXT NOT NULL REFERENCES risk_epochs(epoch_id), valued_at_ms INTEGER NOT NULL,
        mode TEXT NOT NULL CHECK(mode IN ('ACTIVATION','REPLAY_ONLY','LIVE')),
        symbol TEXT NOT NULL, timeframe TEXT NOT NULL, candle_open_ms INTEGER NOT NULL,
        risk_configuration_digest TEXT NOT NULL REFERENCES risk_configurations(risk_configuration_digest),
        mark_price TEXT NOT NULL, virtual_quote_cash TEXT NOT NULL, owned_base_quantity TEXT NOT NULL,
        risk_equity TEXT NOT NULL, peak_risk_equity TEXT NOT NULL, utc_day_start_ms INTEGER NOT NULL,
        utc_day_start_risk_equity TEXT NOT NULL, daily_pnl TEXT NOT NULL,
        entries_this_utc_day INTEGER NOT NULL, trip_reason TEXT, tripped_at_ms INTEGER,
        trip_pending_report INTEGER NOT NULL CHECK(trip_pending_report IN (0,1)),
        fill_evidence_count INTEGER NOT NULL, fill_evidence_digest TEXT NOT NULL,
        PRIMARY KEY(epoch_id,valued_at_ms),
        FOREIGN KEY(symbol,timeframe,candle_open_ms) REFERENCES candles(symbol,timeframe,candle_open_ms)
    )""",
    "risk_verdicts": """CREATE TABLE risk_verdicts (
        symbol TEXT NOT NULL, timeframe TEXT NOT NULL, candle_open_ms INTEGER NOT NULL,
        epoch_id TEXT NOT NULL REFERENCES risk_epochs(epoch_id), valued_at_ms INTEGER NOT NULL,
        risk_configuration_digest TEXT NOT NULL REFERENCES risk_configurations(risk_configuration_digest),
        proposal_kind TEXT CHECK(proposal_kind IN ('ENTRY','EXIT')), authorized_amount TEXT,
        verdict TEXT NOT NULL CHECK(verdict IN ('ALLOW','BLOCK','TRIP')), reason TEXT,
        action_id TEXT UNIQUE REFERENCES actions(logical_action_id), evaluated_at_ms INTEGER NOT NULL,
        PRIMARY KEY(symbol,timeframe,candle_open_ms),
        CHECK((proposal_kind IS NULL) = (authorized_amount IS NULL)),
        FOREIGN KEY(symbol,timeframe,candle_open_ms) REFERENCES decisions(symbol,timeframe,candle_open_ms),
        FOREIGN KEY(epoch_id,valued_at_ms) REFERENCES risk_valuations(epoch_id,valued_at_ms)
    )""",
}
_SCHEMA = {**_SCHEMA_V1, **_RISK_SCHEMA}
_INDEXES = dict(_INDEXES_V1)
_RISK_MODELS = {
    "risk_configurations": RiskConfigurationRecord, "risk_epochs": RiskEpochRecord,
    "risk_valuations": RiskValuationRecord, "risk_verdicts": RiskVerdictRecord,
}

_MODELS = {"identity": RuntimeConfiguration, "candles": CandleRecord, "decisions": DecisionRecord, "actions": ActionRecord, "fills": OwnedFillRecord}
_DECIMALS = {
    "identity": {"buy_quote_budget"}, "candles": {"open", "high", "low", "close", "volume"},
    "actions": {"authorized_amount", "submitted_amount"},
    "fills": {"executed_quantity", "execution_price", "execution_fee"}, "checkpoint": {"owned_base_quantity"},
    "risk_configurations": {"risk_capital_quote", "buy_quote_budget", "max_entry_notional_quote",
                            "max_position_notional_quote", "max_daily_loss_fraction", "max_drawdown_fraction"},
    "risk_valuations": {"mark_price", "virtual_quote_cash", "owned_base_quantity", "risk_equity",
                        "peak_risk_equity", "utc_day_start_risk_equity", "daily_pnl"},
    "risk_verdicts": {"authorized_amount"},
}
_ENUMS = {"actions": {"kind": JournalActionKind, "phase": ActionPhase, "safe_reason": RuntimeReason}, "decisions": {"disposition": DecisionDisposition}}

_ENUMS.update({
    "risk_valuations": {"mode": RiskValuationMode, "trip_reason": RiskReason},
    "risk_verdicts": {"proposal_kind": RiskActionKind, "verdict": RiskVerdict, "reason": RiskReason},
})


def _encode(record):
    result = {}
    for field in fields(record):
        value = getattr(record, field.name)
        if isinstance(value, Decimal):
            value = serialize_decimal(value)
        elif isinstance(value, Enum):
            value = value.value
        elif field.name == "strategy_parameters":
            value = json.dumps(value, separators=(",", ":"), ensure_ascii=True)
        result[field.name] = value
    return result


def _checkpoint_values(checkpoint):
    result = _encode(checkpoint)
    snapshot = result.pop("snapshot")
    result.update({
        "state": snapshot.state.value,
        "owned_base_quantity": None if snapshot.owned_base_quantity is None else serialize_decimal(snapshot.owned_base_quantity),
        "position_evidence": snapshot.position_evidence.value, "desired_position": snapshot.desired_position,
        "pending_action_id": None if snapshot.pending_action is None else snapshot.pending_action.logical_action_id,
        "pending_action_kind": None if snapshot.pending_action is None else snapshot.pending_action.kind.value,
        "reason": None if snapshot.reason is None else snapshot.reason.value,
        "stopped_from": None if snapshot.stopped_from is None else snapshot.stopped_from.value,
    })
    return result


def _decode(table, row, *, legacy=False):
    try:
        values = dict(row)
        values.pop("singleton", None)
        for name in _DECIMALS.get(table, ()):
            if values[name] is not None:
                values[name] = deserialize_decimal(values[name])
        for name, cls in _ENUMS.get(table, {}).items():
            if values[name] is not None:
                values[name] = cls(values[name])
        if table == "identity":
            data = json.loads(values["strategy_parameters"])
            _require(type(data) is list, "Invalid stored parameters.")
            values["strategy_parameters"] = tuple(tuple(pair) for pair in data)
        if table == "checkpoint":
            pending_id = values.pop("pending_action_id")
            pending_kind = values.pop("pending_action_kind")
            _require((pending_id is None) == (pending_kind is None), "Incomplete stored pending identity.")
            pending = None if pending_id is None else PendingAction(pending_id, PendingActionKind(pending_kind))
            values["snapshot"] = RuntimeStateSnapshot(
                state=RuntimeState(values.pop("state")), owned_base_quantity=values.pop("owned_base_quantity"),
                position_evidence=PositionEvidence(values.pop("position_evidence")), desired_position=values.pop("desired_position"),
                pending_action=pending, reason=None if values["reason"] is None else RuntimeReason(values["reason"]),
                stopped_from=None if values["stopped_from"] is None else RuntimeState(values["stopped_from"]),
            )
            values.pop("reason")
            values.pop("stopped_from")
            return RuntimeCheckpoint(**values)
        if table == "risk_valuations":
            _integer(values["trip_pending_report"], maximum=1)
            values["trip_pending_report"] = bool(values["trip_pending_report"])
        if table == "identity" and legacy:
            return _LegacyConfiguration(**values)
        return {**_MODELS, **_RISK_MODELS}[table](**values)
    except (RuntimeStoreError, RuntimeStateError, RuntimeRiskError, ValueError, TypeError, KeyError):
        raise RuntimeStoreIntegrityError("Invalid stored runtime record.") from None


# The closed graph forbids backward phase changes, resends and terminal rewrites.
_PHASE_TRANSITIONS = {
    ActionPhase.PREPARED: {ActionPhase.ATTEMPT_STARTED, ActionPhase.ABANDONED_UNSENT},
    ActionPhase.ATTEMPT_STARTED: {ActionPhase.ACKNOWLEDGED, ActionPhase.UNKNOWN_OUTCOME, ActionPhase.TERMINAL_CONFIRMED, ActionPhase.REJECTED},
    ActionPhase.ACKNOWLEDGED: {ActionPhase.ACKNOWLEDGED, ActionPhase.UNKNOWN_OUTCOME, ActionPhase.TERMINAL_CONFIRMED},
    ActionPhase.UNKNOWN_OUTCOME: {ActionPhase.UNKNOWN_OUTCOME, ActionPhase.ACKNOWLEDGED, ActionPhase.TERMINAL_CONFIRMED},
    ActionPhase.TERMINAL_CONFIRMED: set(), ActionPhase.REJECTED: set(), ActionPhase.ABANDONED_UNSENT: set(),
}
_INTENT_FIELDS = (
    "logical_action_id", "kind", "symbol", "reconciliation_deadline_ms", "order_link_id", "candle_open_ms",
    "control_id", "parent_action_id", "target_broker_order_id", "side", "amount_unit", "currency", "authorized_amount",
)


class RuntimeStore:
    """Lock-bound local journal. Public writes each own a short IMMEDIATE transaction.

    There is no arbitrary SQL/callback transaction API, so a public transaction
    cannot contain a broker call or sleep. Related evidence is supplied to one
    method. Internal commit failures roll back where possible and never return
    success. An indeterminate commit/rollback closes the connection; reopen and
    validate durable evidence instead of treating the action as unsent.
    """

    def __init__(self):
        raise RuntimeStoreError("Use RuntimeStore.open with an acquired account lock.")

    @classmethod
    def open(cls, lock: RuntimeAccountLock, configuration: RuntimeConfiguration, *, initialize: bool = False) -> "RuntimeStore":
        _require(isinstance(lock, RuntimeAccountLock) and isinstance(configuration, RuntimeConfiguration) and type(initialize) is bool, "Explicit lock/configuration/initialization required.")
        lock._assert_held()
        if lock.broker_id != configuration.broker_id or lock.account_binding != configuration.account_binding:
            raise RuntimeStoreConflictError("Lock and runtime account identities differ.")
        instance = object.__new__(cls)
        instance._lock = lock
        instance._configuration = configuration
        instance._connection = None
        instance._attached = False
        path = lock.registry_root / "accounts" / lock.account_key / "runtime.sqlite3"
        if path != lock.database_path:
            raise RuntimeStoreError("Database path must use the canonical account registry.")
        try:
            for directory in (path.parent.parent, path.parent):
                if directory.is_symlink():
                    raise RuntimeStoreError("Store directories must not be symlinks.")
                if initialize:
                    directory.mkdir(mode=0o700, exist_ok=True)
                    descriptor = os.open(directory.parent, os.O_RDONLY)
                    try:
                        os.fsync(descriptor)
                    finally:
                        os.close(descriptor)
                elif not directory.is_dir():
                    raise RuntimeStoreIntegrityError("Existing runtime store is missing.")
            for suffix in ("-journal", "-wal", "-shm"):
                sidecar = path.with_name(path.name + suffix)
                if sidecar.exists() or sidecar.is_symlink():
                    metadata = sidecar.lstat()
                    if initialize or suffix != "-journal" or not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                        raise RuntimeStoreIntegrityError("Unsafe or incompatible SQLite sidecar.")
            if initialize:
                descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                os.close(descriptor)
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > _MAX_DATABASE_BYTES:
                raise RuntimeStoreIntegrityError("Store must be a regular unaliased file.")
            instance._connection = sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, isolation_level=None, timeout=0)
            instance._connection.row_factory = sqlite3.Row
            instance._database_path = path
            instance._database_identity = (info.st_dev, info.st_ino)
            if not initialize:
                # Reject another schema or WAL store before changing any setting.
                schema = {row[0]: row[1] for row in instance._connection.execute("SELECT name,sql FROM sqlite_master WHERE sql IS NOT NULL")}
                if schema == {**_SCHEMA_V1, **_INDEXES_V1} and instance._connection.execute("PRAGMA user_version").fetchone()[0] == 1 and instance._connection.execute("PRAGMA journal_mode").fetchone()[0] == "delete":
                    instance._configure()
                    instance._validate_v1()
                    raise RuntimeStoreMigrationRequiredError("Explicit runtime schema v1 to v2 migration is required.")
                if schema != {**_SCHEMA, **_INDEXES} or instance._connection.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION or instance._connection.execute("PRAGMA journal_mode").fetchone()[0] != "delete":
                    raise RuntimeStoreIntegrityError("Existing runtime schema/version/journal is unsupported.")
            instance._configure()
            if initialize:
                with instance._transaction(validate=False):
                    for sql in (*_SCHEMA.values(), *_INDEXES.values()):
                        instance._connection.execute(sql)
                    instance._connection.execute("PRAGMA user_version=2")
                    instance._insert("identity", {"singleton": 1, **_encode(configuration)})
                    instance._insert("checkpoint", {"singleton": 1, **_checkpoint_values(RuntimeCheckpoint(0, RuntimeStateSnapshot()))})
                # Persist the new database's directory entry as well as SQLite's commit.
                descriptor = os.open(path.parent, os.O_RDONLY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
            instance._validate_all()
            saved = instance._one("identity")
            if saved != configuration:
                raise RuntimeStoreConflictError("Stored runtime identity/configuration does not match.")
            _OPEN_DATABASES[path] = _OPEN_DATABASES.get(path, 0) + 1
            lock._stores += 1
            instance._attached = True
            return instance
        except (OSError, sqlite3.Error):
            instance.close()
            raise RuntimeStoreIntegrityError("Cannot open/initialize the runtime store safely.") from None
        except RuntimeStoreError:
            instance.close()
            raise

    def _validate_v1(self):
        """Decode the literal legacy contract without a v2 identity constructor."""
        previous = self._configuration
        try:
            row = self._connection.execute("SELECT * FROM identity").fetchone()
            if row is None:
                raise RuntimeStoreIntegrityError("Legacy identity is missing.")
            self._configuration = _decode("identity", row, legacy=True)
            self._legacy_validation = True
            self._validate_all()
            return self._configuration
        finally:
            self._configuration = previous
            self._legacy_validation = False

    @classmethod
    def migrate_v1_to_v2(cls, lock: RuntimeAccountLock, configuration: RuntimeConfiguration) -> None:
        """Explicit local structural upgrade; never activation or history repair.

        Only temporary test fixtures should be migrated without a separately
        reviewed operator decision for a real runtime database. A lost commit
        result requires reopening; this operation never retries it.
        """
        _require(type(lock) is RuntimeAccountLock and type(configuration) is RuntimeConfiguration,
                 "An exact acquired lock and v2 runtime configuration are required.")
        replace(configuration)
        lock._assert_held()
        if (lock.broker_id, lock.account_binding) != (configuration.broker_id, configuration.account_binding):
            raise RuntimeStoreConflictError("Lock and runtime account identities differ.")
        path = lock.registry_root / "accounts" / lock.account_key / "runtime.sqlite3"
        if path != lock.database_path or _OPEN_DATABASES.get(path, 0) or lock._stores:
            raise RuntimeStoreConflictError("Migration requires the canonical database with no open store.")
        instance = object.__new__(cls)
        instance._lock, instance._configuration = lock, configuration
        instance._connection, instance._attached = None, False
        committed = False
        try:
            for directory in (path.parent.parent, path.parent):
                if directory.is_symlink() or not directory.is_dir():
                    raise RuntimeStoreIntegrityError("Existing safe store directories are required.")
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > _MAX_DATABASE_BYTES:
                raise RuntimeStoreIntegrityError("Migration requires a regular unaliased existing database.")
            for suffix in ("-journal", "-wal", "-shm"):
                sidecar = path.with_name(path.name + suffix)
                if sidecar.exists() or sidecar.is_symlink():
                    metadata = sidecar.lstat()
                    if suffix != "-journal" or not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                        raise RuntimeStoreIntegrityError("Unsafe or incompatible SQLite sidecar.")
            instance._database_path = path
            instance._database_identity = (info.st_dev, info.st_ino)
            instance._connection = sqlite3.connect(path.as_uri() + "?mode=rw", uri=True,
                                                   isolation_level=None, timeout=0)
            instance._connection.row_factory = sqlite3.Row
            schema = {row[0]: row[1] for row in instance._connection.execute(
                "SELECT name,sql FROM sqlite_master WHERE sql IS NOT NULL")}
            if (schema != {**_SCHEMA_V1, **_INDEXES_V1}
                    or instance._connection.execute("PRAGMA user_version").fetchone()[0] != 1
                    or instance._connection.execute("PRAGMA journal_mode").fetchone()[0] != "delete"):
                raise RuntimeStoreIntegrityError("Migration requires exact supported legacy v1.")
            instance._configure()
            source = instance._validate_v1()
            for field in fields(configuration):
                if field.name not in {"schema_version", "configuration_digest"} and getattr(source, field.name) != getattr(configuration, field.name):
                    raise RuntimeStoreConflictError("Legacy runtime configuration is incompatible with the reviewed destination.")
            with instance._transaction(validate=False):
                if instance._validate_v1() != source:
                    raise RuntimeStoreIntegrityError("Legacy migration source changed.")
                for sql in _RISK_SCHEMA.values():
                    instance._connection.execute(sql)
                instance._connection.execute("UPDATE identity SET schema_version=2, configuration_digest=? WHERE singleton=1",
                                             (configuration.configuration_digest,))
                instance._connection.execute("PRAGMA user_version=2")
                instance._validate_all()
            committed = True
        except (OSError, sqlite3.Error):
            raise RuntimeStoreIntegrityError("Cannot complete runtime migration; reopen to inspect the outcome.") from None
        finally:
            instance.close()
        if committed:
            try:
                with cls.open(lock, configuration):
                    pass
            except RuntimeStoreError:
                raise RuntimeStoreIntegrityError("Post-commit migration validation failed; reopen to inspect the outcome.") from None

    def _configure(self):
        connection = self._connection
        connection.execute("PRAGMA journal_mode=DELETE")
        connection.execute("PRAGMA synchronous=EXTRA")
        connection.execute("PRAGMA foreign_keys=ON")
        if sys.platform == "darwin":
            connection.execute("PRAGMA fullfsync=ON")
        self._verify_settings()

    def durability_settings(self) -> dict:
        """Effective connection settings; fullfsync=1 is required on macOS."""
        self._live()
        try:
            return {name: self._connection.execute("PRAGMA " + name).fetchone()[0] for name in ("journal_mode", "synchronous", "foreign_keys", "fullfsync")}
        except (sqlite3.Error, TypeError):
            raise RuntimeStoreIntegrityError("Cannot verify SQLite settings.") from None

    def _verify_settings(self):
        settings = self.durability_settings()
        if settings["journal_mode"] != "delete" or settings["synchronous"] != 3 or settings["foreign_keys"] != 1 or (sys.platform == "darwin" and settings["fullfsync"] != 1):
            raise RuntimeStoreIntegrityError("Required SQLite durability settings drifted.")

    def _live(self):
        self._lock._assert_held()
        if self._connection is None:
            raise RuntimeStoreError("Runtime store is closed.")
        try:
            info = self._database_path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or (info.st_dev, info.st_ino) != self._database_identity:
                raise RuntimeStoreIntegrityError("Runtime database file identity changed.")
        except OSError:
            raise RuntimeStoreIntegrityError("Runtime database file is unavailable.") from None

    def _commit(self):
        self._connection.execute("COMMIT")

    @contextmanager
    def _transaction(self, *, validate=True):
        self._live()
        self._verify_settings()
        if self._connection.in_transaction:
            raise RuntimeStoreError("Nested transactions are not permitted.")
        began = False
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            began = True
            yield
            if validate:
                self._validate_relations()
                self._validate_bounds()
            self._commit()
        except BaseException as error:
            if began and not self._connection.in_transaction:
                # SQLite may have ended a transaction before reporting a failure.
                # Do not assume rollback or permit a send from an uncertain result.
                self.close()
                raise RuntimeStoreError("Transaction outcome requires reopening and validation.") from None
            try:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
            except sqlite3.Error:
                self.close()
                raise RuntimeStoreError("Transaction outcome requires reopening and validation.") from None
            if isinstance(error, sqlite3.IntegrityError):
                raise RuntimeStoreConflictError("Journal constraint conflict; transaction rolled back.") from None
            if isinstance(error, sqlite3.Error):
                raise RuntimeStoreError("SQLite transaction failed; no successful commit reported.") from None
            raise

    def _insert(self, table, values):
        columns = ",".join(values)
        self._connection.execute("INSERT INTO " + table + " (" + columns + ") VALUES (" + ",".join("?" for _ in values) + ")", tuple(values.values()))

    def _update(self, table, values, key, value):
        self._connection.execute("UPDATE " + table + " SET " + ",".join(name + "=?" for name in values) + " WHERE " + key + "=?", (*values.values(), value))

    def _one(self, table, where="", args=()):
        self._live()
        self._verify_settings()
        try:
            row = self._connection.execute("SELECT * FROM " + table + (" WHERE " + where if where else ""), args).fetchone()
            return None if row is None else _decode(table, row, legacy=getattr(self, "_legacy_validation", False))
        except sqlite3.Error:
            raise RuntimeStoreIntegrityError("Cannot read durable runtime evidence.") from None

    def get_configuration(self) -> RuntimeConfiguration:
        self._verify_settings()
        saved = self._one("identity")
        if saved != self._configuration:
            raise RuntimeStoreIntegrityError("Durable runtime binding changed.")
        return saved

    def get_checkpoint(self) -> RuntimeCheckpoint:
        self._verify_settings()
        try:
            self._validate_relations()
        except sqlite3.Error:
            raise RuntimeStoreIntegrityError("Cannot validate durable checkpoint references.") from None
        return self._one("checkpoint")

    def get_candle(self, candle_open_ms: int) -> CandleRecord | None:
        _time(candle_open_ms, candle=True)
        return self._one("candles", "symbol=? AND timeframe=? AND candle_open_ms=?", (self._configuration.symbol, self._configuration.timeframe, candle_open_ms))

    def get_decision(self, candle_open_ms: int) -> DecisionRecord | None:
        _time(candle_open_ms, candle=True)
        return self._one("decisions", "symbol=? AND timeframe=? AND candle_open_ms=?", (self._configuration.symbol, self._configuration.timeframe, candle_open_ms))

    def get_action(self, action_id: str) -> ActionRecord | None:
        _digest(action_id)
        return self._one("actions", "logical_action_id=?", (action_id,))

    def get_fill(self, execution_id: str) -> OwnedFillRecord | None:
        _text(execution_id)
        return self._one("fills", "broker_id=? AND account_binding=? AND broker_execution_id=?", (self._configuration.broker_id, self._configuration.account_binding, execution_id))

    def list_actions(self) -> tuple[ActionRecord, ...]:
        """Complete durable action history, ordered by logical_action_id ASC.

        Includes cancellation controls and terminal history without resolving
        anything. Full validation enforces the existing row bounds and binding;
        corruption fails the entire read rather than returning a partial tuple.
        """
        self._validate_all()
        try:
            return tuple(_decode("actions", row) for row in self._connection.execute(
                "SELECT * FROM actions ORDER BY logical_action_id ASC"))
        except sqlite3.Error:
            raise RuntimeStoreIntegrityError("Cannot enumerate durable action history.") from None

    def list_fills(self, action_id: str | None = None) -> tuple[OwnedFillRecord, ...]:
        """Complete bound-account fills, optionally for one exact action ID.

        Order is executed_at_ms ASC, broker_execution_id ASC. An empty tuple
        describes only this local query, not whether an exchange order filled.
        No inventory, completeness or reconciliation policy is calculated here.
        """
        if action_id is not None:
            _digest(action_id)
        self._validate_all()
        query = "SELECT * FROM fills WHERE broker_id=? AND account_binding=?"
        arguments = (self._configuration.broker_id, self._configuration.account_binding)
        if action_id is not None:
            query += " AND action_id=?"
            arguments += (action_id,)
        query += " ORDER BY executed_at_ms ASC, broker_execution_id ASC"
        try:
            return tuple(_decode("fills", row) for row in self._connection.execute(query, arguments))
        except sqlite3.Error:
            raise RuntimeStoreIntegrityError("Cannot enumerate durable fill history.") from None

    def _risk_rows(self, table, order):
        self._validate_all()
        try:
            return tuple(_decode(table, row) for row in self._connection.execute(
                "SELECT * FROM " + table + " ORDER BY " + order))
        except sqlite3.Error:
            raise RuntimeStoreIntegrityError("Cannot read complete durable risk history.") from None

    def get_risk_configuration(self, risk_configuration_digest: str | None = None) -> RiskConfigurationRecord | None:
        """Current epoch's configuration, or one exact digest; no partial reads."""
        if risk_configuration_digest is not None:
            _digest(risk_configuration_digest)
        configurations = self._risk_rows("risk_configurations", "risk_configuration_digest")
        if risk_configuration_digest is None:
            epoch = self.get_current_risk_epoch()
            risk_configuration_digest = None if epoch is None else epoch.risk_configuration_digest
        return next((record for record in configurations if record.risk_configuration_digest == risk_configuration_digest), None)

    def get_current_risk_epoch(self) -> RiskEpochRecord | None:
        epochs = self._risk_rows("risk_epochs", "epoch_sequence")
        return epochs[-1] if epochs else None

    def get_latest_risk_valuation(self) -> RiskValuationRecord | None:
        epoch = self.get_current_risk_epoch()
        valuations = () if epoch is None else self.list_risk_valuations(epoch.epoch_id)
        return valuations[-1] if valuations else None

    def list_risk_valuations(self, epoch_id: str | None = None) -> tuple[RiskValuationRecord, ...]:
        """Complete chronological history, optionally restricted to one epoch."""
        if epoch_id is not None:
            _digest(epoch_id)
        rows = self._risk_rows("risk_valuations", "valued_at_ms,epoch_id")
        sequences = {row.epoch_id: row.epoch_sequence
                     for row in self._risk_rows("risk_epochs", "epoch_sequence")}
        rows = sorted(rows, key=lambda row: (row.valued_at_ms, sequences[row.epoch_id]))
        return tuple(row for row in rows if epoch_id is None or row.epoch_id == epoch_id)

    def get_risk_verdict(self, candle_open_ms: int) -> RiskVerdictRecord | None:
        _time(candle_open_ms, candle=True)
        return next((row for row in self.list_risk_verdicts() if row.candle_open_ms == candle_open_ms), None)

    def list_risk_verdicts(self, epoch_id: str | None = None) -> tuple[RiskVerdictRecord, ...]:
        if epoch_id is not None:
            _digest(epoch_id)
        rows = self._risk_rows("risk_verdicts", "candle_open_ms,symbol,timeframe")
        return tuple(row for row in rows if epoch_id is None or row.epoch_id == epoch_id)

    def _risk_compatible(self, configuration):
        runtime = self._configuration
        if (configuration.buy_quote_budget, configuration.base_currency, configuration.quote_currency) != (
                runtime.buy_quote_budget, runtime.base_currency, runtime.quote_currency):
            raise RuntimeStoreConflictError("Risk policy must match runtime budget and currencies.")

    def _risk_facts(self, configuration, candle_open_ms):
        candle = self.get_candle(candle_open_ms)
        if candle is None:
            raise RuntimeStoreConflictError("Risk valuation requires an existing durable candle.")
        _time(candle_open_ms + _HOUR_MS, candle=True)
        selected, evidence = _fill_evidence(self.list_fills(), candle_open_ms + _HOUR_MS)
        return candle, _risk_book(configuration, selected), evidence

    def initialize_risk_journal(self, risk_configuration: RuntimeRiskConfiguration, *, candle_open_ms: int) -> RiskValuationRecord:
        """Once-only epoch-1 ACTIVATION from durable fills, never wallet facts."""
        _time(candle_open_ms, candle=True)
        record = _risk_configuration_record(risk_configuration)
        self._risk_compatible(risk_configuration)
        with self._transaction():
            self._validate_all()
            if any(self._connection.execute("SELECT 1 FROM " + table + " LIMIT 1").fetchone()
                   for table in _RISK_SCHEMA):
                raise RuntimeStoreConflictError("Risk journal has already been initialized.")
            checkpoint = self.get_checkpoint()
            snapshot = checkpoint.snapshot
            if (snapshot.state not in (RuntimeState.FLAT, RuntimeState.LONG)
                    or snapshot.position_evidence is not PositionEvidence.CONFIRMED
                    or snapshot.pending_action is not None):
                raise RuntimeStoreConflictError("Risk activation requires safe confirmed FLAT or LONG without pending work.")
            candle, book, evidence = self._risk_facts(risk_configuration, candle_open_ms)
            if book.owned_base_quantity != snapshot.owned_base_quantity:
                raise RuntimeStoreConflictError("Activation executions do not match confirmed owned inventory at this boundary.")
            # Even a future round-trip returning to the same quantity cannot be
            # silently folded into a historical activation checkpoint.
            if self._connection.execute("SELECT 1 FROM fills WHERE executed_at_ms>? LIMIT 1",
                                        (candle_open_ms + _HOUR_MS,)).fetchone():
                raise RuntimeStoreConflictError("Activation boundary precedes retained owned executions.")
            with _risk_validation():
                state = initialize_risk_state(risk_configuration, book, candle.close, candle_open_ms + _HOUR_MS)
            epoch = _initial_risk_epoch(record, state.valued_at_ms)
            valuation = _risk_valuation(epoch, RiskValuationMode.ACTIVATION, candle, book, state, evidence)
            self._insert("risk_configurations", _encode(record))
            self._insert("risk_epochs", _encode(epoch))
            self._insert("risk_valuations", _encode(valuation))
            self._validate_risk_history()
        return valuation

    def rearm_runtime_halt(self, *, expected_sequence: int, operator_at_ms: int) -> RuntimeCheckpoint:
        """Explicit HALT → SYNCHRONIZING CAS; risk and broker evidence stay intact.

        This records an operator control, not repaired/confirmed exposure.
        Indeterminate persistence requires reopening, never blind retry.
        """
        _integer(expected_sequence)
        _time(operator_at_ms)
        with self._transaction():
            self._validate_all()
            current = self.get_checkpoint()
            if current.sequence != expected_sequence or current.snapshot.state is not RuntimeState.HALTED:
                raise RuntimeStoreConflictError("HALT rearm requires the current HALTED checkpoint sequence.")
            if (operator_at_ms <= current.halted_at_ms
                    or (current.rearmed_at_ms is not None and operator_at_ms < current.rearmed_at_ms)):
                raise RuntimeStoreConflictError("HALT rearm time must follow the latch and remain monotonic.")
            snapshot = transition_runtime_state(current.snapshot, RuntimeEvent(RuntimeEventType.OPERATOR_REARMED))
            checkpoint = replace(current, sequence=current.sequence + 1, snapshot=snapshot,
                                 halted_at_ms=None, rearmed_at_ms=operator_at_ms)
            self._save_checkpoint(checkpoint, expected_sequence)
            self._validate_all()
        return checkpoint

    def rearm_risk_epoch(self, *, expected_epoch_id: str, operator_at_ms: int) -> RiskValuationRecord:
        """Explicit same-boundary child epoch from complete durable local evidence.

        Only epoch + ACTIVATION are inserted. No checkpoint, configuration,
        strategy intent, action or broker state is changed by this control.
        """
        _digest(expected_epoch_id)
        _time(operator_at_ms)
        with self._transaction():
            self._validate_all()
            parent = self.get_current_risk_epoch()
            if parent is None or parent.epoch_id != expected_epoch_id:
                raise RuntimeStoreConflictError("Risk rearm requires the current expected epoch.")
            previous = self.get_latest_risk_valuation()
            if (previous.trip_reason is None or previous.tripped_at_ms is None
                    or previous.trip_pending_report):
                raise RuntimeStoreConflictError("Risk rearm requires a reported automatic trip.")
            checkpoint = self.get_checkpoint()
            snapshot = checkpoint.snapshot
            if (snapshot.state not in (RuntimeState.FLAT, RuntimeState.LONG)
                    or snapshot.position_evidence is not PositionEvidence.CONFIRMED
                    or snapshot.pending_action is not None or snapshot.reason is not None
                    or any(action.phase not in _TERMINAL_PHASES for action in self.list_actions())):
                raise RuntimeStoreConflictError("Risk rearm requires safe confirmed FLAT or LONG without unresolved work.")
            if snapshot.desired_position != int(snapshot.state is RuntimeState.LONG):
                raise RuntimeStoreConflictError("Risk rearm requires aligned strategy intent and exposure.")
            runtime = self._configuration
            for observed in (checkpoint.last_reconciled_at_ms, checkpoint.observed_at_ms):
                if (observed is None or not 0 <= operator_at_ms - observed <= runtime.observation_max_age_ms
                        or (checkpoint.rearmed_at_ms is not None and observed < checkpoint.rearmed_at_ms)):
                    raise RuntimeStoreConflictError("Risk rearm requires fresh post-rearm reconciliation evidence.")
            if not 0 <= operator_at_ms - previous.valued_at_ms <= runtime.decision_max_age_ms:
                raise RuntimeStoreConflictError("Risk rearm requires a fresh accepted mark.")
            if previous.candle_open_ms != checkpoint.last_processed_candle_ms:
                raise RuntimeStoreConflictError("Risk rearm requires aligned risk and runtime frontiers.")
            fills = self.list_fills()
            selected, evidence = _fill_evidence(fills, previous.valued_at_ms)
            if evidence != (previous.fill_evidence_count, previous.fill_evidence_digest):
                raise RuntimeStoreConflictError("Predecessor owned-fill evidence changed; risk rearm is blocked.")
            # Quantity equality cannot prove unchanged economics: even a round
            # trip or a base-fee-offset fill after T must wait for later accounting.
            if any(fill.executed_at_ms > previous.valued_at_ms for fill in fills):
                raise RuntimeStoreConflictError("Risk rearm boundary precedes retained owned executions.")
            record = self.get_risk_configuration(parent.risk_configuration_digest)
            configuration = record.configuration
            book = _risk_book(configuration, selected)
            if book != previous.book or book.owned_base_quantity != snapshot.owned_base_quantity:
                raise RuntimeStoreConflictError("Risk rearm requires the exact accepted continuous owned book.")
            consumed = sum(row.verdict is RiskVerdict.ALLOW and row.proposal_kind is RiskActionKind.ENTRY
                           and row.evaluated_at_ms // DAY_MS * DAY_MS == previous.utc_day_start_ms
                           for row in self.list_risk_verdicts())
            if consumed != previous.entries_this_utc_day:
                raise RuntimeStoreIntegrityError("Risk ENTRY count differs from retained authorization history.")
            with _risk_validation():
                state = rearm_risk_state(configuration, previous.state(parent.started_at_ms), book,
                                         previous.mark_price, previous.valued_at_ms)
            child = _initial_risk_epoch(record, previous.valued_at_ms, parent=parent)
            candle = self.get_candle(previous.candle_open_ms)
            valuation = _risk_valuation(child, RiskValuationMode.ACTIVATION, candle, book, state, evidence)
            self._insert("risk_epochs", _encode(child))
            self._insert("risk_valuations", _encode(valuation))
            self._validate_all()
        return valuation

    def append_risk_replay_valuation(self, *, candle_open_ms: int) -> bool:
        """Append exactly the next hour; an exact complete replay retry is False.

        Historical evidence is immutable. A changed predecessor snapshot blocks
        continuation; no old row is rewritten or reinterpreted on ordinary read.
        """
        _time(candle_open_ms, candle=True)
        with self._transaction():
            self._validate_all()
            epoch = self.get_current_risk_epoch()
            if epoch is None:
                raise RuntimeStoreConflictError("Risk journal must be explicitly initialized first.")
            configuration = self.get_risk_configuration().configuration
            valuations = self.list_risk_valuations(epoch.epoch_id)
            target_ms = candle_open_ms + _HOUR_MS
            existing = next((row for row in valuations if row.valued_at_ms == target_ms), None)
            if existing is not None:
                index = valuations.index(existing)
                if existing.mode is not RiskValuationMode.REPLAY_ONLY or index == 0:
                    raise RuntimeStoreConflictError("Only an identical REPLAY_ONLY valuation may be retried.")
                previous = valuations[index - 1]
            else:
                previous = valuations[-1]
            if target_ms != previous.valued_at_ms + _HOUR_MS:
                raise RuntimeStoreConflictError("Risk replay must advance by exactly one hour.")
            _, evidence = _fill_evidence(self.list_fills(), previous.valued_at_ms)
            if evidence != (previous.fill_evidence_count, previous.fill_evidence_digest):
                raise RuntimeStoreConflictError("Predecessor owned-fill evidence changed; risk replay is blocked.")
            candle, book, evidence = self._risk_facts(configuration, candle_open_ms)
            with _risk_validation():
                state = advance_risk_state(configuration, previous.state(epoch.started_at_ms), book,
                                           candle.close, target_ms)
            expected = _risk_valuation(epoch, RiskValuationMode.REPLAY_ONLY, candle, book, state, evidence)
            if existing is not None:
                if existing != expected:
                    raise RuntimeStoreConflictError("Conflicting immutable risk replay.")
                return False
            self._insert("risk_valuations", _encode(expected))
            self._validate_risk_history()
        return True

    def _risk_planning_history(self, epoch):
        verdicts = {row.candle_open_ms: row for row in self.list_risk_verdicts(epoch.epoch_id)}
        return tuple((self.get_decision(row.candle_open_ms), row, verdicts.get(row.candle_open_ms))
                     for row in self.list_risk_valuations(epoch.epoch_id))

    def commit_live_risk_decision(
        self, candle: CandleRecord, decision: DecisionRecord, checkpoint: RuntimeCheckpoint,
        *, expected_sequence: int, evaluated_at_ms: int,
        proposed_action: ActionRecord | None = None,
    ) -> bool:
        """Atomically authorize one current LIVE decision from durable facts.

        Inputs are the original frozen planner proposal/checkpoint, never a
        caller verdict. Refusal replaces its pending event with NO_CHANGE. True
        means committed; False means an exact already-committed replay and can
        NEVER license a send. Persistence uncertainty requires reopening.
        """
        # Local imports avoid the frozen planner -> record definitions cycle.
        from .planner import CanonicalDecision, DecisionMode, PlanKind, plan_action, _canonical_intent
        from .risk_gate import continue_refused_intent, risk_proposal

        _require(type(candle) is CandleRecord and type(decision) is DecisionRecord
                 and type(checkpoint) is RuntimeCheckpoint, "Exact validated LIVE records are required.")
        replace(candle)
        replace(decision)
        replace(checkpoint, snapshot=replace(checkpoint.snapshot))
        _integer(expected_sequence)
        _time(evaluated_at_ms)
        with _risk_validation():
            proposal = risk_proposal(proposed_action)
        self._check_instrument(candle)
        self._check_instrument(decision)
        if (candle.candle_open_ms, candle.input_fingerprint) != (decision.candle_open_ms, decision.input_fingerprint):
            raise RuntimeStoreConflictError("LIVE decision must match its accepted candle.")
        config = self._configuration
        if proposed_action is not None:
            self._check_action_binding(proposed_action)
            expected_id = hashlib.sha256(_canonical_intent(config, decision, proposed_action.kind,
                                                           proposed_action.authorized_amount)).hexdigest()
            if (proposed_action.logical_action_id != expected_id or decision.action_id != expected_id
                    or proposed_action.candle_open_ms != candle.candle_open_ms
                    or proposed_action.reconciliation_deadline_ms != decision.available_at_ms + config.reconciliation_timeout_ms
                    or proposed_action.remaining_reconciliation_rounds != config.reconciliation_round_limit
                    or proposed_action.remaining_read_attempts != config.read_attempt_limit
                    or (proposal.kind is RiskActionKind.ENTRY and proposal.authorized_amount != config.buy_quote_budget)):
                raise RuntimeStoreConflictError("LIVE proposal differs from canonical frozen planner intent.")

        with self._transaction():
            self._validate_all()
            epoch = self.get_current_risk_epoch()
            if epoch is None:
                raise RuntimeStoreConflictError("An explicitly activated risk epoch is required.")
            configuration = self.get_risk_configuration().configuration
            previous = self.get_latest_risk_valuation()
            prior_decision = self.get_decision(candle.candle_open_ms)
            if prior_decision is not None:
                prior_verdict = self.get_risk_verdict(candle.candle_open_ms)
                expected_decision = decision
                if prior_verdict is not None and prior_verdict.verdict is not RiskVerdict.ALLOW and proposal is not None:
                    expected_decision = replace(decision, disposition=DecisionDisposition.WAIT, action_id=None)
                if (prior_verdict is None or prior_verdict.epoch_id != epoch.epoch_id
                        or self.get_candle(candle.candle_open_ms) != candle or prior_decision != expected_decision
                        or (prior_verdict.proposal_kind, prior_verdict.authorized_amount, prior_verdict.evaluated_at_ms)
                        != (None if proposal is None else proposal.kind,
                            None if proposal is None else proposal.authorized_amount, evaluated_at_ms)):
                    raise RuntimeStoreConflictError("Conflicting immutable LIVE replay.")
                if prior_verdict.action_id is not None:
                    saved = self.get_action(prior_verdict.action_id)
                    if proposed_action is None or any(getattr(saved, name) != getattr(proposed_action, name) for name in _INTENT_FIELDS):
                        raise RuntimeStoreConflictError("LIVE replay cannot replace its original action.")
                return False

            current = self.get_checkpoint()
            if current.sequence != expected_sequence:
                raise RuntimeStoreConflictError("Stale LIVE checkpoint sequence.")
            if (current.last_processed_candle_ms is None
                    or candle.candle_open_ms != current.last_processed_candle_ms + _HOUR_MS
                    or previous.candle_open_ms != current.last_processed_candle_ms
                    or candle.candle_open_ms + _HOUR_MS != previous.valued_at_ms + _HOUR_MS):
                raise RuntimeStoreConflictError("LIVE requires the next frontier and consecutive risk hour after catch-up.")
            canonical = CanonicalDecision(decision.symbol, decision.timeframe, decision.candle_open_ms,
                                          decision.input_fingerprint, decision.signal, decision.desired_position,
                                          decision.available_at_ms)
            actions = self.list_actions()
            plan = plan_action(config, current, canonical, evaluated_at_ms=evaluated_at_ms,
                               mode=DecisionMode.LIVE, action_history=actions)
            if plan.kind is PlanKind.HALT:
                plan = continue_refused_intent(config, current, canonical, plan, evaluated_at_ms=evaluated_at_ms,
                    epoch=epoch, history=self._risk_planning_history(epoch), action_history=actions)
            if (plan.kind not in (PlanKind.NOOP, PlanKind.WAIT, PlanKind.PLACE_BUY, PlanKind.PLACE_SELL)
                    or plan.decision is None or plan.decision.disposition not in (
                        DecisionDisposition.NOOP, DecisionDisposition.WAIT, DecisionDisposition.ACTION)
                    or decision != plan.decision or proposed_action != plan.action):
                raise RuntimeStoreConflictError("Operational planner evidence does not permit this LIVE proposal.")
            snapshot = current.snapshot
            for event in plan.events:
                snapshot = transition_runtime_state(snapshot, event)
            expected_checkpoint = replace(current, sequence=current.sequence + 1, snapshot=snapshot,
                                          last_processed_candle_ms=candle.candle_open_ms)
            if checkpoint != expected_checkpoint:
                raise RuntimeStoreConflictError("LIVE checkpoint differs from its independent planner transition.")

            fills = self.list_fills()
            _, predecessor_evidence = _fill_evidence(fills, previous.valued_at_ms)
            if predecessor_evidence != (previous.fill_evidence_count, previous.fill_evidence_digest):
                raise RuntimeStoreConflictError("Predecessor owned-fill evidence changed; LIVE is blocked.")
            selected, evidence = _fill_evidence(fills, candle.candle_open_ms + _HOUR_MS)
            book = _risk_book(configuration, selected)
            # A read may observe fills after this closed mark. No-action
            # accounting keeps its temporal cutoff; a placement must agree with
            # the currently confirmed quantity as well as that cutoff book.
            if proposal is not None and book.owned_base_quantity != current.snapshot.owned_base_quantity:
                raise RuntimeStoreConflictError("Current owned exposure differs from the closed-boundary risk book.")
            # Pure state counts use the valued UTC day, whereas durable counts
            # use authorization time. Refuse a cross-day clock mismatch; never
            # relabel either timestamp or modify the frozen pure engine.
            day = (candle.candle_open_ms + _HOUR_MS) // DAY_MS * DAY_MS
            if evaluated_at_ms // DAY_MS * DAY_MS != day:
                raise RuntimeStoreConflictError("LIVE authorization and valuation UTC days must agree.")
            verdicts = self.list_risk_verdicts()
            if verdicts and evaluated_at_ms < max(row.evaluated_at_ms for row in verdicts):
                raise RuntimeStoreConflictError("LIVE authorization time cannot regress.")
            consumed = sum(row.verdict is RiskVerdict.ALLOW and row.proposal_kind is RiskActionKind.ENTRY
                           and row.evaluated_at_ms // DAY_MS * DAY_MS == day for row in verdicts)
            with _risk_validation():
                state = advance_risk_state(configuration, previous.state(epoch.started_at_ms), book,
                                           candle.close, candle.candle_open_ms + _HOUR_MS)
                if state.entries_this_utc_day != consumed:
                    raise RuntimeStoreIntegrityError("Risk ENTRY count differs from retained authorization history.")
                evaluation = evaluate_risk(configuration, state, book, candle.close, proposal)
            authorized = proposed_action if evaluation.verdict is RiskVerdict.ALLOW else None
            accepted_decision, accepted_checkpoint = decision, expected_checkpoint
            if proposed_action is not None and authorized is None:
                accepted_decision = replace(decision, disposition=DecisionDisposition.WAIT, action_id=None)
                snapshot = transition_runtime_state(current.snapshot, RuntimeEvent(
                    RuntimeEventType.NO_CHANGE, desired_position=decision.desired_position))
                accepted_checkpoint = replace(expected_checkpoint, snapshot=snapshot)
            valuation = _risk_valuation(epoch, RiskValuationMode.LIVE, candle, book, evaluation.state, evidence)
            verdict = RiskVerdictRecord(candle.symbol, candle.timeframe, candle.candle_open_ms, epoch.epoch_id,
                valuation.valued_at_ms, epoch.risk_configuration_digest,
                None if proposal is None else proposal.kind, None if proposal is None else proposal.authorized_amount,
                evaluation.verdict, evaluation.reason, None if authorized is None else authorized.logical_action_id,
                evaluated_at_ms)
            self._insert("candles", _encode(candle))
            if authorized is not None:
                self._insert_prepared(authorized)
            self._insert("decisions", _encode(accepted_decision))
            self._insert("risk_valuations", _encode(valuation))
            self._insert("risk_verdicts", _encode(verdict))
            self._save_checkpoint(accepted_checkpoint, expected_sequence)
            self._validate_all()
        return True

    def _validate_risk_history(self):
        """Validate retained observations without replaying today's expanded fills.

        Each stored book is valued by the frozen pure engine. Its evidence hash
        identifies the facts accepted then, not all subsequently discovered fills.
        """
        connection = self._connection
        history = {}
        for table in _RISK_MODELS:
            count = connection.execute("SELECT count(*) FROM " + table).fetchone()[0]
            if count > _MAX_ROWS:
                raise RuntimeStoreIntegrityError("Risk history exceeds the supported complete-read bound.")
            history[table] = tuple(_decode(table, row) for row in connection.execute("SELECT * FROM " + table))
        if not any(history.values()):
            return
        configurations = {row.risk_configuration_digest: row for row in history["risk_configurations"]}
        epochs = sorted(history["risk_epochs"], key=lambda row: row.epoch_sequence)
        valuations = history["risk_valuations"]
        verdicts = history["risk_verdicts"]
        if not configurations or not epochs or not valuations:
            raise RuntimeStoreIntegrityError("Partially initialized risk journal.")
        if set(configurations) != {epoch.risk_configuration_digest for epoch in epochs}:
            raise RuntimeStoreIntegrityError("Risk configuration history has an unbound epoch/configuration.")
        for record in configurations.values():
            self._risk_compatible(record.configuration)
        by_valuation = {(row.epoch_id, row.valued_at_ms): row for row in valuations}
        by_verdict = {(row.epoch_id, row.valued_at_ms): row for row in verdicts}
        entry_counts = {}
        prior_epoch = prior_final = None
        for sequence, epoch in enumerate(epochs, 1):
            if (epoch.epoch_sequence != sequence or epoch.parent_epoch_id != (None if prior_epoch is None else prior_epoch.epoch_id)
                    or (prior_epoch is not None and (
                        epoch.started_at_ms != prior_final.valued_at_ms
                        or epoch.risk_configuration_digest != prior_epoch.risk_configuration_digest))):
                raise RuntimeStoreIntegrityError("Risk epoch lineage is not consecutive.")
            rows = sorted((row for row in valuations if row.epoch_id == epoch.epoch_id), key=lambda row: row.valued_at_ms)
            if not rows or rows[0].valued_at_ms != epoch.started_at_ms:
                raise RuntimeStoreIntegrityError("Risk epoch requires its first activation valuation.")
            configuration = configurations[epoch.risk_configuration_digest].configuration
            previous = None
            for row in rows:
                candle = self.get_candle(row.candle_open_ms)
                if (row.risk_configuration_digest != epoch.risk_configuration_digest or candle is None
                        or row.symbol != self._configuration.symbol or row.timeframe != self._configuration.timeframe
                        or row.mark_price != candle.close):
                    raise RuntimeStoreIntegrityError("Risk epoch/configuration/candle binding mismatch.")
                if row.fill_evidence_count == 0 and row.fill_evidence_digest != _canonical_hash([]):
                    raise RuntimeStoreIntegrityError("Empty risk evidence digest mismatch.")
                with _risk_validation():
                    state = row.state(epoch.started_at_ms)
                    if previous is None:
                        if row.mode is not RiskValuationMode.ACTIVATION:
                            raise RuntimeStoreIntegrityError("First risk valuation must be ACTIVATION.")
                        if prior_epoch is None:
                            expected = initialize_risk_state(configuration, row.book, row.mark_price, row.valued_at_ms)
                        else:
                            if (row.book != prior_final.book or row.mark_price != prior_final.mark_price
                                    or (row.fill_evidence_count, row.fill_evidence_digest) != (
                                        prior_final.fill_evidence_count, prior_final.fill_evidence_digest)):
                                raise RuntimeStoreIntegrityError("Child activation must preserve the accepted parent book/mark/evidence.")
                            expected = rearm_risk_state(configuration, prior_final.state(prior_epoch.started_at_ms),
                                                        row.book, row.mark_price, row.valued_at_ms)
                    else:
                        if row.mode is RiskValuationMode.ACTIVATION or row.valued_at_ms != previous.valued_at_ms + _HOUR_MS:
                            raise RuntimeStoreIntegrityError("Risk valuation history must be consecutive within its epoch.")
                        if (row.fill_evidence_count < previous.fill_evidence_count
                                or (row.fill_evidence_count == previous.fill_evidence_count
                                    and row.fill_evidence_digest != previous.fill_evidence_digest)):
                            raise RuntimeStoreIntegrityError("Accepted owned-fill evidence cannot regress or change without added executions.")
                        expected = advance_risk_state(configuration, previous.state(epoch.started_at_ms),
                                                      row.book, row.mark_price, row.valued_at_ms)
                    verdict = by_verdict.get((row.epoch_id, row.valued_at_ms))
                    if row.mode is RiskValuationMode.LIVE:
                        if verdict is None:
                            raise RuntimeStoreIntegrityError("LIVE valuation requires its complete verdict transaction.")
                        proposal = None if verdict.proposal_kind is None else RiskActionProposal(verdict.proposal_kind, verdict.authorized_amount)
                        evaluation = evaluate_risk(configuration, expected, row.book, row.mark_price, proposal)
                        if (evaluation.verdict, evaluation.reason) != (verdict.verdict, verdict.reason):
                            raise RuntimeStoreIntegrityError("Risk verdict differs from the pure policy result.")
                        expected = evaluation.state
                        if verdict.evaluated_at_ms // DAY_MS * DAY_MS != row.utc_day_start_ms:
                            raise RuntimeStoreIntegrityError("Risk authorization and valuation UTC days differ.")
                        if verdict.verdict is RiskVerdict.ALLOW and verdict.proposal_kind is RiskActionKind.ENTRY:
                            entry_counts[row.utc_day_start_ms] = entry_counts.get(row.utc_day_start_ms, 0) + 1
                    elif verdict is not None:
                        raise RuntimeStoreIntegrityError("Historical risk valuation cannot authorize a decision.")
                    if state != expected:
                        raise RuntimeStoreIntegrityError("Risk valuation differs from its pure state transition.")
                    if state.entries_this_utc_day != entry_counts.get(row.utc_day_start_ms, 0):
                        raise RuntimeStoreIntegrityError("Risk ENTRY count differs from retained authorization history.")
                previous = row
            prior_epoch, prior_final = epoch, rows[-1]
        if {row.epoch_id for row in valuations} != {row.epoch_id for row in epochs}:
            raise RuntimeStoreIntegrityError("Risk valuation references unknown epoch history.")
        for verdict in verdicts:
            row = by_valuation.get((verdict.epoch_id, verdict.valued_at_ms))
            decision = self.get_decision(verdict.candle_open_ms)
            if (row is None or row.mode is not RiskValuationMode.LIVE or decision is None
                    or (verdict.symbol, verdict.timeframe, verdict.candle_open_ms, verdict.risk_configuration_digest) != (
                        row.symbol, row.timeframe, row.candle_open_ms, row.risk_configuration_digest)
                    or verdict.action_id != decision.action_id):
                raise RuntimeStoreIntegrityError("Risk verdict/valuation/decision binding mismatch.")
            if decision.disposition not in (DecisionDisposition.ACTION, DecisionDisposition.NOOP, DecisionDisposition.WAIT):
                raise RuntimeStoreIntegrityError("LIVE policy requires an operational decision disposition.")
            if verdict.proposal_kind is RiskActionKind.ENTRY and (
                    verdict.authorized_amount != self._configuration.buy_quote_budget
                    or decision.signal != "LONG_ENTRY" or decision.desired_position != 1):
                raise RuntimeStoreIntegrityError("Risk ENTRY must retain the exact frozen planner proposal.")
            if verdict.verdict is not RiskVerdict.ALLOW and verdict.proposal_kind is not None and (
                    decision.disposition is not DecisionDisposition.WAIT or row.owned_base_quantity != 0):
                raise RuntimeStoreIntegrityError("Refused ENTRY requires confirmed zero exposure and a no-action WAIT.")
            if verdict.action_id is not None:
                action = self.get_action(verdict.action_id)
                if (action is None or action.kind.value != verdict.proposal_kind.value
                        or action.authorized_amount != verdict.authorized_amount
                        or action.symbol != verdict.symbol or action.candle_open_ms != verdict.candle_open_ms):
                    raise RuntimeStoreIntegrityError("Risk ALLOW action binding mismatch.")
                from .planner import _canonical_intent
                if (hashlib.sha256(_canonical_intent(self._configuration, decision, action.kind,
                                                    action.authorized_amount)).hexdigest() != action.logical_action_id
                        or action.reconciliation_deadline_ms != decision.available_at_ms + self._configuration.reconciliation_timeout_ms):
                    raise RuntimeStoreIntegrityError("Risk action differs from canonical planner identity/timing.")
            if verdict.verdict is RiskVerdict.TRIP and verdict.reason is not row.trip_reason:
                raise RuntimeStoreIntegrityError("Risk TRIP must retain its valuation latch.")
        # Recheck the entire epoch, including its ACTIVATION anchor. This is
        # independent of the cycle's interpretation and also runs on reopen.
        from .risk_gate import refusal_frontiers
        for epoch in epochs:
            rows = sorted((row for row in valuations if row.epoch_id == epoch.epoch_id), key=lambda row: row.valued_at_ms)
            links = tuple((self.get_decision(row.candle_open_ms), row,
                           by_verdict.get((row.epoch_id, row.valued_at_ms))) for row in rows)
            actions = tuple(_decode("actions", action) for action in connection.execute("SELECT * FROM actions"))
            proved = refusal_frontiers(self._configuration, epoch, links, actions)
            for decision, row, verdict in links:
                if (row.mode is RiskValuationMode.LIVE and row.owned_base_quantity == 0
                        and decision.signal == "HOLD" and decision.desired_position == 1
                        and decision.disposition is DecisionDisposition.NOOP
                        and row.candle_open_ms not in proved):
                    raise RuntimeStoreIntegrityError("LIVE refused-intent HOLD lacks complete durable provenance.")

    def _validate_all(self):
        self._verify_settings()
        connection = self._connection
        try:
            legacy = getattr(self, "_legacy_validation", False)
            if connection.execute("PRAGMA user_version").fetchone()[0] != (1 if legacy else SCHEMA_VERSION):
                raise RuntimeStoreIntegrityError("Unsupported runtime database version.")
            schema = {row[0]: row[1] for row in connection.execute("SELECT name,sql FROM sqlite_master WHERE sql IS NOT NULL")}
            expected_schema = {**_SCHEMA_V1, **_INDEXES_V1} if legacy else {**_SCHEMA, **_INDEXES}
            if schema != expected_schema:
                raise RuntimeStoreIntegrityError("Runtime schema/tables/indexes do not match the supported version.")
            if [row[0] for row in connection.execute("PRAGMA quick_check(1)")] != ["ok"] or connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise RuntimeStoreIntegrityError("SQLite integrity/reference check failed.")
            for table in (*_MODELS, "checkpoint"):
                count = connection.execute("SELECT count(*) FROM " + table).fetchone()[0]
                if count > _MAX_ROWS or (table in {"identity", "checkpoint"} and count != 1):
                    raise RuntimeStoreIntegrityError("Runtime record count is unsafe or incomplete.")
                for row in connection.execute("SELECT * FROM " + table):
                    record = _decode(table, row, legacy=legacy)
                    if table == "candles":
                        self._check_instrument(record)
                    if table == "actions":
                        self._check_action_binding(record)
            self._validate_relations()
            self._validate_bounds()
            if not legacy:
                self._validate_risk_history()
        except sqlite3.Error:
            raise RuntimeStoreIntegrityError("SQLite runtime integrity validation failed.") from None

    def _check_instrument(self, record):
        if record.symbol != self._configuration.symbol or record.timeframe != self._configuration.timeframe or record.candle_open_ms < self._configuration.history_anchor_ms:
            raise RuntimeStoreConflictError("Candle/decision does not match the anchored instrument.")

    def _validate_bounds(self):
        # Refuse a write that would produce a store our bounded loader rejects.
        tables = _SCHEMA_V1 if getattr(self, "_legacy_validation", False) else _SCHEMA
        for table in tables:
            if self._connection.execute("SELECT count(*) FROM " + table).fetchone()[0] > _MAX_ROWS:
                raise RuntimeStoreIntegrityError("Runtime record count exceeds the supported bound.")
        pages = self._connection.execute("PRAGMA page_count").fetchone()[0]
        page_size = self._connection.execute("PRAGMA page_size").fetchone()[0]
        if pages * page_size > _MAX_DATABASE_BYTES:
            raise RuntimeStoreIntegrityError("Runtime database exceeds the supported size bound.")

    def _check_action_binding(self, action):
        config = self._configuration
        if action.symbol != config.symbol or action.remaining_reconciliation_rounds > config.reconciliation_round_limit or action.remaining_read_attempts > config.read_attempt_limit:
            raise RuntimeStoreConflictError("Action does not match the runtime binding/bounds.")
        if action.kind != JournalActionKind.CANCEL:
            currency = config.quote_currency if action.kind == JournalActionKind.ENTRY else config.base_currency
            if action.currency != currency or action.order_link_id != config.bot_id + "-" + action.logical_action_id[:23]:
                raise RuntimeStoreConflictError("Action currency/original link binding mismatch.")

    def _validate_relations(self):
        connection = self._connection
        checkpoint = self._one("checkpoint")
        if checkpoint is None or self._one("identity") != self._configuration:
            raise RuntimeStoreIntegrityError("Runtime identity/checkpoint is missing or inconsistent.")
        config = self._configuration
        decisions = connection.execute("SELECT count(*),min(candle_open_ms),max(candle_open_ms) FROM decisions").fetchone()
        count, first, latest = decisions
        if count > _MAX_ROWS or checkpoint.last_processed_candle_ms != latest or (count and (first != config.history_anchor_ms or latest != first + (count - 1) * _HOUR_MS)):
            raise RuntimeStoreIntegrityError("Checkpoint/frontier or contiguous decision history mismatch.")
        if latest is not None and self.get_decision(latest).desired_position != checkpoint.snapshot.desired_position:
            raise RuntimeStoreIntegrityError("Checkpoint desired intent differs from the latest decision.")
        if connection.execute("SELECT 1 FROM decisions d JOIN candles c USING(symbol,timeframe,candle_open_ms) WHERE d.input_fingerprint<>c.input_fingerprint OR d.symbol<>? OR d.timeframe<>? LIMIT 1", (config.symbol, config.timeframe)).fetchone():
            raise RuntimeStoreIntegrityError("Decision/candle fingerprint binding mismatch.")
        unresolved = [_decode("actions", row) for row in connection.execute("SELECT * FROM actions WHERE kind<>'CANCEL' AND phase IN ('PREPARED','ATTEMPT_STARTED','ACKNOWLEDGED','UNKNOWN_OUTCOME')")]
        pending = checkpoint.snapshot.pending_action
        if len(unresolved) > 1 or bool(unresolved) != (pending is not None):
            raise RuntimeStoreIntegrityError("Checkpoint must retain the one unresolved placement.")
        if unresolved and (pending.logical_action_id != unresolved[0].logical_action_id or pending.kind.value != unresolved[0].kind.value):
            raise RuntimeStoreIntegrityError("Checkpoint pending action identity/kind mismatch.")
        if connection.execute("SELECT 1 FROM actions WHERE phase='UNKNOWN_OUTCOME' LIMIT 1").fetchone() and checkpoint.snapshot.state not in (RuntimeState.STARTING, RuntimeState.SYNCHRONIZING, RuntimeState.UNCERTAIN, RuntimeState.HALTED, RuntimeState.STOPPING):
            # A lost receipt stays missing even after exact pending-order discovery.
            # Ownership/freshness/fill completeness remain caller assertions. The
            # identity checks above bind the sole placement to this checkpoint.
            observed_pending = (
                checkpoint.snapshot.state == RuntimeState.ORDER_PENDING
                and len(unresolved) == 1
                and unresolved[0].phase == ActionPhase.UNKNOWN_OUTCOME
                and unresolved[0].attempt_count == 1
                and unresolved[0].broker_order_id is not None
                and unresolved[0].observed_at_ms is not None
                and unresolved[0].order_status in {"OPEN", "PARTIALLY_FILLED"}
                # Observing a parent order does not resolve a lost cancel receipt.
                and connection.execute("SELECT 1 FROM actions WHERE kind='CANCEL' AND phase='UNKNOWN_OUTCOME' LIMIT 1").fetchone() is None
            )
            if not observed_pending:
                raise RuntimeStoreIntegrityError("Unknown action outcome cannot retain confirmed operational certainty.")
        if connection.execute("""SELECT 1 FROM actions c LEFT JOIN actions p ON c.parent_action_id=p.logical_action_id
            WHERE c.kind='CANCEL' AND (p.logical_action_id IS NULL OR p.kind='CANCEL'
            OR c.target_broker_order_id IS NOT p.broker_order_id OR
            (c.phase IN ('PREPARED','ATTEMPT_STARTED','ACKNOWLEDGED','UNKNOWN_OUTCOME')
             AND p.phase IN ('TERMINAL_CONFIRMED','REJECTED','ABANDONED_UNSENT'))) LIMIT 1""").fetchone():
            raise RuntimeStoreIntegrityError("Cancellation control must retain its exactly known parent lifecycle.")
        if connection.execute("""SELECT 1 FROM actions a LEFT JOIN decisions d
            ON a.symbol=d.symbol AND a.candle_open_ms=d.candle_open_ms AND d.timeframe=?
            WHERE a.kind<>'CANCEL' AND (d.action_id IS NOT a.logical_action_id
            OR d.signal<>CASE WHEN a.kind='ENTRY' THEN 'LONG_ENTRY' ELSE 'LONG_EXIT' END) LIMIT 1""", (config.timeframe,)).fetchone():
            raise RuntimeStoreIntegrityError("Placement must bind its original canonical decision.")
        if connection.execute("SELECT 1 FROM fills f JOIN actions a ON f.action_id=a.logical_action_id WHERE f.symbol<>a.symbol OR f.side<>a.side OR a.kind='CANCEL' OR a.phase IN ('PREPARED','REJECTED','ABANDONED_UNSENT') LIMIT 1").fetchone():
            raise RuntimeStoreIntegrityError("Fill/action ownership or phase mismatch.")
        if connection.execute("SELECT 1 FROM fills f JOIN actions a ON f.action_id=a.logical_action_id WHERE a.phase='TERMINAL_CONFIRMED' AND f.execution_fee<>'0' AND f.fee_currency IS NULL LIMIT 1").fetchone():
            raise RuntimeStoreIntegrityError("Unknown nonzero fee currency prevents terminal ownership settlement.")
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise RuntimeStoreIntegrityError("Broken durable reference.")

    def _save_checkpoint(self, checkpoint, expected_sequence):
        _require(isinstance(checkpoint, RuntimeCheckpoint), "Validated checkpoint required.")
        _integer(expected_sequence)
        current = self._one("checkpoint")
        if current.sequence != expected_sequence or checkpoint.sequence != expected_sequence + 1:
            raise RuntimeStoreConflictError("Stale or nonconsecutive checkpoint sequence.")
        for name in ("last_processed_candle_ms", "last_reconciled_at_ms", "observed_at_ms", "rearmed_at_ms", "bootstrap_until_ms", "replay_until_ms"):
            old, new = getattr(current, name), getattr(checkpoint, name)
            if old is not None and (new is None or new < old):
                raise RuntimeStoreConflictError("Durable frontier/observation cannot regress.")
        halt_latched = current.snapshot.state == RuntimeState.HALTED or current.snapshot.stopped_from == RuntimeState.HALTED
        if halt_latched:
            if checkpoint.snapshot.state in (RuntimeState.HALTED, RuntimeState.STOPPING):
                if checkpoint.halted_at_ms != current.halted_at_ms or (checkpoint.snapshot.state == RuntimeState.STOPPING and checkpoint.snapshot.stopped_from != RuntimeState.HALTED):
                    raise RuntimeStoreConflictError("HALT latch/time cannot be erased by shutdown or repeated HALT.")
            elif checkpoint.snapshot.state != RuntimeState.SYNCHRONIZING or checkpoint.rearmed_at_ms is None or checkpoint.rearmed_at_ms <= current.halted_at_ms:
                raise RuntimeStoreConflictError("HALT requires explicit recorded rearm through synchronization.")
        self._update("checkpoint", _checkpoint_values(checkpoint), "singleton", 1)

    def save_checkpoint(self, checkpoint: RuntimeCheckpoint, *, expected_sequence: int) -> None:
        """Compare-and-save; no frontier advance without its committed decision."""
        with self._transaction():
            self._save_checkpoint(checkpoint, expected_sequence)

    def commit_decision(self, candle: CandleRecord, decision: DecisionRecord, checkpoint: RuntimeCheckpoint, *, expected_sequence: int, action: ActionRecord | None = None) -> bool:
        """Atomic candle + decision + optional PREPARED action + frontier.

        Exact decision replay returns False and performs no checkpoint write.
        It does not claim the supplied checkpoint was applied. New records return
        True only after commit. Missing hours/conflicting replays fail explicitly.
        """
        _require(isinstance(candle, CandleRecord) and isinstance(decision, DecisionRecord) and isinstance(checkpoint, RuntimeCheckpoint), "Validated candle/decision/checkpoint records required.")
        _integer(expected_sequence)
        if action is not None:
            _require(isinstance(action, ActionRecord), "Validated action required.")
        self._check_instrument(candle)
        self._check_instrument(decision)
        if (candle.candle_open_ms, candle.input_fingerprint) != (decision.candle_open_ms, decision.input_fingerprint):
            raise RuntimeStoreConflictError("Decision does not match its accepted candle.")
        with self._transaction():
            prior = self.get_decision(decision.candle_open_ms)
            if prior is not None:
                if prior != decision or self.get_candle(candle.candle_open_ms) != candle:
                    raise RuntimeStoreConflictError("Conflicting committed candle/decision replay.")
                if action is not None:
                    saved = self.get_action(action.logical_action_id)
                    if saved is None or any(getattr(saved, name) != getattr(action, name) for name in _INTENT_FIELDS):
                        raise RuntimeStoreConflictError("Replay cannot replace the original action.")
                return False
            current = self._one("checkpoint")
            next_candle = self._configuration.history_anchor_ms if current.last_processed_candle_ms is None else current.last_processed_candle_ms + _HOUR_MS
            if decision.candle_open_ms != next_candle or checkpoint.last_processed_candle_ms != next_candle or checkpoint.snapshot.desired_position != decision.desired_position:
                raise RuntimeStoreConflictError("New decision must advance the contiguous frontier and matching intent.")
            cutoffs = tuple(value for value in (current.bootstrap_until_ms, current.replay_until_ms) if value is not None)
            if (cutoffs and decision.candle_open_ms > max(cutoffs)
                    and decision.disposition in (DecisionDisposition.ACTION, DecisionDisposition.NOOP, DecisionDisposition.WAIT)):
                raise RuntimeStoreConflictError("Classified LIVE work requires atomic risk authorization.")
            self._insert("candles", _encode(candle))
            if decision.action_id is not None:
                _require(isinstance(action, ActionRecord), "ACTION decision requires a prepared action.")
                if action.logical_action_id != decision.action_id or action.candle_open_ms != decision.candle_open_ms or action.kind == JournalActionKind.CANCEL:
                    raise RuntimeStoreConflictError("Prepared intent/decision binding mismatch.")
                self._insert_prepared(action)
            elif action is not None:
                raise RuntimeStoreConflictError("Non-action decision cannot authorize an action.")
            self._insert("decisions", _encode(decision))
            self._save_checkpoint(checkpoint, expected_sequence)
        return True

    def _insert_prepared(self, action):
        _require(isinstance(action, ActionRecord) and action.phase == ActionPhase.PREPARED, "Only fresh PREPARED intents may be inserted.")
        self._check_action_binding(action)
        self._insert("actions", _encode(action))

    def prepare_cancellation(self, action: ActionRecord, checkpoint: RuntimeCheckpoint, *, expected_sequence: int) -> None:
        """Store explicit caller control only; no cancellation is sent."""
        _require(isinstance(action, ActionRecord) and action.kind == JournalActionKind.CANCEL, "Explicit cancellation control required.")
        with self._transaction():
            current = self._one("checkpoint")
            if current.snapshot.state != RuntimeState.ORDER_PENDING or current.snapshot.pending_action.logical_action_id != action.parent_action_id:
                raise RuntimeStoreConflictError("Cancellation needs the reconciled pending parent lifecycle.")
            self._insert_prepared(action)
            self._save_checkpoint(checkpoint, expected_sequence)

    def _change_action(self, action):
        _require(isinstance(action, ActionRecord), "Validated action observation required.")
        previous = self.get_action(action.logical_action_id)
        if previous is None or any(getattr(previous, name) != getattr(action, name) for name in _INTENT_FIELDS):
            raise RuntimeStoreConflictError("Action intent/identity cannot be replaced.")
        if action == previous:
            return
        if action.phase not in _PHASE_TRANSITIONS[previous.phase]:
            raise RuntimeStoreConflictError("Forbidden persisted action phase transition.")
        for name in ("broker_order_id", "submitted_amount", "acknowledgement_broker_ms", "acknowledgement_observed_ms"):
            old = getattr(previous, name)
            if old is not None and getattr(action, name) != old:
                raise RuntimeStoreConflictError("Previously observed acknowledgement cannot be erased/rebound.")
        if action.remaining_reconciliation_rounds > previous.remaining_reconciliation_rounds or action.remaining_read_attempts > previous.remaining_read_attempts:
            raise RuntimeStoreConflictError("Recovery bounds cannot be reset.")
        if previous.observed_at_ms is not None and (action.observed_at_ms is None or action.observed_at_ms < previous.observed_at_ms):
            raise RuntimeStoreConflictError("Order observations cannot move backwards.")
        self._update("actions", _encode(action), "logical_action_id", action.logical_action_id)

    def start_attempt(self, action_id: str, checkpoint: RuntimeCheckpoint, *, expected_sequence: int) -> None:
        """Durably mark the single possible send BEFORE any future broker call."""
        with self._transaction():
            action = self.get_action(action_id)
            if action is None or action.phase != ActionPhase.PREPARED:
                raise RuntimeStoreConflictError("Only an unsent PREPARED action may start one attempt.")
            if self._one("checkpoint").snapshot.state != RuntimeState.ORDER_PENDING:
                raise RuntimeStoreConflictError("Unsafe operational state cannot start an action attempt.")
            self._change_action(replace(action, phase=ActionPhase.ATTEMPT_STARTED, attempt_count=1))
            self._save_checkpoint(checkpoint, expected_sequence)

    def abandon_prepared(self, action_id: str, checkpoint: RuntimeCheckpoint, *, expected_sequence: int, terminal_at_ms: int) -> None:
        """Retain consumed IDs while retiring only a provably unsent intent."""
        with self._transaction():
            action = self.get_action(action_id)
            if action is None or action.phase != ActionPhase.PREPARED:
                raise RuntimeStoreConflictError("Attempted action cannot be abandoned as unsent.")
            self._change_action(replace(action, phase=ActionPhase.ABANDONED_UNSENT, terminal_at_ms=terminal_at_ms))
            self._save_checkpoint(checkpoint, expected_sequence)

    def record_observation(self, action: ActionRecord, checkpoint: RuntimeCheckpoint, *, expected_sequence: int, fills: tuple[OwnedFillRecord, ...] = ()) -> None:
        """Atomic supplied receipt/status/fills/terminal evidence + checkpoint.

        Exact duplicate executions are retained once; conflicting duplicates
        roll back every related change. No inventory or fill is calculated here.
        Terminal completeness is a caller assertion, not broker proof.
        """
        _require(type(fills) is tuple and all(isinstance(fill, OwnedFillRecord) for fill in fills), "Immutable supplied fill records required.")
        _require(len(fills) <= _MAX_BATCH_FILLS, "Supplied fill batch exceeds the supported bound.")
        _require(isinstance(action, ActionRecord), "Validated action observation required.")
        with self._transaction():
            previous = self.get_action(action.logical_action_id)
            if previous is None or previous.phase == ActionPhase.PREPARED or action.phase in (ActionPhase.PREPARED, ActionPhase.ATTEMPT_STARTED, ActionPhase.ABANDONED_UNSENT):
                raise RuntimeStoreConflictError("Observation cannot bypass the durable attempt marker.")
            self._change_action(action)
            for fill in fills:
                if fill.action_id != action.logical_action_id or fill.broker_id != self._configuration.broker_id or fill.account_binding != self._configuration.account_binding:
                    raise RuntimeStoreConflictError("Supplied fill has a different owned identity.")
                saved = self.get_fill(fill.broker_execution_id)
                if saved is not None:
                    if any(getattr(saved, field.name) != getattr(fill, field.name) for field in fields(fill) if field.name != "observed_at_ms"):
                        raise RuntimeStoreConflictError("Conflicting duplicate owned execution.")
                else:
                    if previous.phase in _TERMINAL_PHASES:
                        raise RuntimeStoreConflictError("Completed evidence cannot acquire an unrecorded late fill.")
                    self._insert("fills", _encode(fill))
            self._save_checkpoint(checkpoint, expected_sequence)

    def close(self) -> None:
        try:
            if self._connection is not None:
                self._connection.close()
        except sqlite3.Error:
            raise RuntimeStoreError("Cannot close runtime store.") from None
        finally:
            self._connection = None
            if self._attached:
                self._lock._stores -= 1
                remaining = _OPEN_DATABASES[self._database_path] - 1
                if remaining:
                    _OPEN_DATABASES[self._database_path] = remaining
                else:
                    del _OPEN_DATABASES[self._database_path]
                self._attached = False

    def __enter__(self):
        self._live()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
