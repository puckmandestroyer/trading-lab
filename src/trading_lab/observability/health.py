"""Non-authoritative health, fenced by public durable reads, never wallet data."""

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
import re

from ..runtime.state import RuntimeState, RuntimeReason, PositionEvidence
from ..runtime.store import (RuntimeConfiguration, RuntimeCheckpoint, ActionRecord, RiskEpochRecord,
                             RiskConfigurationRecord, RiskValuationRecord, CandleRecord, ActionPhase, JournalActionKind,
                             RuntimeStoreError)
from ..runtime.cycle import SingleCycleResult, CycleOutcome
from ..risk.runtime_risk import RiskReason
from .model import (OBSERVABILITY_CONTRACT_VERSION, ObservabilityValidationError,
                    ObservabilityHealthLevel, EvidenceFreshness, validate_run_id, integer,
                    safe_text, digest, require, validate_value, encode_value, decode_value,
                    canonical_bytes, parse_object)
from .projection import projection_errors, exact

MAX_HEALTH_BYTES = 32_768


class HealthReason(str, Enum):
    RUNTIME_HALTED = "RUNTIME_HALTED"
    RUNTIME_UNCERTAIN = "RUNTIME_UNCERTAIN"
    FATAL_STATUS = "FATAL_STATUS"
    RISK_TRIPPED = "RISK_TRIPPED"
    RISK_NOT_READY = "RISK_NOT_READY"
    RUNTIME_NOT_READY = "RUNTIME_NOT_READY"
    MARKET_STALE = "MARKET_STALE"
    MARKET_UNKNOWN = "MARKET_UNKNOWN"
    RECONCILIATION_STALE = "RECONCILIATION_STALE"
    RECONCILIATION_UNKNOWN = "RECONCILIATION_UNKNOWN"
    BROKER_STALE = "BROKER_STALE"
    BROKER_UNKNOWN = "BROKER_UNKNOWN"
    RISK_STALE = "RISK_STALE"
    RISK_UNKNOWN = "RISK_UNKNOWN"
    OBSERVABILITY_DEGRADED = "OBSERVABILITY_DEGRADED"
    PENDING_OVERDUE = "PENDING_OVERDUE"


HEALTH_FIELDS = tuple("""observability_version generated_at_ms run_id broker_id account_binding bot_id
strategy_id symbol timeframe process_started_at_ms last_scheduler_activity_ms last_cycle_activity_ms
last_cycle_outcome observability_status checkpoint_sequence runtime_state runtime_reason position_evidence
owned_base_quantity desired_position pending_action_id pending_action_kind pending_action_phase
pending_reconciliation_deadline_ms last_processed_candle_ms last_reconciled_at_ms
last_broker_observation_at_ms halted_at_ms rearmed_at_ms risk_active risk_epoch_id risk_epoch_sequence
risk_configuration_digest valued_at_ms risk_equity peak_risk_equity utc_day_start_risk_equity daily_pnl
entries_this_utc_day max_entries_per_utc_day risk_trip_reason tripped_at_ms risk_capital_quote
buy_quote_budget max_entry_notional_quote max_position_notional_quote max_daily_loss_fraction
max_drawdown_fraction base_currency quote_currency drawdown_numerator drawdown_denominator
latest_accepted_candle_open_ms latest_accepted_mark_price market_valued_at_ms generated_freshness
market_freshness reconciliation_freshness broker_freshness risk_freshness overall_health reason_codes""".split())
_RISK_FIELDS = tuple("""risk_epoch_id risk_epoch_sequence risk_configuration_digest valued_at_ms
risk_equity peak_risk_equity utc_day_start_risk_equity daily_pnl entries_this_utc_day
max_entries_per_utc_day risk_trip_reason tripped_at_ms risk_capital_quote buy_quote_budget
max_entry_notional_quote max_position_notional_quote max_daily_loss_fraction max_drawdown_fraction
base_currency quote_currency drawdown_numerator drawdown_denominator""".split())
_ENUMS = {"overall_health": ObservabilityHealthLevel, "runtime_state": RuntimeState,
          "runtime_reason": RuntimeReason, "position_evidence": PositionEvidence,
          "risk_trip_reason": RiskReason, "pending_action_kind": JournalActionKind,
          "pending_action_phase": ActionPhase,
          **{name: EvidenceFreshness for name in ("generated_freshness", "market_freshness",
             "reconciliation_freshness", "broker_freshness", "risk_freshness")}}


