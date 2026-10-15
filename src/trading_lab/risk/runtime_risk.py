"""Pure runtime risk facts and policy under Decision 018; no external resources.

Callers supply already-owned, deduplicated executions and an authoritative mark
at each consecutive closed hour. This module cannot establish ownership, fetch
prices, authenticate history or make an authorization durable. In particular,
applying the same execution twice applies its economics twice: durable identity,
deduplication, activation and rearm belong to later milestones.
"""

from dataclasses import dataclass, replace
from decimal import (
    Context, Decimal, DecimalException, Inexact, InvalidOperation, MAX_EMAX,
    MIN_EMIN, Overflow, Underflow, localcontext,
)
from enum import Enum


HOUR_MS = 3_600_000
DAY_MS = 86_400_000
_MAX_TIME_MS = 2**63 - 1
_MAX_DECIMAL_CHARS = 4096

__all__ = [
    "RuntimeRiskError", "RiskVerdict", "RiskReason", "RiskActionKind",
    "RiskExecutionSide", "RuntimeRiskConfiguration", "RiskExecution",
    "RiskBook", "RiskState", "RiskActionProposal", "RiskEvaluation",
    "initial_risk_book", "apply_owned_execution", "calculate_risk_equity",
    "initialize_risk_state", "advance_risk_state", "evaluate_risk",
    "calculate_projected_exposure", "HOUR_MS", "DAY_MS",
]


class RuntimeRiskError(ValueError):
    """Invalid/inconsistent pure evidence; diagnostics never echo supplied data."""


class RiskVerdict(str, Enum):
    ALLOW = "ALLOW"
    BLOCK = "BLOCK"
    TRIP = "TRIP"


class RiskReason(str, Enum):
    ENTRY_NOTIONAL_LIMIT = "ENTRY_NOTIONAL_LIMIT"
    POSITION_NOTIONAL_LIMIT = "POSITION_NOTIONAL_LIMIT"
    ENTRY_COUNT_LIMIT = "ENTRY_COUNT_LIMIT"
    RISK_LATCH_ACTIVE = "RISK_LATCH_ACTIVE"
    DAILY_LOSS_LIMIT = "DAILY_LOSS_LIMIT"
    MAX_DRAWDOWN = "MAX_DRAWDOWN"


class RiskActionKind(str, Enum):
    ENTRY = "ENTRY"
    EXIT = "EXIT"


class RiskExecutionSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


_TRIP_REASONS = (RiskReason.DAILY_LOSS_LIMIT, RiskReason.MAX_DRAWDOWN)


def _require(condition, message):
    if not condition:
        raise RuntimeRiskError(message)


def _decimal(value, *, positive=False, nonnegative=False):
    _require(type(value) is Decimal and value.is_finite(), "A finite exact Decimal is required.")
    # Same plain-decimal size bound as the frozen journal; zero is canonical
    # regardless of its supplied exponent. Never format an unbounded value.
    if value != 0:
        parts = value.as_tuple()
        _require(len(parts.digits) + abs(parts.exponent) + 3 <= _MAX_DECIMAL_CHARS,
                 "Decimal exceeds the supported exact numeric bound.")
    if positive:
        _require(value > 0, "A strictly positive Decimal is required.")
    if nonnegative:
        _require(value >= 0, "A nonnegative Decimal is required.")


def _integer(value):
    _require(type(value) is int and value >= 0, "A nonnegative Python integer is required.")


def _time(value, *, hourly=False):
    _integer(value)
    _require(value <= _MAX_TIME_MS and (not hourly or value % HOUR_MS == 0),
             "An in-range UTC millisecond timestamp on the required grid is required.")


