"""Closed, exact, non-authoritative event records under Decision 023.

Only our own explicitly listed fields are serialized. No object/exception dump
API exists. Process IDs correlate observations; durable IDs identify facts.
"""

from dataclasses import dataclass, replace
from decimal import Decimal
from enum import Enum
import hashlib
import json
import re
import uuid

from ..runtime.state import RuntimeReason, RuntimeState, PositionEvidence
from ..runtime.store import (
    ActionPhase, JournalActionKind, RuntimeConfiguration, RiskValuationMode,
    serialize_decimal, deserialize_decimal, RuntimeStoreError,
)
from ..risk.runtime_risk import RiskReason, RiskVerdict, RiskActionKind

OBSERVABILITY_CONTRACT_VERSION = 1
MAX_SUMMARY_CHARS = 128
MAX_SAFE_CHARS = 64
MAX_EVENT_BYTES = 131_072
MAX_CANDLES = 10_000
MAX_EXECUTIONS = 256
MAX_FILLS = 128
MAX_RETAINED_RECORDS = 10_000


class ObservabilityError(ValueError):
    """Fixed safe diagnostic; never retains a supplied object or message."""


class ObservabilityValidationError(ObservabilityError):
    """A derived record/encoding is invalid."""


class ObservabilityProjectionError(ObservabilityError):
    """Available public facts cannot establish a coherent projection."""


class ObservabilityStorageError(ObservabilityError):
    """Local derived storage is unavailable or invalid."""


class ObservabilitySeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class ObservabilityHealthLevel(str, Enum):
    OK = "OK"
    ATTENTION = "ATTENTION"
    CRITICAL = "CRITICAL"


class EvidenceFreshness(str, Enum):
    FRESH = "FRESH"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"


class ObservabilityEventType(str, Enum):
    PROCESS_STARTED = "PROCESS_STARTED"
    PROCESS_STOPPED = "PROCESS_STOPPED"
    SCHEDULER_STARTED = "SCHEDULER_STARTED"
    SCHEDULER_EXITED = "SCHEDULER_EXITED"
    CYCLE_COMPLETED = "CYCLE_COMPLETED"
    CRITICAL_FAILURE = "CRITICAL_FAILURE"
    MARKET_DATA_STALE = "MARKET_DATA_STALE"
    RECONCILIATION_DEGRADED = "RECONCILIATION_DEGRADED"
    RECONCILIATION_CONFIRMED = "RECONCILIATION_CONFIRMED"
    ACTION_PREPARED = "ACTION_PREPARED"
    ACTION_ATTEMPT_STARTED = "ACTION_ATTEMPT_STARTED"
    ACTION_ACKNOWLEDGED = "ACTION_ACKNOWLEDGED"
    ACTION_UNKNOWN_OUTCOME = "ACTION_UNKNOWN_OUTCOME"
    ACTION_TERMINAL_CONFIRMED = "ACTION_TERMINAL_CONFIRMED"
    ACTION_REJECTED = "ACTION_REJECTED"
    ACTION_ABANDONED_UNSENT = "ACTION_ABANDONED_UNSENT"
    OWNED_EXECUTION_DISCOVERED = "OWNED_EXECUTION_DISCOVERED"
    POSITION_OPEN_CONFIRMED = "POSITION_OPEN_CONFIRMED"
    POSITION_CLOSE_CONFIRMED = "POSITION_CLOSE_CONFIRMED"
    POSITION_QUANTITY_CHANGED = "POSITION_QUANTITY_CHANGED"
    RISK_NOT_READY = "RISK_NOT_READY"
    RISK_BLOCKED = "RISK_BLOCKED"
    RISK_TRIPPED = "RISK_TRIPPED"
    RISK_REARMED = "RISK_REARMED"
    RUNTIME_HALTED = "RUNTIME_HALTED"
    RUNTIME_UNCERTAIN = "RUNTIME_UNCERTAIN"
    RUNTIME_REARMED = "RUNTIME_REARMED"
    OBSERVABILITY_DEGRADED = "OBSERVABILITY_DEGRADED"