def freshness(generated_at_ms, evidence_at_ms, maximum_age_ms):
    integer(generated_at_ms)
    integer(maximum_age_ms, 1)
    if evidence_at_ms is None:
        return EvidenceFreshness.UNKNOWN
    integer(evidence_at_ms)
    age = generated_at_ms - evidence_at_ms
    return (EvidenceFreshness.UNKNOWN if age < 0 else
            EvidenceFreshness.FRESH if age <= maximum_age_ms else EvidenceFreshness.STALE)


def _presentation(snapshot):
    critical = []
    attention = []
    if snapshot.runtime_state is RuntimeState.HALTED:
        critical.append(HealthReason.RUNTIME_HALTED)
    if (snapshot.runtime_state is RuntimeState.UNCERTAIN
            or snapshot.pending_action_phase is ActionPhase.UNKNOWN_OUTCOME
            or snapshot.runtime_state is RuntimeState.STOPPING and snapshot.runtime_reason is not None
            and snapshot.halted_at_ms is None):
        critical.append(HealthReason.RUNTIME_UNCERTAIN)
    if snapshot.observability_status == "CRITICAL":
        critical.append(HealthReason.FATAL_STATUS)
    if not snapshot.risk_active:
        attention.append(HealthReason.RISK_NOT_READY)
    if snapshot.risk_trip_reason is not None:
        attention.append(HealthReason.RISK_TRIPPED)
    if snapshot.runtime_state in (RuntimeState.STARTING, RuntimeState.SYNCHRONIZING, RuntimeState.STOPPING):
        attention.append(HealthReason.RUNTIME_NOT_READY)
    # A stopped HALT/UNCERTAIN retains its original reason and latch.
    if snapshot.halted_at_ms is not None and HealthReason.RUNTIME_HALTED not in critical:
        critical.append(HealthReason.RUNTIME_HALTED)
    for group in ("market", "reconciliation", "broker", "risk"):
        state = getattr(snapshot, group + "_freshness")
        if state is not EvidenceFreshness.FRESH:
            attention.append(HealthReason(group.upper() + "_" + state.value))
    if snapshot.observability_status == "DEGRADED":
        attention.append(HealthReason.OBSERVABILITY_DEGRADED)
    if (snapshot.pending_reconciliation_deadline_ms is not None
            and snapshot.generated_at_ms >= snapshot.pending_reconciliation_deadline_ms):
        attention.append(HealthReason.PENDING_OVERDUE)
    return (ObservabilityHealthLevel.CRITICAL if critical else
            ObservabilityHealthLevel.ATTENTION if attention else ObservabilityHealthLevel.OK,
            tuple(critical + attention))