def _text(value, *, currency=False):
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789" if currency else (
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-"
    )
    _require(type(value) is str and 0 < len(value) <= 64
             and all(character in alphabet for character in value)
             and (not currency or value[0] in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"),
             "Explicit safe identifier or uppercase currency text is required.")


def _record(value, cls):
    _require(type(value) is cls, "A validated pure risk record is required.")
    # Revalidate even if an outside caller bypassed a frozen constructor.
    try:
        replace(value)
        return
    except (AttributeError, TypeError):
        pass
    # Raise outside the handler so an AttributeError cannot retain the supplied
    # incomplete object through its exception context.
    raise RuntimeRiskError("A complete valid pure risk record is required.")


def _context(precision):
    # A new Context, not a copy of the caller's context: precision, exponent
    # bounds and traps are independent of global precision/rounding/traps.
    return Context(prec=precision, Emax=MAX_EMAX, Emin=MIN_EMIN,
                   traps=[Inexact, InvalidOperation, Overflow, Underflow])


def _sum(*values):
    # Aligned decimal coefficients plus carry room make addition exact, including
    # cancellation between very large and very small finite decimal values.
    values = tuple(Decimal(0) if value == 0 else value for value in values)
    exponent = min(value.as_tuple().exponent for value in values)
    precision = max(len(value.as_tuple().digits) + value.as_tuple().exponent - exponent
                    for value in values) + len(values) + 2
    try:
        with localcontext(_context(precision)):
            result = sum(values, Decimal(0))
    except DecimalException:
        raise RuntimeRiskError("Exact risk arithmetic failed.") from None
    _decimal(result)
    return result


def _product(left, right):
    if left == 0 or right == 0:
        return Decimal(0)
    precision = len(left.as_tuple().digits) + len(right.as_tuple().digits) + 2
    try:
        with localcontext(_context(precision)):
            result = left * right
    except DecimalException:
        raise RuntimeRiskError("Exact risk arithmetic failed.") from None
    _decimal(result)
    return result


@dataclass(frozen=True, slots=True)
class RuntimeRiskConfiguration:
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
        for value in (self.risk_capital_quote, self.buy_quote_budget,
                      self.max_entry_notional_quote, self.max_position_notional_quote,
                      self.max_daily_loss_fraction, self.max_drawdown_fraction):
            _decimal(value, positive=True)
        _require(self.buy_quote_budget <= self.max_entry_notional_quote
                 <= self.max_position_notional_quote <= self.risk_capital_quote,
                 "Configured quote budgets and caps must be ordered within risk capital.")
        _require(self.max_daily_loss_fraction <= 1 and self.max_drawdown_fraction <= 1,
                 "Risk fractions must be at most one.")
        _integer(self.max_entries_per_utc_day)
        _require(self.max_entries_per_utc_day >= 1, "The daily entry limit must be positive.")
        _text(self.base_currency, currency=True)
        _text(self.quote_currency, currency=True)
        _require(self.base_currency != self.quote_currency, "Base and quote currencies must differ.")


@dataclass(frozen=True, slots=True)
class RiskExecution:
    """One already-owned, already-deduplicated normalized execution observation."""

    execution_id: str
    side: RiskExecutionSide
    executed_base_quantity: Decimal
    execution_price: Decimal
    execution_fee: Decimal
    fee_currency: str | None
    executed_at_ms: int

    def __post_init__(self):
        _text(self.execution_id)
        _require(type(self.side) is RiskExecutionSide, "An explicit execution side is required.")
        _decimal(self.executed_base_quantity, positive=True)
        _decimal(self.execution_price, positive=True)
        _decimal(self.execution_fee)
        if self.fee_currency is not None:
            _text(self.fee_currency, currency=True)
        _time(self.executed_at_ms)


@dataclass(frozen=True, slots=True)
class RiskBook:
    """Bot-owned cash/inventory only; negative cash is retained, never repaired."""

    virtual_quote_cash: Decimal
    owned_base_quantity: Decimal

    def __post_init__(self):
        _decimal(self.virtual_quote_cash)
        _decimal(self.owned_base_quantity, nonnegative=True)


@dataclass(frozen=True, slots=True)
class RiskState:
    """One pure epoch snapshot, not durable history or a rearm capability.

    Drawdown diagnostics are an exact numerator/denominator pair exposed below;
    no rounded ratio controls policy. trip_pending_report distinguishes a newly
    latched, as-yet unevaluated breach from an existing latch. evaluate_risk
    consumes that notification in its returned copy, never clears the latch.
    """

    epoch_started_at_ms: int
    valued_at_ms: int
    risk_equity: Decimal
    peak_risk_equity: Decimal
    utc_day_start_ms: int
    utc_day_start_risk_equity: Decimal
    daily_pnl: Decimal
    entries_this_utc_day: int
    trip_reason: RiskReason | None = None
    tripped_at_ms: int | None = None
    trip_pending_report: bool = False

    def __post_init__(self):
        _time(self.epoch_started_at_ms, hourly=True)
        _time(self.valued_at_ms, hourly=True)
        _time(self.utc_day_start_ms)
        _require(self.epoch_started_at_ms <= self.valued_at_ms
                 and self.utc_day_start_ms == self.valued_at_ms // DAY_MS * DAY_MS,
                 "Epoch, valuation and UTC day boundaries must agree.")
        _decimal(self.risk_equity, positive=True)
        _decimal(self.peak_risk_equity, positive=True)
        _decimal(self.utc_day_start_risk_equity, positive=True)
        _decimal(self.daily_pnl)
        _require(self.peak_risk_equity >= self.risk_equity
                 and self.peak_risk_equity >= self.utc_day_start_risk_equity,
                 "Epoch peak cannot be below accepted equity or the daily baseline.")
        _require(self.daily_pnl == _sum(self.risk_equity, self.utc_day_start_risk_equity.copy_negate()),
                 "Daily PnL must equal equity minus its UTC baseline.")
        _integer(self.entries_this_utc_day)
        _require(type(self.trip_pending_report) is bool, "The trip notification must be an explicit boolean.")
        if self.trip_reason is None:
            _require(self.tripped_at_ms is None and not self.trip_pending_report,
                     "An untripped state cannot carry trip time or notification.")
        else:
            _require(type(self.trip_reason) is RiskReason and self.trip_reason in _TRIP_REASONS,
                     "Only valuation breaker reasons may latch a trip.")
            _time(self.tripped_at_ms, hourly=True)
            _require(self.epoch_started_at_ms <= self.tripped_at_ms <= self.valued_at_ms,
                     "Trip time must belong to the accepted epoch history.")

    @property
    def drawdown_numerator(self) -> Decimal:
        return _sum(self.peak_risk_equity, self.risk_equity.copy_negate())

    @property
    def drawdown_denominator(self) -> Decimal:
        return self.peak_risk_equity


@dataclass(frozen=True, slots=True)
class RiskActionProposal:
    """ENTRY amount is quote authorization; EXIT amount is exact owned base."""

    kind: RiskActionKind
    authorized_amount: Decimal

    def __post_init__(self):
        _require(type(self.kind) is RiskActionKind, "An explicit risk action kind is required.")
        _decimal(self.authorized_amount, positive=True)


@dataclass(frozen=True, slots=True)
class RiskEvaluation:
    state: RiskState
    verdict: RiskVerdict
    reason: RiskReason | None = None

    def __post_init__(self):
        _record(self.state, RiskState)
        _require(type(self.verdict) is RiskVerdict, "An explicit risk verdict is required.")
        if self.verdict is RiskVerdict.ALLOW:
            _require(self.reason is None, "ALLOW cannot carry a refusal reason.")
        elif self.verdict is RiskVerdict.TRIP:
            _require(type(self.reason) is RiskReason and self.reason in _TRIP_REASONS
                     and self.reason is self.state.trip_reason,
                     "TRIP must match the state's latched valuation reason.")
        else:
            _require(type(self.reason) is RiskReason and self.reason not in _TRIP_REASONS,
                     "BLOCK requires a policy refusal reason.")
            if self.reason is RiskReason.RISK_LATCH_ACTIVE:
                _require(self.state.trip_reason is not None, "An active latch refusal requires a latched state.")


def initial_risk_book(config: RuntimeRiskConfiguration) -> RiskBook:
    """First accounting anchor; never adopts broker balances or rearms an epoch."""
    _record(config, RuntimeRiskConfiguration)
    return RiskBook(config.risk_capital_quote, Decimal(0))


def apply_owned_execution(
    config: RuntimeRiskConfiguration, book: RiskBook, execution: RiskExecution,
) -> RiskBook:
    """Apply one supplied owned execution once; this function is NOT idempotent.

    Caller owns deduplication, temporal cutoffs and complete ownership evidence.
    Signed base fees affect inventory on either side, exactly once; signed quote
    fees affect cash. Unknown nonzero fee units cannot be valued safely.
    """
    _record(config, RuntimeRiskConfiguration)
    _record(book, RiskBook)
    _record(execution, RiskExecution)
    fee = execution.execution_fee
    _require(fee == 0 or execution.fee_currency in (config.base_currency, config.quote_currency),
             "Nonzero fees require the configured base or quote currency.")
    notional = _product(execution.executed_base_quantity, execution.execution_price)
    buy = execution.side is RiskExecutionSide.BUY
    cash = _sum(book.virtual_quote_cash, notional.copy_negate() if buy else notional)
    base = _sum(book.owned_base_quantity, execution.executed_base_quantity if buy
                else execution.executed_base_quantity.copy_negate())
    if execution.fee_currency == config.quote_currency:
        cash = _sum(cash, fee.copy_negate())
    elif execution.fee_currency == config.base_currency:
        base = _sum(base, fee.copy_negate())
    return RiskBook(cash, base)


def calculate_risk_equity(book: RiskBook, mark_price: Decimal) -> Decimal:
    """Cash plus exact owned-base mark; no hypothetical execution or future fee."""
    _record(book, RiskBook)
    _decimal(mark_price, positive=True)
    return _sum(book.virtual_quote_cash, _product(book.owned_base_quantity, mark_price))


def calculate_projected_exposure(
    owned_base_quantity: Decimal, mark_price: Decimal,
    authorized_entry_quote: Decimal,
    pending_entry_reservation_quote: Decimal = Decimal("0"),
) -> Decimal:
    """Conservative capacity only; reservations do not debit cash or create fills."""
    _decimal(owned_base_quantity, nonnegative=True)
    _decimal(mark_price, positive=True)
    _decimal(authorized_entry_quote, nonnegative=True)
    _decimal(pending_entry_reservation_quote, nonnegative=True)
    return _sum(_product(owned_base_quantity, mark_price), authorized_entry_quote,
                pending_entry_reservation_quote)


def initialize_risk_state(
    config: RuntimeRiskConfiguration, book: RiskBook, mark_price: Decimal,
    valued_at_ms: int,
) -> RiskState:
    """First validated activation only; no historical reconstruction or rearm."""
    _record(config, RuntimeRiskConfiguration)
    _time(valued_at_ms, hourly=True)
    equity = calculate_risk_equity(book, mark_price)
    return RiskState(valued_at_ms, valued_at_ms, equity, equity,
                     valued_at_ms // DAY_MS * DAY_MS, equity, Decimal(0), 0)


def _breach(config, equity, peak, baseline):
    """Daily loss takes precedence; no division or rounded ratio is involved."""
    pnl = _sum(equity, baseline.copy_negate())
    if pnl <= _product(config.risk_capital_quote, config.max_daily_loss_fraction).copy_negate():
        return RiskReason.DAILY_LOSS_LIMIT
    if _sum(peak, equity.copy_negate()) >= _product(peak, config.max_drawdown_fraction):
        return RiskReason.MAX_DRAWDOWN
    return None


def advance_risk_state(
    config: RuntimeRiskConfiguration, previous: RiskState, book: RiskBook,
    mark_price: Decimal, valued_at_ms: int,
) -> RiskState:
    """Value exactly the next closed hour and latch any first breach.

    At UTC midnight, check the outgoing day's final move BEFORE resetting its
    baseline/count. DAILY_LOSS_LIMIT wins a simultaneous first drawdown breach.
    Existing latch reason/time/notification survive; no automatic rearm exists.
    """
    _record(config, RuntimeRiskConfiguration)
    _record(previous, RiskState)
    _time(valued_at_ms, hourly=True)
    _require(valued_at_ms == previous.valued_at_ms + HOUR_MS,
             "Risk valuations must advance by exactly one closed hour.")
    equity = calculate_risk_equity(book, mark_price)
    _decimal(equity, positive=True)
    peak = max(previous.peak_risk_equity, equity)
    closing_pnl = _sum(equity, previous.utc_day_start_risk_equity.copy_negate())
    reason, tripped_at, pending = previous.trip_reason, previous.tripped_at_ms, previous.trip_pending_report
    if reason is None:
        reason = _breach(config, equity, peak, previous.utc_day_start_risk_equity)
        if reason is not None:
            tripped_at, pending = valued_at_ms, True
    day = valued_at_ms // DAY_MS * DAY_MS
    rollover = day != previous.utc_day_start_ms
    return RiskState(previous.epoch_started_at_ms, valued_at_ms, equity, peak, day,
                     equity if rollover else previous.utc_day_start_risk_equity,
                     Decimal(0) if rollover else closing_pnl,
                     0 if rollover else previous.entries_this_utc_day,
                     reason, tripped_at, pending)


def evaluate_risk(
    config: RuntimeRiskConfiguration, state: RiskState, book: RiskBook,
    mark_price: Decimal, proposal: RiskActionProposal | None = None,
) -> RiskEvaluation:
    """Evaluate a supplied proposal against the latest accepted valuation.

    Thread the returned immutable state into the next call. A newly latched
    breach reports TRIP once (or ALLOW for a valid exact EXIT); subsequent ENTRY
    gets BLOCK/RISK_LATCH_ACTIVE. No-proposal ALLOW authorizes no broker action.
    An ENTRY ALLOW consumes one pure count; durable atomicity is later work.
    """
    _record(config, RuntimeRiskConfiguration)
    _record(state, RiskState)
    _require(calculate_risk_equity(book, mark_price) == state.risk_equity,
             "Book and mark must match the state's accepted valuation.")
    if proposal is not None:
        _record(proposal, RiskActionProposal)
        if proposal.kind is RiskActionKind.EXIT:
            _require(book.owned_base_quantity > 0 and proposal.authorized_amount == book.owned_base_quantity,
                     "EXIT must authorize exactly the positive owned base quantity.")
        else:
            _require(book.owned_base_quantity == 0, "ENTRY requires zero owned base; pyramiding is forbidden.")
    # A supplied structurally valid unlatched snapshot is not proof that its
    # policy thresholds were checked. Recheck before any action can be ALLOWed.
    if state.trip_reason is None:
        reason = _breach(config, state.risk_equity, state.peak_risk_equity,
                         state.utc_day_start_risk_equity)
        if reason is not None:
            state = replace(state, trip_reason=reason, tripped_at_ms=state.valued_at_ms,
                            trip_pending_report=True)
    reported = replace(state, trip_pending_report=False)
    if proposal is not None and proposal.kind is RiskActionKind.EXIT:
        return RiskEvaluation(reported, RiskVerdict.ALLOW)
    if state.trip_pending_report:
        return RiskEvaluation(reported, RiskVerdict.TRIP, state.trip_reason)
    if proposal is None:
        return RiskEvaluation(reported, RiskVerdict.ALLOW)
    if state.trip_reason is not None:
        return RiskEvaluation(reported, RiskVerdict.BLOCK, RiskReason.RISK_LATCH_ACTIVE)
    if state.entries_this_utc_day >= config.max_entries_per_utc_day:
        return RiskEvaluation(reported, RiskVerdict.BLOCK, RiskReason.ENTRY_COUNT_LIMIT)
    if proposal.authorized_amount > config.max_entry_notional_quote:
        return RiskEvaluation(reported, RiskVerdict.BLOCK, RiskReason.ENTRY_NOTIONAL_LIMIT)
    exposure = calculate_projected_exposure(book.owned_base_quantity, mark_price, proposal.authorized_amount)
    if exposure > config.max_position_notional_quote:
        return RiskEvaluation(reported, RiskVerdict.BLOCK, RiskReason.POSITION_NOTIONAL_LIMIT)
    return RiskEvaluation(replace(reported, entries_this_utc_day=state.entries_this_utc_day + 1), RiskVerdict.ALLOW)