T = ObservabilityEventType
ENVELOPE_FIELDS = tuple("""observability_version event_id event_type severity source
occurred_at_ms observed_at_ms run_id broker_id account_binding bot_id strategy_id
symbol timeframe checkpoint_sequence runtime_state runtime_reason risk_epoch_id
risk_epoch_sequence risk_trip_reason candle_open_ms action_id broker_order_id summary""".split())


def require(condition):
    if not condition:
        raise ObservabilityValidationError("Invalid bounded observability record.")


def integer(value, minimum=0):
    require(type(value) is int and minimum <= value <= 2**63 - 1)


def safe_text(value, limit=MAX_SAFE_CHARS):
    require(type(value) is str and re.fullmatch(r"[A-Za-z0-9_-]{1," + str(limit) + "}", value) is not None)


def validate_strategy_id(value):
    """Derived identity only; this does not authorize a runtime strategy."""
    require(type(value) is str and re.fullmatch(r"[a-z][a-z0-9_]{0,31}", value) is not None)


def digest(value):
    require(type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None)


def validate_run_id(value):
    require(type(value) is str and re.fullmatch(r"[0-9a-f]{32}", value) is not None)


def new_run_id() -> str:
    return uuid.uuid4().hex


def canonical_bytes(value) -> bytes:
    """Internal encoder for already validated, explicitly assembled primitives."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("utf-8")


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result)
        result[key] = value
    return result


def parse_object(data: bytes, maximum: int):
    require(type(data) is bytes and 0 < len(data) <= maximum)
    try:
        result = json.loads(data.decode("utf-8"), object_pairs_hook=_pairs,
                            parse_constant=lambda _: require(False))
        require(type(result) is dict)
        return result
    except (UnicodeError, ValueError, TypeError, RecursionError):
        raise ObservabilityValidationError("Invalid observability JSON.") from None


# A field's kind is explicit, rather than introspecting arbitrary objects.
DECIMAL_FIELDS = set("""authorized_amount submitted_amount executed_quantity execution_price
execution_fee previous_owned_base_quantity owned_base_quantity realized_trade_pnl_quote
latest_mark_price mark_price risk_equity peak_risk_equity utc_day_start_risk_equity
daily_pnl risk_capital_quote buy_quote_budget max_entry_notional_quote
max_position_notional_quote max_daily_loss_fraction max_drawdown_fraction
latest_accepted_mark_price drawdown_numerator drawdown_denominator""".split())
ENUM_FIELDS = {
    "runtime_state": RuntimeState, "runtime_reason": RuntimeReason,
    "position_evidence": PositionEvidence, "action_kind": JournalActionKind,
    "action_phase": ActionPhase, "safe_reason": RuntimeReason,
    "risk_trip_reason": RiskReason, "risk_reason": RiskReason, "risk_verdict": RiskVerdict,
    "proposal_kind": RiskActionKind, "valuation_mode": RiskValuationMode,
    "previous_runtime_state": RuntimeState,
}
CHOICES = {
    "side": {"BUY", "SELL"}, "amount_unit": {"BASE", "QUOTE"},
    "order_status": {"NEW", "OPEN", "PARTIALLY_FILLED", "FILLED", "CANCELLED", "REJECTED", "EXPIRED", "UNKNOWN"},
    "cycle_outcome": {"BOOTSTRAP", "REPLAY_ONLY", "NO_NEW_DATA", "NOOP", "WAIT", "RECONCILE", "HALTED", "STOPPING", "OBSERVED", "ABANDONED_UNSENT", "RISK_NOT_READY", "RISK_BLOCKED", "RISK_TRIPPED"},
    "planner_kind": {"NOOP", "PLACE_BUY", "PLACE_SELL", "WAIT", "RECONCILE", "HALT"},
    "scheduler_exit_reason": {"STOP_REQUESTED", "HALTED", "STOPPING"},
    "last_cycle_outcome": {"BOOTSTRAP", "REPLAY_ONLY", "NO_NEW_DATA", "NOOP", "WAIT", "RECONCILE", "HALTED", "STOPPING", "OBSERVED", "ABANDONED_UNSENT", "RISK_NOT_READY", "RISK_BLOCKED", "RISK_TRIPPED"},
}
ACTION_FIELDS = tuple("""action_kind action_phase order_link_id parent_action_id target_broker_order_id
side amount_unit currency authorized_amount submitted_amount attempt_count acknowledgement_broker_ms
acknowledgement_observed_ms order_status external_status terminal_at_ms safe_reason rejection_code""".split())
EXECUTION_FIELDS = tuple("""broker_execution_id order_link_id side executed_quantity execution_price
execution_fee fee_currency executed_at_ms first_observed_at_ms""".split())
POSITION_FIELDS = tuple("""position_evidence previous_owned_base_quantity owned_base_quantity pending_action_id
order_link_id contributing_execution_ids entry_time_ms exit_time_ms entry_fills exit_fills realized_trade_pnl_quote""".split())
RISK_FIELDS = tuple("""risk_configuration_digest valued_at_ms valuation_mode proposal_kind authorized_amount
risk_verdict risk_reason mark_price risk_equity peak_risk_equity utc_day_start_risk_equity daily_pnl
entries_this_utc_day max_entries_per_utc_day tripped_at_ms""".split())
ACTION_TYPES = {T("ACTION_" + phase.value): phase for phase in ActionPhase}
POSITION_TYPES = {T.POSITION_OPEN_CONFIRMED, T.POSITION_CLOSE_CONFIRMED, T.POSITION_QUANTITY_CHANGED}
PROCESS_TYPES = {T.PROCESS_STARTED, T.PROCESS_STOPPED, T.SCHEDULER_STARTED, T.SCHEDULER_EXITED,
                 T.CYCLE_COMPLETED, T.CRITICAL_FAILURE, T.MARKET_DATA_STALE,
                 T.RECONCILIATION_DEGRADED, T.RISK_NOT_READY, T.OBSERVABILITY_DEGRADED}
PAYLOAD_FIELDS = {
    T.PROCESS_STARTED: ("process_started_at_ms",),
    T.PROCESS_STOPPED: ("process_started_at_ms", "process_stopped_at_ms", "stop_reason"),
    T.SCHEDULER_STARTED: ("scheduler_started_at_ms",),
    T.SCHEDULER_EXITED: ("scheduler_exit_reason", "cycle_count", "wake_count", "last_cycle_outcome"),
    T.CYCLE_COMPLETED: ("cycle_outcome", "processed_candle_count", "processed_candle_open_ms", "planner_kind", "new_execution_ids", "risk_verdict", "risk_reason"),
    T.CRITICAL_FAILURE: ("operation", "failure_kind", "exception_type", "safe_error_code"),
    T.MARKET_DATA_STALE: ("evidence_kind", "latest_accepted_candle_open_ms", "latest_mark_price", "evidence_observed_at_ms"),
    T.RECONCILIATION_DEGRADED: ("evidence_kind", "last_reconciled_at_ms", "last_broker_observation_at_ms", "pending_action_id"),
    T.RECONCILIATION_CONFIRMED: ("position_evidence", "owned_base_quantity", "pending_action_id", "last_reconciled_at_ms", "last_broker_observation_at_ms"),
    T.OWNED_EXECUTION_DISCOVERED: EXECUTION_FIELDS,
    T.RISK_NOT_READY: ("risk_active", "cycle_outcome"),
    T.RISK_BLOCKED: RISK_FIELDS, T.RISK_TRIPPED: RISK_FIELDS,
    T.RISK_REARMED: ("parent_epoch_id", "child_epoch_id", "accepted_boundary_ms", "risk_configuration_digest"),
    T.RUNTIME_HALTED: ("owned_base_quantity", "position_evidence", "pending_action_id", "halted_at_ms"),
    T.RUNTIME_UNCERTAIN: ("owned_base_quantity", "position_evidence", "pending_action_id", "action_phase"),
    T.RUNTIME_REARMED: ("rearmed_at_ms", "previous_runtime_state", "reconciliation_required"),
    T.OBSERVABILITY_DEGRADED: ("sink", "operation", "failure_kind", "exception_type", "safe_error_code"),
    **{kind: ACTION_FIELDS for kind in ACTION_TYPES}, **{kind: POSITION_FIELDS for kind in POSITION_TYPES},
}
_DIGEST_FIELDS = {"parent_action_id", "pending_action_id", "parent_epoch_id", "child_epoch_id", "risk_configuration_digest", "action_id"}
_COUNTS = {"attempt_count", "cycle_count", "wake_count", "processed_candle_count", "entries_this_utc_day", "max_entries_per_utc_day"}


def validate_value(name, value):
    if value is None:
        return
    if name in DECIMAL_FIELDS:
        require(type(value) is Decimal and value.is_finite())
        try:
            serialize_decimal(value)
        except (ValueError, RuntimeStoreError):
            raise ObservabilityValidationError("Invalid exact observability amount.") from None
        if name in {"previous_owned_base_quantity", "owned_base_quantity", "drawdown_numerator"}:
            require(value >= 0)
        elif name not in {"execution_fee", "daily_pnl", "realized_trade_pnl_quote"}:
            require(value > 0)
    elif name in ENUM_FIELDS:
        require(type(value) is ENUM_FIELDS[name])
    elif name in CHOICES:
        require(type(value) is str and value in CHOICES[name])
    elif name in _DIGEST_FIELDS:
        digest(value)
    elif name in {"risk_active", "reconciliation_required"}:
        require(type(value) is bool)
    elif name in {"processed_candle_open_ms", "new_execution_ids", "contributing_execution_ids"}:
        maximum = MAX_CANDLES if name == "processed_candle_open_ms" else MAX_EXECUTIONS
        require(type(value) is tuple and len(value) <= maximum)
        for item in value:
            integer(item) if name == "processed_candle_open_ms" else safe_text(item)
        require(len(set(value)) == len(value))
    elif name in {"entry_fills", "exit_fills"}:
        require(type(value) is tuple and len(value) <= MAX_FILLS)
        for fill in value:
            validate_details(EXECUTION_FIELDS + ("action_id", "broker_order_id"), fill)
    elif name.endswith("_ms") or name in _COUNTS:
        integer(value, 1 if name == "max_entries_per_utc_day" else 0)
    elif name == "rejection_code":
        require(type(value) is int and -(2**63) <= value < 2**63 and value != 0)
    else:
        safe_text(value, 36 if name == "order_link_id" else MAX_SAFE_CHARS)


def validate_details(allowed, details):
    require(type(details) is tuple and len(details) <= len(allowed))
    seen = set()
    for pair in details:
        require(type(pair) is tuple and len(pair) == 2)
        name, value = pair
        require(type(name) is str and name in allowed and name not in seen)
        seen.add(name)
        validate_value(name, value)


def encode_value(name, value):
    if type(value) is Decimal:
        return serialize_decimal(value)
    if isinstance(value, Enum):
        return value.value
    if name in {"entry_fills", "exit_fills"} and value is not None:
        return [{key: encode_value(key, item) for key, item in fill} for fill in value]
    if type(value) is tuple:
        return list(value)
    return value


def decode_value(name, value):
    if value is None:
        return None
    try:
        if name in DECIMAL_FIELDS:
            return deserialize_decimal(value)
        if name in ENUM_FIELDS:
            return ENUM_FIELDS[name](value)
        if name in {"processed_candle_open_ms", "new_execution_ids", "contributing_execution_ids"}:
            require(type(value) is list)
            return tuple(value)
        if name in {"entry_fills", "exit_fills"}:
            require(type(value) is list and len(value) <= MAX_FILLS)
            require(all(type(fill) is dict for fill in value))
            return tuple(tuple((key, decode_value(key, item)) for key, item in fill.items()) for fill in value)
        return value
    except (ValueError, TypeError, RuntimeStoreError):
        raise ObservabilityValidationError("Invalid observability field encoding.") from None


def _reference(event_type, values, details):
    if event_type in ACTION_TYPES:
        return {"action_id": values["action_id"], "phase": details.get("action_phase").value}
    if event_type in POSITION_TYPES or event_type is T.RECONCILIATION_CONFIRMED:
        return {"checkpoint_sequence": values["checkpoint_sequence"]}
    if event_type is T.OWNED_EXECUTION_DISCOVERED:
        return {"broker_execution_id": details.get("broker_execution_id")}
    if event_type is T.RISK_BLOCKED:
        return {"epoch_id": values["risk_epoch_id"], "candle_open_ms": values["candle_open_ms"]}
    if event_type is T.RISK_TRIPPED:
        reason = values["risk_trip_reason"]
        return {"epoch_id": values["risk_epoch_id"], "reason": reason.value,
                "tripped_at_ms": details.get("tripped_at_ms")}
    if event_type is T.RISK_REARMED:
        return {name: details.get(name) for name in ("parent_epoch_id", "child_epoch_id", "accepted_boundary_ms")}
    if event_type is T.RUNTIME_HALTED:
        return {"halted_at_ms": details.get("halted_at_ms")}
    if event_type is T.RUNTIME_REARMED:
        return {"rearmed_at_ms": details.get("rearmed_at_ms")}
    return ({"action_id": values["action_id"], "phase": "UNKNOWN_OUTCOME"}
            if values["action_id"] is not None and details.get("action_phase") is ActionPhase.UNKNOWN_OUTCOME
            else {"checkpoint_sequence": values["checkpoint_sequence"]})


def _id(event_type, values, details, occurrence_reference=None):
    payload = {key: values[key] for key in ("observability_version", "broker_id", "account_binding", "bot_id")}
    payload["event_type"] = event_type.value
    if event_type in PROCESS_TYPES:
        safe_text(occurrence_reference)
        payload.update(run_id=values["run_id"], occurrence_reference=occurrence_reference)
    else:
        require(occurrence_reference is None)
        payload["durable_reference"] = _reference(event_type, values, details)
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


def _required(event_type, values, details):
    def present(*names):
        require(all((details if name in PAYLOAD_FIELDS[event_type] else values).get(name) is not None for name in names))
    if event_type in ACTION_TYPES:
        present("action_id", "action_kind", "action_phase", "attempt_count")
        require(details["action_phase"] is ACTION_TYPES[event_type])
        require(details["attempt_count"] == int(details["action_phase"] not in (ActionPhase.PREPARED, ActionPhase.ABANDONED_UNSENT)))
        cancel = details["action_kind"] is JournalActionKind.CANCEL
        if cancel:
            present("parent_action_id", "target_broker_order_id")
            require(all(details.get(name) is None for name in ("side", "amount_unit", "currency", "authorized_amount", "submitted_amount", "order_link_id")))
        else:
            present("side", "amount_unit", "currency", "authorized_amount", "order_link_id")
            entry = details["action_kind"] is JournalActionKind.ENTRY
            require(details["side"] == ("BUY" if entry else "SELL") and details["amount_unit"] == ("QUOTE" if entry else "BASE"))
        if details["action_phase"] is ActionPhase.ACKNOWLEDGED:
            present("acknowledgement_broker_ms", "acknowledgement_observed_ms")
            if not cancel:
                present("broker_order_id", "submitted_amount")
        if details["action_phase"] in (ActionPhase.TERMINAL_CONFIRMED, ActionPhase.REJECTED, ActionPhase.ABANDONED_UNSENT):
            present("terminal_at_ms")
        if details["action_phase"] is ActionPhase.TERMINAL_CONFIRMED:
            require(details.get("order_status") in {"FILLED", "CANCELLED", "REJECTED", "EXPIRED"})
            if not cancel:
                present("broker_order_id")
        if details["action_phase"] is ActionPhase.REJECTED:
            present("rejection_code")
        if details["action_phase"] is ActionPhase.UNKNOWN_OUTCOME:
            present("safe_reason")
        if details.get("submitted_amount") is not None:
            require(details["submitted_amount"] <= details["authorized_amount"])
    elif event_type is T.OWNED_EXECUTION_DISCOVERED:
        present("action_id", "broker_order_id", "broker_execution_id", "side", "executed_quantity", "execution_price", "execution_fee", "executed_at_ms", "first_observed_at_ms")
        require(details["executed_quantity"] > 0 and details["execution_price"] > 0)
    elif event_type in POSITION_TYPES:
        present("checkpoint_sequence", "position_evidence", "previous_owned_base_quantity", "owned_base_quantity")
        before, after = details["previous_owned_base_quantity"], details["owned_base_quantity"]
        require(details["position_evidence"] is PositionEvidence.CONFIRMED and before >= 0 and after >= 0)
        require((before == 0 and after > 0) if event_type is T.POSITION_OPEN_CONFIRMED else
                (before > 0 and after == 0) if event_type is T.POSITION_CLOSE_CONFIRMED else
                (before > 0 and after > 0 and before != after))
    elif event_type is T.RECONCILIATION_CONFIRMED:
        present("checkpoint_sequence", "position_evidence", "owned_base_quantity", "last_reconciled_at_ms")
        require(details["position_evidence"] is PositionEvidence.CONFIRMED and details["owned_base_quantity"] >= 0)
    elif event_type in (T.RISK_BLOCKED, T.RISK_TRIPPED):
        present("risk_epoch_id", "risk_epoch_sequence")
        if event_type is T.RISK_BLOCKED:
            present("candle_open_ms", "risk_verdict", "risk_reason")
            require(details["risk_verdict"] is RiskVerdict.BLOCK)
        else:
            present("risk_trip_reason", "tripped_at_ms")
            require(values["risk_trip_reason"] in (RiskReason.DAILY_LOSS_LIMIT, RiskReason.MAX_DRAWDOWN))
    elif event_type is T.RISK_REARMED:
        present("parent_epoch_id", "child_epoch_id", "accepted_boundary_ms", "risk_configuration_digest", "risk_epoch_id", "risk_epoch_sequence")
        require(values["risk_epoch_sequence"] > 1 and values["risk_epoch_id"] == details["child_epoch_id"])
    elif event_type is T.RUNTIME_HALTED:
        present("halted_at_ms", "runtime_reason")
        require(values["runtime_state"] is RuntimeState.HALTED)
    elif event_type is T.RUNTIME_UNCERTAIN:
        present("runtime_reason")
        require(values["runtime_state"] is RuntimeState.UNCERTAIN or details.get("action_phase") is ActionPhase.UNKNOWN_OUTCOME)
        require(values["action_id"] is not None or values["checkpoint_sequence"] is not None)
    elif event_type is T.RUNTIME_REARMED:
        present("rearmed_at_ms", "previous_runtime_state", "reconciliation_required")
        require(values["runtime_state"] is RuntimeState.SYNCHRONIZING
                and details["previous_runtime_state"] is RuntimeState.HALTED and details["reconciliation_required"] is True)
    elif event_type in (T.CRITICAL_FAILURE, T.OBSERVABILITY_DEGRADED):
        present("operation", "failure_kind", "exception_type")
    elif event_type is T.CYCLE_COMPLETED:
        present("cycle_outcome", "processed_candle_count", "processed_candle_open_ms", "new_execution_ids")
        require(details["processed_candle_count"] == len(details["processed_candle_open_ms"]))
    elif event_type is T.SCHEDULER_EXITED:
        present("scheduler_exit_reason", "cycle_count", "wake_count")
    elif event_type is T.RISK_NOT_READY:
        require(details.get("risk_active") is False and details.get("cycle_outcome") == "RISK_NOT_READY")
    elif event_type is T.PROCESS_STARTED:
        present("process_started_at_ms")
    elif event_type is T.PROCESS_STOPPED:
        present("process_started_at_ms", "process_stopped_at_ms", "stop_reason")
        require(details["process_stopped_at_ms"] >= details["process_started_at_ms"])
    elif event_type is T.SCHEDULER_STARTED:
        present("scheduler_started_at_ms")
    else:
        present("evidence_kind")


@dataclass(frozen=True, slots=True)
class ObservabilityEvent:
    observability_version: int
    event_id: str
    event_type: ObservabilityEventType
    severity: ObservabilitySeverity
    source: str
    occurred_at_ms: int | None
    observed_at_ms: int
    run_id: str
    broker_id: str
    account_binding: str
    bot_id: str
    strategy_id: str
    symbol: str
    timeframe: str
    checkpoint_sequence: int | None = None
    runtime_state: RuntimeState | None = None
    runtime_reason: RuntimeReason | None = None
    risk_epoch_id: str | None = None
    risk_epoch_sequence: int | None = None
    risk_trip_reason: RiskReason | None = None
    candle_open_ms: int | None = None
    action_id: str | None = None
    broker_order_id: str | None = None
    summary: str = ""
    details: tuple[tuple[str, object], ...] = ()

    def __post_init__(self):
        require(type(self.observability_version) is int and self.observability_version == OBSERVABILITY_CONTRACT_VERSION)
        digest(self.event_id)
        require(type(self.event_type) is T and type(self.severity) is ObservabilitySeverity)
        require(type(self.source) is str and self.source == ("PROCESS" if self.event_type in PROCESS_TYPES else "DURABLE"))
        validate_run_id(self.run_id)
        integer(self.observed_at_ms)
        for name in ("broker_id", "account_binding", "bot_id", "strategy_id", "symbol", "timeframe", "broker_order_id"):
            if name != "broker_order_id":
                require(getattr(self, name) is not None)
            if getattr(self, name) is not None:
                safe_text(getattr(self, name))
        require(self.broker_id == "bybit-demo" and self.timeframe == "60")
        validate_strategy_id(self.strategy_id)
        require(self.symbol.isupper() and re.fullmatch(r"[a-z0-9]{1,12}", self.bot_id) is not None)
        for name in ("occurred_at_ms", "checkpoint_sequence", "risk_epoch_sequence", "candle_open_ms"):
            if getattr(self, name) is not None:
                integer(getattr(self, name), 1 if name == "risk_epoch_sequence" else 0)
        for name in ("action_id", "risk_epoch_id"):
            if getattr(self, name) is not None:
                digest(getattr(self, name))
        for name in ("runtime_state", "runtime_reason", "risk_trip_reason"):
            validate_value(name, getattr(self, name))
        require((self.risk_epoch_id is None) == (self.risk_epoch_sequence is None))
        require(type(self.summary) is str and len(self.summary) <= MAX_SUMMARY_CHARS
                and self.summary == self.event_type.value.replace("_", " "))
        validate_details(PAYLOAD_FIELDS[self.event_type], self.details)
        object.__setattr__(self, "details", tuple(sorted(self.details)))
        values = {name: getattr(self, name) for name in ENVELOPE_FIELDS}
        details = dict(self.details)
        _required(self.event_type, values, details)
        if self.event_type not in PROCESS_TYPES:
            require(self.event_id == _id(self.event_type, values, details))
        require(len(canonical_bytes(self.to_dict())) <= MAX_EVENT_BYTES)

    def to_dict(self):
        result = {name: encode_value(name, getattr(self, name)) for name in ENVELOPE_FIELDS}
        result.update((name, encode_value(name, value)) for name, value in self.details)
        return result

    def to_json(self) -> bytes:
        return canonical_bytes(self.to_dict())


def make_event(configuration: RuntimeConfiguration, event_type: ObservabilityEventType, *,
               run_id: str, observed_at_ms: int, occurred_at_ms: int | None = None,
               occurrence_reference: str | None = None, checkpoint_sequence: int | None = None,
               runtime_state: RuntimeState | None = None, runtime_reason: RuntimeReason | None = None,
               risk_epoch_id: str | None = None, risk_epoch_sequence: int | None = None,
               risk_trip_reason: RiskReason | None = None, candle_open_ms: int | None = None,
               action_id: str | None = None, broker_order_id: str | None = None,
               details: tuple[tuple[str, object], ...] = ()) -> ObservabilityEvent:
    require(type(configuration) is RuntimeConfiguration and type(event_type) is T)
    try:
        replace(configuration)
    except (RuntimeStoreError, TypeError):
        raise ObservabilityValidationError("Invalid observability instance configuration.") from None
    validate_run_id(run_id)
    integer(observed_at_ms)
    # Bound references before canonical hashing, not after allocating JSON for
    # an invalid supplied reference. These checks have no trading side effects.
    for value in (action_id, risk_epoch_id):
        if value is not None:
            digest(value)
    for value in (occurred_at_ms, checkpoint_sequence, candle_open_ms):
        if value is not None:
            integer(value)
    if risk_epoch_sequence is not None:
        integer(risk_epoch_sequence, 1)
    for name, value in (("runtime_state", runtime_state), ("runtime_reason", runtime_reason)):
        validate_value(name, value)
    if risk_trip_reason is not None:
        require(type(risk_trip_reason) is RiskReason)
    validate_details(PAYLOAD_FIELDS[event_type], details)
    values = {name: getattr(configuration, name) for name in
              ("broker_id", "account_binding", "bot_id", "strategy_id", "symbol", "timeframe")}
    values.update(observability_version=1, run_id=run_id, observed_at_ms=observed_at_ms,
        occurred_at_ms=occurred_at_ms, checkpoint_sequence=checkpoint_sequence,
        runtime_state=runtime_state, runtime_reason=runtime_reason,
        risk_epoch_id=risk_epoch_id, risk_epoch_sequence=risk_epoch_sequence,
        risk_trip_reason=risk_trip_reason, candle_open_ms=candle_open_ms,
        action_id=action_id, broker_order_id=broker_order_id)
    _required(event_type, values, dict(details))
    severity = (ObservabilitySeverity.CRITICAL if event_type in (T.RUNTIME_HALTED, T.CRITICAL_FAILURE) else
                ObservabilitySeverity.ERROR if event_type in (T.RUNTIME_UNCERTAIN, T.ACTION_UNKNOWN_OUTCOME) else
                ObservabilitySeverity.WARNING if event_type in (T.RISK_BLOCKED, T.RISK_TRIPPED, T.RISK_NOT_READY,
                    T.MARKET_DATA_STALE, T.RECONCILIATION_DEGRADED, T.OBSERVABILITY_DEGRADED) else ObservabilitySeverity.INFO)
    return ObservabilityEvent(event_id=_id(event_type, values, dict(details), occurrence_reference),
        event_type=event_type, severity=severity, source="PROCESS" if event_type in PROCESS_TYPES else "DURABLE",
        summary=event_type.value.replace("_", " "), details=details, **values)


def event_from_json(data: bytes) -> ObservabilityEvent:
    value = parse_object(data, MAX_EVENT_BYTES)
    require(set(ENVELOPE_FIELDS) <= value.keys())
    try:
        kind = T(value["event_type"])
        extra = set(value) - set(ENVELOPE_FIELDS)
        require(extra <= set(PAYLOAD_FIELDS[kind]))
        envelope = {name: decode_value(name, value[name]) for name in ENVELOPE_FIELDS}
        envelope["event_type"] = kind
        envelope["severity"] = ObservabilitySeverity(envelope["severity"])
        details = tuple((name, decode_value(name, value[name])) for name in sorted(extra))
        event = ObservabilityEvent(**envelope, details=details)
        require(event.to_json() == data)
        return event
    except (ValueError, TypeError, KeyError, AttributeError):
        raise ObservabilityValidationError("Invalid complete event encoding.") from None