@dataclass(frozen=True, slots=True)
class HealthSnapshot:
    observability_version: int
    generated_at_ms: int
    run_id: str
    broker_id: str
    account_binding: str
    bot_id: str
    strategy_id: str
    symbol: str
    timeframe: str
    process_started_at_ms: int
    last_scheduler_activity_ms: int | None
    last_cycle_activity_ms: int | None
    last_cycle_outcome: str | None
    observability_status: str
    checkpoint_sequence: int
    runtime_state: RuntimeState
    runtime_reason: RuntimeReason | None
    position_evidence: PositionEvidence
    owned_base_quantity: Decimal | None
    desired_position: int | None
    pending_action_id: str | None
    pending_action_kind: JournalActionKind | None
    pending_action_phase: ActionPhase | None
    pending_reconciliation_deadline_ms: int | None
    last_processed_candle_ms: int | None
    last_reconciled_at_ms: int | None
    last_broker_observation_at_ms: int | None
    halted_at_ms: int | None
    rearmed_at_ms: int | None
    risk_active: bool
    risk_epoch_id: str | None
    risk_epoch_sequence: int | None
    risk_configuration_digest: str | None
    valued_at_ms: int | None
    risk_equity: Decimal | None
    peak_risk_equity: Decimal | None
    utc_day_start_risk_equity: Decimal | None
    daily_pnl: Decimal | None
    entries_this_utc_day: int | None
    max_entries_per_utc_day: int | None
    risk_trip_reason: RiskReason | None
    tripped_at_ms: int | None
    risk_capital_quote: Decimal | None
    buy_quote_budget: Decimal | None
    max_entry_notional_quote: Decimal | None
    max_position_notional_quote: Decimal | None
    max_daily_loss_fraction: Decimal | None
    max_drawdown_fraction: Decimal | None
    base_currency: str | None
    quote_currency: str | None
    drawdown_numerator: Decimal | None
    drawdown_denominator: Decimal | None
    latest_accepted_candle_open_ms: int | None
    latest_accepted_mark_price: Decimal | None
    market_valued_at_ms: int | None
    generated_freshness: EvidenceFreshness
    market_freshness: EvidenceFreshness
    reconciliation_freshness: EvidenceFreshness
    broker_freshness: EvidenceFreshness
    risk_freshness: EvidenceFreshness
    overall_health: ObservabilityHealthLevel
    reason_codes: tuple[HealthReason, ...]

    def __post_init__(self):
        require(type(self.observability_version) is int and self.observability_version == OBSERVABILITY_CONTRACT_VERSION)
        validate_run_id(self.run_id)
        for name in ("broker_id", "account_binding", "bot_id", "strategy_id", "symbol", "timeframe"):
            safe_text(getattr(self, name))
        require(self.broker_id == "bybit-demo" and self.strategy_id == "ema_trend" and self.timeframe == "60")
        require(re.fullmatch(r"[a-z0-9]{1,12}", self.bot_id) is not None and self.symbol.isupper())
        require(type(self.observability_status) is str and self.observability_status in {"OK", "DEGRADED", "CRITICAL"})
        for name, enum in _ENUMS.items():
            value = getattr(self, name)
            require((value is None and name in {"runtime_reason", "risk_trip_reason", "pending_action_kind", "pending_action_phase"}) or type(value) is enum)
        integer(self.generated_at_ms)
        integer(self.process_started_at_ms)
        integer(self.checkpoint_sequence)
        require(self.generated_at_ms >= self.process_started_at_ms)
        for name in HEALTH_FIELDS:
            value = getattr(self, name)
            if name in _ENUMS or name in {"observability_version", "run_id", "observability_status", "reason_codes"}:
                continue
            if name in {"risk_epoch_id", "pending_action_id", "risk_configuration_digest"}:
                if value is not None:
                    digest(value)
            elif name in {"risk_epoch_sequence", "checkpoint_sequence"}:
                if value is not None:
                    integer(value, 1 if name == "risk_epoch_sequence" else 0)
            elif name == "desired_position":
                require(value is None or type(value) is int and value in (0, 1))
            else:
                validate_value(name, value)
        require(type(self.risk_active) is bool)
        require(type(self.reason_codes) is tuple and len(self.reason_codes) <= len(HealthReason))
        require(all(type(r) is HealthReason for r in self.reason_codes) and len(set(self.reason_codes)) == len(self.reason_codes))
        require((self.owned_base_quantity is None) == (self.position_evidence is PositionEvidence.UNKNOWN))
        require(self.owned_base_quantity is None or self.owned_base_quantity >= 0)
        operational = self.runtime_state in (RuntimeState.FLAT, RuntimeState.LONG, RuntimeState.ORDER_PENDING)
        require(operational == (self.position_evidence is PositionEvidence.CONFIRMED))
        if self.runtime_state is RuntimeState.FLAT:
            require(self.owned_base_quantity == 0 and self.pending_action_id is None)
        if self.runtime_state is RuntimeState.LONG:
            require(self.owned_base_quantity > 0 and self.pending_action_id is None)
        if self.runtime_state is RuntimeState.ORDER_PENDING:
            require(self.pending_action_id is not None)
        if self.runtime_state in (RuntimeState.HALTED, RuntimeState.UNCERTAIN):
            require(self.runtime_reason is not None)
        require(self.runtime_state is not RuntimeState.HALTED or self.halted_at_ms is not None)
        pending = (self.pending_action_id, self.pending_action_kind, self.pending_action_phase, self.pending_reconciliation_deadline_ms)
        require(all(v is None for v in pending) or all(v is not None for v in pending))
        if not self.risk_active:
            require(all(getattr(self, name) is None for name in _RISK_FIELDS))
        else:
            require(all(getattr(self, name) is not None for name in _RISK_FIELDS if name not in {"risk_trip_reason", "tripped_at_ms"}))
            require((self.risk_trip_reason is None) == (self.tripped_at_ms is None))
            require(self.risk_trip_reason is None or self.risk_trip_reason in (RiskReason.DAILY_LOSS_LIMIT, RiskReason.MAX_DRAWDOWN))
            require(self.tripped_at_ms is None or self.tripped_at_ms <= self.valued_at_ms)
            require(self.risk_equity > 0 and self.peak_risk_equity >= self.risk_equity
                    and self.utc_day_start_risk_equity > 0 and self.drawdown_numerator >= 0 and self.drawdown_denominator > 0)
            try:
                RiskConfigurationRecord(self.risk_configuration_digest, 1, self.risk_capital_quote,
                    self.buy_quote_budget, self.max_entry_notional_quote, self.max_position_notional_quote,
                    self.max_daily_loss_fraction, self.max_drawdown_fraction, self.max_entries_per_utc_day,
                    self.base_currency, self.quote_currency)
            except RuntimeStoreError:
                raise ObservabilityValidationError("Invalid bound health risk configuration.") from None
            require(self.symbol == self.base_currency + self.quote_currency)
        require((self.latest_accepted_candle_open_ms is None) == (self.latest_accepted_mark_price is None)
                == (self.market_valued_at_ms is None))
        require(self.latest_accepted_mark_price is None or self.latest_accepted_mark_price > 0)
        require(self.generated_freshness is EvidenceFreshness.FRESH)
        require((self.overall_health, self.reason_codes) == _presentation(self))
        require(len(self.to_json()) <= MAX_HEALTH_BYTES)

    def to_dict(self):
        result = {name: encode_value(name, getattr(self, name)) for name in HEALTH_FIELDS if name != "reason_codes"}
        result["reason_codes"] = [r.value for r in self.reason_codes]
        return result

    def to_json(self):
        return canonical_bytes(self.to_dict())


