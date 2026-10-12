"""Local SQLite journal primitives under Decision 017, never orchestration.

Caller supplies validated facts and checkpoints. This layer binds references,
preserves exact money and commits related records together; it does not discover
ownership, calculate inventory/PnL, authorize orders, or verify broker finality.
Use RuntimeAccountLock first, then open the store; close the store before the
lock. Fresh initialization is explicit and refuses every existing file.
"""

from contextlib import contextmanager
from dataclasses import dataclass, fields, replace
from decimal import Decimal, InvalidOperation
from enum import Enum
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import sys

from .locking import RuntimeAccountLock
from .state import (
    PendingAction, PendingActionKind, PositionEvidence, RuntimeReason,
    RuntimeState, RuntimeStateError, RuntimeStateSnapshot,
)

SCHEMA_VERSION = 1
RUNTIME_CONTRACT_VERSION = 1
_HOUR_MS = 3_600_000
_MAX_ROWS = 100_000  # Bounded full validation; no truncation/partial success.
_MAX_DATABASE_BYTES = 256 * 1024 * 1024
_MAX_BATCH_FILLS = 10_000
_MAX_DECIMAL_CHARS = 4096


class RuntimeStoreError(RuntimeError):
    """Safe persistence/record diagnostic; no raw SQL, file or exception text."""


class RuntimeStoreIntegrityError(RuntimeStoreError):
    """Unsupported, malformed or inconsistent durable evidence."""


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
        _require(self.schema_version == SCHEMA_VERSION and self.runtime_contract_version == RUNTIME_CONTRACT_VERSION, "Unsupported runtime schema/contract version.")


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


# Explicit columns: all financial values are TEXT, all time/sequence values INTEGER.
_SCHEMA = {
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
_INDEXES = {
    "one_pending_placement": "CREATE UNIQUE INDEX one_pending_placement ON actions((1)) WHERE kind IN ('ENTRY','EXIT') AND phase IN ('PREPARED','ATTEMPT_STARTED','ACKNOWLEDGED','UNKNOWN_OUTCOME')",
    "one_pending_cancel": "CREATE UNIQUE INDEX one_pending_cancel ON actions(parent_action_id) WHERE kind='CANCEL' AND phase IN ('PREPARED','ATTEMPT_STARTED','ACKNOWLEDGED','UNKNOWN_OUTCOME')",
}
_MODELS = {"identity": RuntimeConfiguration, "candles": CandleRecord, "decisions": DecisionRecord, "actions": ActionRecord, "fills": OwnedFillRecord}
_DECIMALS = {
    "identity": {"buy_quote_budget"}, "candles": {"open", "high", "low", "close", "volume"},
    "actions": {"authorized_amount", "submitted_amount"},
    "fills": {"executed_quantity", "execution_price", "execution_fee"}, "checkpoint": {"owned_base_quantity"},
}
_ENUMS = {"actions": {"kind": JournalActionKind, "phase": ActionPhase, "safe_reason": RuntimeReason}, "decisions": {"disposition": DecisionDisposition}}


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


def _decode(table, row):
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
        return _MODELS[table](**values)
    except (RuntimeStoreError, RuntimeStateError, ValueError, TypeError, KeyError):
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
                if schema != {**_SCHEMA, **_INDEXES} or instance._connection.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION or instance._connection.execute("PRAGMA journal_mode").fetchone()[0] != "delete":
                    raise RuntimeStoreIntegrityError("Existing runtime schema/version/journal is unsupported.")
            instance._configure()
            if initialize:
                with instance._transaction(validate=False):
                    for sql in (*_SCHEMA.values(), *_INDEXES.values()):
                        instance._connection.execute(sql)
                    instance._connection.execute("PRAGMA user_version=1")
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
            lock._stores += 1
            instance._attached = True
            return instance
        except (OSError, sqlite3.Error):
            instance.close()
            raise RuntimeStoreIntegrityError("Cannot open/initialize the runtime store safely.") from None
        except RuntimeStoreError:
            instance.close()
            raise

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
            return None if row is None else _decode(table, row)
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

    def _validate_all(self):
        self._verify_settings()
        connection = self._connection
        try:
            if connection.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
                raise RuntimeStoreIntegrityError("Unsupported runtime database version.")
            schema = {row[0]: row[1] for row in connection.execute("SELECT name,sql FROM sqlite_master WHERE sql IS NOT NULL")}
            if schema != {**_SCHEMA, **_INDEXES}:
                raise RuntimeStoreIntegrityError("Runtime schema/tables/indexes do not match version 1.")
            if [row[0] for row in connection.execute("PRAGMA quick_check(1)")] != ["ok"] or connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise RuntimeStoreIntegrityError("SQLite integrity/reference check failed.")
            for table in (*_MODELS, "checkpoint"):
                count = connection.execute("SELECT count(*) FROM " + table).fetchone()[0]
                if count > _MAX_ROWS or (table in {"identity", "checkpoint"} and count != 1):
                    raise RuntimeStoreIntegrityError("Runtime record count is unsafe or incomplete.")
                for row in connection.execute("SELECT * FROM " + table):
                    record = _decode(table, row)
                    if table == "candles":
                        self._check_instrument(record)
                    if table == "actions":
                        self._check_action_binding(record)
            self._validate_relations()
        except sqlite3.Error:
            raise RuntimeStoreIntegrityError("SQLite runtime integrity validation failed.") from None

    def _check_instrument(self, record):
        if record.symbol != self._configuration.symbol or record.timeframe != self._configuration.timeframe or record.candle_open_ms < self._configuration.history_anchor_ms:
            raise RuntimeStoreConflictError("Candle/decision does not match the anchored instrument.")

    def _validate_bounds(self):
        # Refuse a write that would produce a store our bounded loader rejects.
        for table in (*_MODELS, "checkpoint"):
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
        if connection.execute("SELECT 1 FROM actions WHERE phase='UNKNOWN_OUTCOME' LIMIT 1").fetchone() and checkpoint.snapshot.state not in (RuntimeState.SYNCHRONIZING, RuntimeState.UNCERTAIN, RuntimeState.HALTED, RuntimeState.STOPPING):
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
        if self._connection is not None:
            try:
                self._connection.close()
            except sqlite3.Error:
                raise RuntimeStoreError("Cannot close runtime store.") from None
            finally:
                self._connection = None
        if self._attached:
            self._lock._stores -= 1
            self._attached = False

    def __enter__(self):
        self._live()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