def health_from_json(data: bytes) -> HealthSnapshot:
    values = parse_object(data, MAX_HEALTH_BYTES)
    require(set(values) == set(HEALTH_FIELDS))
    try:
        decoded = {name: (None if value is None else _ENUMS[name](value)) if name in _ENUMS
                   else decode_value(name, value) for name, value in values.items() if name != "reason_codes"}
        require(type(values["reason_codes"]) is list)
        decoded["reason_codes"] = tuple(HealthReason(r) for r in values["reason_codes"])
        result = HealthSnapshot(**decoded)
        require(result.to_json() == data)
        return result
    except (ValueError, TypeError, AttributeError):
        raise ObservabilityValidationError("Invalid complete health encoding.") from None


def build_health_snapshot(store, *, run_id, process_started_at_ms, generated_at_ms,
                          last_scheduler_activity_ms=None, last_cycle_activity_ms=None,
                          last_cycle_result=None, observability_status="OK") -> HealthSnapshot:
    with projection_errors():
        a = exact(store.get_checkpoint(), RuntimeCheckpoint)
        cfg = exact(store.get_configuration(), RuntimeConfiguration)
        epoch = store.get_current_risk_epoch()
        risk_config = store.get_risk_configuration()
        valuation = store.get_latest_risk_valuation()
        candle = None if a.last_processed_candle_ms is None else store.get_candle(a.last_processed_candle_ms)
        pending = a.snapshot.pending_action
        action = None if pending is None else store.get_action(pending.logical_action_id)
        b = exact(store.get_checkpoint(), RuntimeCheckpoint)
        require(a.sequence == b.sequence and a == b and epoch == store.get_current_risk_epoch()
                and valuation == store.get_latest_risk_valuation())
        if pending is not None:
            exact(action, ActionRecord)
            require(action.logical_action_id == pending.logical_action_id and action.kind.value == pending.kind.value
                    and action.symbol == cfg.symbol and action.phase not in
                    (ActionPhase.TERMINAL_CONFIRMED, ActionPhase.REJECTED, ActionPhase.ABANDONED_UNSENT))
        if candle is not None:
            exact(candle, CandleRecord)
            require((candle.symbol, candle.timeframe, candle.candle_open_ms) == (cfg.symbol, cfg.timeframe, a.last_processed_candle_ms))
        require(a.last_processed_candle_ms is None or candle is not None)
        risk_values = {name: None for name in _RISK_FIELDS}
        if epoch is None:
            require(risk_config is None and valuation is None)
        else:
            exact(epoch, RiskEpochRecord)
            exact(risk_config, RiskConfigurationRecord)
            exact(valuation, RiskValuationRecord)
            require(epoch.epoch_id == valuation.epoch_id and epoch.risk_configuration_digest ==
                    risk_config.risk_configuration_digest == valuation.risk_configuration_digest)
            require((valuation.symbol, valuation.timeframe) == (cfg.symbol, cfg.timeframe))
            risk_values.update({name: getattr(risk_config, name) for name in (
                "risk_configuration_digest", "risk_capital_quote", "buy_quote_budget", "max_entry_notional_quote",
                "max_position_notional_quote", "max_daily_loss_fraction", "max_drawdown_fraction",
                "max_entries_per_utc_day", "base_currency", "quote_currency")})
            risk_values.update({name: getattr(valuation, name) for name in (
                "valued_at_ms", "risk_equity", "peak_risk_equity", "utc_day_start_risk_equity",
                "daily_pnl", "entries_this_utc_day", "tripped_at_ms")})
            state = valuation.state(epoch.started_at_ms)
            risk_values.update(risk_epoch_id=epoch.epoch_id, risk_epoch_sequence=epoch.epoch_sequence,
                risk_trip_reason=valuation.trip_reason, drawdown_numerator=state.drawdown_numerator,
                drawdown_denominator=state.drawdown_denominator)
        market_time = None if candle is None else candle.candle_open_ms + cfg.interval_ms
        market_price = None if candle is None else candle.close
        market_open = None if candle is None else candle.candle_open_ms
        if valuation is not None and (market_time is None or valuation.valued_at_ms > market_time):
            market_time, market_price, market_open = valuation.valued_at_ms, valuation.mark_price, valuation.candle_open_ms
        if last_cycle_result is not None:
            require(type(last_cycle_result) is SingleCycleResult and type(last_cycle_result.outcome) is CycleOutcome)
            require(last_cycle_activity_ms is not None and last_cycle_result.checkpoint.sequence <= a.sequence)
        values = dict(observability_version=1, generated_at_ms=generated_at_ms, run_id=run_id,
            **{name: getattr(cfg, name) for name in ("broker_id", "account_binding", "bot_id", "strategy_id", "symbol", "timeframe")},
            process_started_at_ms=process_started_at_ms, last_scheduler_activity_ms=last_scheduler_activity_ms,
            last_cycle_activity_ms=last_cycle_activity_ms,
            last_cycle_outcome=None if last_cycle_result is None else last_cycle_result.outcome.value,
            observability_status=observability_status, checkpoint_sequence=a.sequence,
            runtime_state=a.snapshot.state, runtime_reason=a.snapshot.reason,
            position_evidence=a.snapshot.position_evidence, owned_base_quantity=a.snapshot.owned_base_quantity,
            desired_position=a.snapshot.desired_position, pending_action_id=None if pending is None else pending.logical_action_id,
            pending_action_kind=None if action is None else action.kind, pending_action_phase=None if action is None else action.phase,
            pending_reconciliation_deadline_ms=None if action is None else action.reconciliation_deadline_ms,
            last_processed_candle_ms=a.last_processed_candle_ms, last_reconciled_at_ms=a.last_reconciled_at_ms,
            last_broker_observation_at_ms=a.observed_at_ms, halted_at_ms=a.halted_at_ms, rearmed_at_ms=a.rearmed_at_ms,
            risk_active=epoch is not None, **risk_values, latest_accepted_candle_open_ms=market_open,
            latest_accepted_mark_price=market_price, market_valued_at_ms=market_time,
            generated_freshness=EvidenceFreshness.FRESH,
            market_freshness=freshness(generated_at_ms, market_time, cfg.decision_max_age_ms),
            reconciliation_freshness=freshness(generated_at_ms, a.last_reconciled_at_ms, cfg.observation_max_age_ms),
            broker_freshness=freshness(generated_at_ms, a.observed_at_ms, cfg.observation_max_age_ms),
            risk_freshness=freshness(generated_at_ms, None if valuation is None else valuation.valued_at_ms, cfg.decision_max_age_ms))
        # Classify from a private explicit field view, then construct/validate the
        # immutable record once. No partially valid record escapes the builder.
        class View:
            def __getattr__(self, name):
                return values[name]
        level, reasons = _presentation(View())
        return HealthSnapshot(**values, overall_health=level, reason_codes=reasons)
