"""One bounded, read-only reconciliation round under Decision 017.

The caller acquires the account lock, opens the store and supplies a Demo
ReadOnlyBroker. Broker reads and durable writes are separate operations, never
an exchange/SQLite transaction. No strategy, submission, resend or retry loop.
"""

from collections.abc import Callable
from dataclasses import dataclass, fields, replace
from datetime import datetime, timedelta, timezone
from decimal import Context, Decimal, MAX_EMAX, MIN_EMIN, localcontext
import math
from time import monotonic as monotonic_clock

from ..exchange.account_state import (
    AccountState, BrokerOrderNotFoundError, BrokerReadError, BrokerReadFailureKind,
    CurrencyBalance, ExecutionState,
    OrderState, OrderStatus, ReadOnlyBroker,
)
from .state import (
    RuntimeEvent, RuntimeEventType, RuntimeEvidence, RuntimeReason, RuntimeState,
    transition_runtime_state,
)
from .store import (
    ActionPhase, ActionRecord, JournalActionKind, OwnedFillRecord,
    RuntimeCheckpoint, RuntimeStore, RuntimeStoreError, serialize_decimal,
)


class ReconciliationError(ValueError):
    """Invalid caller/clock input; fixed diagnostics, no external error text."""


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    """Committed result; cancellation stays separate from the placement."""

    checkpoint: RuntimeCheckpoint
    placement: ActionRecord | None
    cancellation: ActionRecord | None
    new_execution_ids: tuple[str, ...] = ()


class _Issue(Exception):
    def __init__(self, reason, *, fatal=False, observation=None):
        self.reason = reason
        self.fatal = fatal
        self.observation = observation


_TERMINAL = frozenset({ActionPhase.TERMINAL_CONFIRMED, ActionPhase.REJECTED, ActionPhase.ABANDONED_UNSENT})
_ORDER_TERMINAL = frozenset({OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED, OrderStatus.EXPIRED})


def _milliseconds(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ReconciliationError("An aware UTC datetime is required.")
    delta = value - datetime(1970, 1, 1, tzinfo=timezone.utc)
    result = (delta.days * 86400 + delta.seconds) * 1000 + delta.microseconds // 1000
    if result < 0:
        raise ReconciliationError("UTC timestamp precedes the supported epoch.")
    return result  # Explicit floor for local observation microseconds; no float.


def _clock(utc_now, monotonic):
    try:
        utc = _milliseconds(utc_now())
        elapsed = monotonic()
        if isinstance(elapsed, bool) or not isinstance(elapsed, (int, float)) or not math.isfinite(elapsed):
            raise ReconciliationError("A finite monotonic clock is required.")
        return utc, elapsed
    except Exception:
        raise ReconciliationError("Invalid reconciliation clock input.") from None


def _number(value, *, positive=False, signed=False):
    try:
        serialize_decimal(value)
    except RuntimeStoreError:
        raise _Issue(RuntimeReason.INCONSISTENT_EVIDENCE, fatal=True) from None
    if not signed and (value <= 0 if positive else value < 0):
        raise _Issue(RuntimeReason.INCONSISTENT_EVIDENCE, fatal=True)
    return value


def _sum(values):
    values = tuple(values)
    if not values:
        return Decimal(0)
    exponent = min(value.as_tuple().exponent for value in values)
    precision = max(len(value.as_tuple().digits) + value.as_tuple().exponent - exponent for value in values)
    with localcontext(Context(prec=precision + len(str(len(values))) + 2, Emax=MAX_EMAX, Emin=MIN_EMIN)):
        return sum(values, Decimal(0))


def _product(left, right):
    with localcontext(Context(prec=len(left.as_tuple().digits) + len(right.as_tuple().digits) + 2,
                              Emax=MAX_EMAX, Emin=MIN_EMIN)):
        return left * right


def _inventory(fills, config):
    effects = []
    for fill in fills:
        effects.append(fill.executed_quantity if fill.side == "BUY" else fill.executed_quantity.copy_negate())
        if fill.execution_fee != 0 and fill.fee_currency is None:
            raise _Issue(RuntimeReason.EVIDENCE_MISSING)
        # Signed base fees reduce inventory; rebates increase it. Quote/other
        # currency fees remain separate facts, with no conversion or PnL.
        if fill.fee_currency == config.base_currency:
            effects.append(fill.execution_fee.copy_negate())
    quantity = _sum(effects)
    if quantity < 0:
        raise _Issue(RuntimeReason.INCONSISTENT_EVIDENCE, fatal=True)
    return quantity


def _common(record, config, now_ms):
    if record.broker_id != config.broker_id or record.account_id not in (None, config.account_binding):
        raise _Issue(RuntimeReason.OWNERSHIP_CONFLICT, fatal=True)
    try:
        broker_ms, fetched_ms = _milliseconds(record.broker_timestamp), _milliseconds(record.fetched_at)
    except ReconciliationError:
        raise _Issue(RuntimeReason.INCONSISTENT_EVIDENCE, fatal=True) from None
    if (abs(broker_ms - fetched_ms) > config.max_clock_skew_ms
            or fetched_ms > now_ms + config.max_clock_skew_ms
            or now_ms - fetched_ms > config.observation_max_age_ms):
        raise _Issue(RuntimeReason.EVIDENCE_MISSING)
    return fetched_ms


def _order_identity(order, action, config, now_ms):
    if not isinstance(order, OrderState):
        raise _Issue(RuntimeReason.INCONSISTENT_EVIDENCE, fatal=True)
    fetched_ms = _common(order, config, now_ms)
    if action.observed_at_ms is not None and fetched_ms < action.observed_at_ms:
        raise _Issue(RuntimeReason.EVIDENCE_MISSING)
    if (order.symbol != action.symbol or order.side != action.side or order.order_type != "MARKET"
            or order.quantity_unit != action.amount_unit or order.limit_price is not None or order.stop_price is not None
            or (action.broker_order_id is not None and order.broker_order_id != action.broker_order_id)
            or (order.order_link_id is not None and order.order_link_id != action.order_link_id)):
        raise _Issue(RuntimeReason.OWNERSHIP_CONFLICT, fatal=True)
    try:
        replace(action, broker_order_id=order.broker_order_id)
    except RuntimeStoreError:
        raise _Issue(RuntimeReason.INCONSISTENT_EVIDENCE, fatal=True) from None
    if order.order_link_id is None:
        raise _Issue(RuntimeReason.EVIDENCE_MISSING)
    _number(order.requested_quantity, positive=True)
    for value in (order.filled_quantity, order.remaining_quantity, order.filled_base_quantity):
        _number(value)
    if order.filled_quote_amount is not None:
        _number(order.filled_quote_amount)
    if (order.requested_quantity > action.authorized_amount
            or (action.submitted_amount is not None and order.requested_quantity != action.submitted_amount)):
        raise _Issue(RuntimeReason.OWNERSHIP_CONFLICT, fatal=True)
    if (not isinstance(order.status, OrderStatus)
            or _sum((order.filled_quantity, order.remaining_quantity)) != order.requested_quantity
            or order.filled_quantity != (order.filled_base_quantity if order.quantity_unit == "BASE" else order.filled_quote_amount)):
        raise _Issue(RuntimeReason.INCONSISTENT_EVIDENCE, fatal=True)
    try:
        created, updated = _milliseconds(order.created_at), _milliseconds(order.updated_at)
        server = _milliseconds(order.broker_timestamp)
    except ReconciliationError:
        raise _Issue(RuntimeReason.INCONSISTENT_EVIDENCE, fatal=True) from None
    if created < action.candle_open_ms + config.interval_ms or created > updated or updated > server:
        raise _Issue(RuntimeReason.INCONSISTENT_EVIDENCE, fatal=True)


def _execution(execution, action, config, now_ms):
    if (execution.symbol != action.symbol or execution.side != action.side
            or (execution.order_link_id is not None and execution.order_link_id != action.order_link_id)
            or (action.broker_order_id is not None and execution.broker_order_id != action.broker_order_id)):
        raise _Issue(RuntimeReason.OWNERSHIP_CONFLICT, fatal=True)
    _common(execution, config, now_ms)
    if execution.order_link_id is None:
        raise _Issue(RuntimeReason.EVIDENCE_MISSING)
    try:
        executed_ms = _milliseconds(execution.executed_at)
        if executed_ms < action.candle_open_ms + config.interval_ms or executed_ms > _milliseconds(execution.broker_timestamp):
            raise _Issue(RuntimeReason.INCONSISTENT_EVIDENCE, fatal=True)
        return OwnedFillRecord(config.broker_id, config.account_binding, execution.broker_execution_id,
                               action.logical_action_id, execution.broker_order_id, action.order_link_id,
                               execution.symbol, execution.side, execution.executed_quantity, execution.execution_price,
                               execution.execution_fee, execution.fee_currency,
                               executed_ms, _milliseconds(execution.fetched_at))
    except (RuntimeStoreError, ReconciliationError):
        raise _Issue(RuntimeReason.INCONSISTENT_EVIDENCE, fatal=True) from None


def _same_fill(left, right):
    return all(getattr(left, field.name) == getattr(right, field.name)
               for field in fields(left) if field.name != "observed_at_ms")


def _observation(placement, order):
    try:
        result = replace(placement, broker_order_id=order.broker_order_id,
                         order_status=order.status.value, external_status=None,
                         observed_at_ms=_milliseconds(order.fetched_at))
    except RuntimeStoreError:
        raise _Issue(RuntimeReason.INCONSISTENT_EVIDENCE, fatal=True) from None
    try:
        return replace(result, external_status=order.external_status)
    except RuntimeStoreError:
        # Optional diagnostics must obey the frozen safe-text storage contract.
        # Retain the normalized UNKNOWN enum even for unsafe future status text.
        return result


def _views(actions, opens, executions, config, now_ms):
    """Validate exact mappings, never adopt a prefix or unrelated open order."""
    placements = tuple(action for action in actions if action.kind != JournalActionKind.CANCEL)
    links = {action.order_link_id: action for action in placements}
    orders = {action.broker_order_id: action for action in placements if action.broker_order_id is not None}
    candidates = {}
    if type(opens) is not tuple or type(executions) is not tuple:
        raise _Issue(RuntimeReason.INCONSISTENT_EVIDENCE, fatal=True)
    for order in opens:
        if not isinstance(order, OrderState):
            raise _Issue(RuntimeReason.INCONSISTENT_EVIDENCE, fatal=True)
        if not isinstance(order.order_link_id, (str, type(None))) or order.status in _ORDER_TERMINAL:
            raise _Issue(RuntimeReason.INCONSISTENT_EVIDENCE, fatal=True)
        action = links.get(order.order_link_id)
        if action is None and order.order_link_id is None and order.broker_order_id in orders:
            if orders[order.broker_order_id].phase not in _TERMINAL:
                raise _Issue(RuntimeReason.EVIDENCE_MISSING)
        if action is None or action.phase in _TERMINAL:
            raise _Issue(RuntimeReason.OWNERSHIP_CONFLICT, fatal=True)
        _order_identity(order, action, config, now_ms)
        candidates.setdefault(action.logical_action_id, set()).add(order.broker_order_id)
    for execution in executions:
        if not isinstance(execution, ExecutionState):
            raise _Issue(RuntimeReason.INCONSISTENT_EVIDENCE, fatal=True)
        if not isinstance(execution.order_link_id, (str, type(None))) or not isinstance(execution.broker_order_id, str):
            raise _Issue(RuntimeReason.INCONSISTENT_EVIDENCE, fatal=True)
        _common(execution, config, now_ms)
        if execution.symbol != config.symbol:
            raise _Issue(RuntimeReason.OWNERSHIP_CONFLICT, fatal=True)
        action = links.get(execution.order_link_id)
        if action is None:
            if execution.order_link_id is None and execution.broker_order_id in orders:
                raise _Issue(RuntimeReason.EVIDENCE_MISSING)
            if execution.broker_order_id in orders or (execution.order_link_id or "").startswith(config.bot_id + "-"):
                raise _Issue(RuntimeReason.OWNERSHIP_CONFLICT, fatal=True)
            continue  # Unrelated historical executions do not establish ownership.
        _execution(execution, action, config, now_ms)
        candidates.setdefault(action.logical_action_id, set()).add(execution.broker_order_id)
    if any(len(ids) > 1 for ids in candidates.values()):
        raise _Issue(RuntimeReason.OWNERSHIP_CONFLICT, fatal=True)
    return links, candidates


def _evaluate(actions, durable, retained, checkpoint, account, opens, executions, order, placement, config, now_ms):
    if not isinstance(account, AccountState) or type(account.balances) is not tuple:
        raise _Issue(RuntimeReason.INCONSISTENT_EVIDENCE, fatal=True)
    _common(account, config, now_ms)
    links, _ = _views(actions, opens, executions, config, now_ms)
    baseline = _inventory(durable, config)
    if checkpoint.snapshot.owned_base_quantity is not None and checkpoint.snapshot.owned_base_quantity != baseline:
        raise _Issue(RuntimeReason.INCONSISTENT_EVIDENCE, fatal=True)
    merged = {fill.broker_execution_id: fill for fill in durable}
    new = {}
    for execution in executions:
        action = links.get(execution.order_link_id)
        if action is None:
            continue
        owned = _execution(execution, action, config, now_ms)
        previous = merged.get(owned.broker_execution_id)
        if previous is not None:
            if not _same_fill(previous, owned):
                raise _Issue(RuntimeReason.OWNERSHIP_CONFLICT, fatal=True)
        else:
            if placement is None or action.logical_action_id != placement.logical_action_id or action.phase in _TERMINAL:
                raise _Issue(RuntimeReason.INCONSISTENT_EVIDENCE, fatal=True)
            merged[owned.broker_execution_id] = new[owned.broker_execution_id] = owned
    filled_actions = {fill.action_id for fill in durable}
    for action in actions:
        if action.phase == ActionPhase.TERMINAL_CONFIRMED and action.kind != JournalActionKind.CANCEL and action.order_status == "FILLED":
            if action.logical_action_id not in filled_actions:
                raise _Issue(RuntimeReason.INCONSISTENT_EVIDENCE, fatal=True)
    quantity = _inventory(tuple(merged.values()), config)
    if placement is not None:
        if order is None:
            raise _Issue(RuntimeReason.ACTION_OUTCOME_UNKNOWN)
        _order_identity(order, placement, config, now_ms)
        if order.status in (OrderStatus.UNKNOWN, OrderStatus.NEW):
            raise _Issue(RuntimeReason.ACTION_OUTCOME_UNKNOWN, observation=_observation(placement, order))
        matching = retained + tuple(new.values())
        total_base = _sum(fill.executed_quantity for fill in matching)
        if total_base != order.filled_base_quantity:
            raise _Issue(RuntimeReason.EVIDENCE_MISSING)
        if order.filled_quote_amount is not None and _sum(_product(fill.executed_quantity, fill.execution_price) for fill in matching) != order.filled_quote_amount:
            raise _Issue(RuntimeReason.EVIDENCE_MISSING)
        if any(fill.executed_at_ms < _milliseconds(order.created_at) or fill.executed_at_ms > _milliseconds(order.updated_at) for fill in matching):
            raise _Issue(RuntimeReason.EVIDENCE_MISSING)
        if (order.status == OrderStatus.OPEN and total_base != 0
                or order.status == OrderStatus.PARTIALLY_FILLED and total_base == 0
                or order.status == OrderStatus.FILLED and (total_base == 0 or (order.quantity_unit == "BASE" and order.remaining_quantity != 0))
                or order.status == OrderStatus.REJECTED and total_base != 0):
            raise _Issue(RuntimeReason.INCONSISTENT_EVIDENCE, fatal=True)
        for earlier in opens:
            if earlier.broker_order_id == order.broker_order_id and (earlier.status != order.status or earlier.filled_base_quantity != order.filled_base_quantity):
                raise _Issue(RuntimeReason.EVIDENCE_MISSING)
    balances = {}
    for balance in account.balances:
        if (not isinstance(balance, CurrencyBalance) or not isinstance(balance.currency, str)
                or not balance.currency or not balance.currency.isupper() or balance.currency in balances):
            raise _Issue(RuntimeReason.INCONSISTENT_EVIDENCE, fatal=True)
        _number(balance.total_balance, signed=True)
        balances[balance.currency] = balance.total_balance
    if quantity > 0:
        if config.base_currency not in balances:
            raise _Issue(RuntimeReason.EVIDENCE_MISSING)
        # walletBalance includes locked holdings; availability and USD aggregates
        # are not an asset-coverage bound or ownership/SELL authorization.
        if balances[config.base_currency] < quantity:
            raise _Issue(RuntimeReason.INCONSISTENT_EVIDENCE, fatal=True)
        if any(fill.executed_at_ms > _milliseconds(account.broker_timestamp) for fill in merged.values()):
            raise _Issue(RuntimeReason.EVIDENCE_MISSING)
    return quantity, tuple(new.values())


def _checkpoint(current, event, now_ms, *, reconciled=False):
    snapshot = transition_runtime_state(current.snapshot, event)
    return replace(current, sequence=current.sequence + 1, snapshot=snapshot,
                   halted_at_ms=now_ms if snapshot.state == RuntimeState.HALTED else None,
                   observed_at_ms=now_ms if reconciled else current.observed_at_ms,
                   last_reconciled_at_ms=now_ms if reconciled else current.last_reconciled_at_ms)


def _result(store, placement, cancellation, new=()):
    return ReconciliationResult(store.get_checkpoint(),
                                None if placement is None else store.get_action(placement.logical_action_id),
                                None if cancellation is None else store.get_action(cancellation.logical_action_id),
                                tuple(fill.broker_execution_id for fill in new))


def reconcile_startup(
    store: RuntimeStore,
    broker: ReadOnlyBroker,
    *,
    utc_now: Callable[[], datetime],
    monotonic: Callable[[], float] = monotonic_clock,
) -> ReconciliationResult:
    """Acquire at most one complete read round and persist its validated result.

    One round/read-attempt token per unresolved attempted action is reserved
    durably BEFORE I/O. No retry is performed; restart cannot restore tokens.
    Limits are checked between calls, not an interruption of a paginated SDK
    call. utc_now is a control clock, never a substitute for broker timestamps.
    HALTED/STOPPING return unchanged; explicit rearm belongs to the caller.
    """
    if not isinstance(store, RuntimeStore) or not callable(utc_now) or not callable(monotonic):
        raise ReconciliationError("An open RuntimeStore and explicit clocks are required.")
    if not all(callable(getattr(broker, name, None)) for name in
               ("get_account_state", "get_open_orders", "get_order", "get_executions")):
        raise ReconciliationError("The four ReadOnlyBroker operations are required.")
    start_ms, start_elapsed = _clock(utc_now, monotonic)
    last_control_ms = start_ms
    config = store.get_configuration()
    current = store.get_checkpoint()
    actions, durable = store.list_actions(), store.list_fills()
    placement = next((action for action in actions if action.kind != JournalActionKind.CANCEL and action.phase not in _TERMINAL), None)
    cancellation = next((action for action in actions if action.kind == JournalActionKind.CANCEL and action.phase not in _TERMINAL), None)
    retained = () if placement is None else store.list_fills(placement.logical_action_id)
    if current.snapshot.state in (RuntimeState.HALTED, RuntimeState.STOPPING):
        return _result(store, placement, cancellation)
    discovered = None

    def problem(issue):
        nonlocal current, placement
        exhausted = any(action is not None and action.phase not in _TERMINAL
                        and (action.remaining_reconciliation_rounds == 0 or action.remaining_read_attempts == 0)
                        for action in (placement, cancellation))
        fatal = issue.fatal or exhausted
        reason = RuntimeReason.RECOVERY_EXHAUSTED if exhausted and not issue.fatal else issue.reason
        event = RuntimeEvent(RuntimeEventType.FATAL_INCONSISTENCY if fatal else RuntimeEventType.UNCERTAINTY_DETECTED, reason=reason)
        cp = _checkpoint(current, event, last_control_ms)
        observation = issue.observation or (discovered if not issue.fatal else None)
        if observation is not None:
            store.record_observation(observation, cp, expected_sequence=current.sequence)
            placement = observation
        else:
            store.save_checkpoint(cp, expected_sequence=current.sequence)
        current = cp
        return _result(store, placement, cancellation)

    try:
        if config.broker_account_id is not None:
            # Stage 9 account_id is only a caller label, not verified exchange UID.
            raise _Issue(RuntimeReason.INVALID_CONFIGURATION, fatal=True)
        if current.observed_at_ms is not None and start_ms < current.observed_at_ms:
            raise _Issue(RuntimeReason.INVALID_CONFIGURATION, fatal=True)
        state = current.snapshot.state
        if state in (RuntimeState.STARTING, RuntimeState.FLAT, RuntimeState.LONG):
            kind = RuntimeEventType.STARTUP_VALIDATED if state == RuntimeState.STARTING else RuntimeEventType.FRESHNESS_LOST
            cp = _checkpoint(current, RuntimeEvent(kind), start_ms)
            store.save_checkpoint(cp, expected_sequence=current.sequence)
            current = cp
        for action in (cancellation, placement):
            if action is not None and action.phase == ActionPhase.PREPARED:
                cp = current
                if action.kind != JournalActionKind.CANCEL:
                    uncertain = _checkpoint(current, RuntimeEvent(RuntimeEventType.UNCERTAINTY_DETECTED, reason=RuntimeReason.EVIDENCE_MISSING), start_ms)
                    store.save_checkpoint(uncertain, expected_sequence=current.sequence)
                    current = uncertain
                    event = RuntimeEvent(RuntimeEventType.RECOVERY_VALIDATED,
                                         evidence=RuntimeEvidence(_inventory(durable, config), terminal_action_id=action.logical_action_id))
                    cp = _checkpoint(current, event, start_ms)
                else:
                    cp = replace(current, sequence=current.sequence + 1)
                store.abandon_prepared(action.logical_action_id, cp, expected_sequence=current.sequence, terminal_at_ms=start_ms)
                current = cp
                if action.kind == JournalActionKind.CANCEL:
                    cancellation = store.get_action(action.logical_action_id)
                else:
                    placement = None
        active = tuple(action for action in (placement, cancellation) if action is not None and action.phase not in _TERMINAL)
        if any(start_ms >= action.reconciliation_deadline_ms or action.remaining_reconciliation_rounds == 0
               or action.remaining_read_attempts == 0 for action in active):
            raise _Issue(RuntimeReason.RECOVERY_EXHAUSTED, fatal=True)
        for action in active:
            reserved = replace(action, remaining_reconciliation_rounds=action.remaining_reconciliation_rounds - 1,
                               remaining_read_attempts=action.remaining_read_attempts - 1,
                               phase=ActionPhase.UNKNOWN_OUTCOME if action.phase == ActionPhase.ATTEMPT_STARTED else action.phase,
                               safe_reason=RuntimeReason.ACTION_OUTCOME_UNKNOWN if action.phase == ActionPhase.ATTEMPT_STARTED else action.safe_reason)
            cp = _checkpoint(current, RuntimeEvent(RuntimeEventType.UNCERTAINTY_DETECTED, reason=RuntimeReason.EVIDENCE_MISSING), start_ms)
            store.record_observation(reserved, cp, expected_sequence=current.sequence)
            current = cp
            if action.kind == JournalActionKind.CANCEL:
                cancellation = reserved
            else:
                placement = reserved
        actions = store.list_actions()

        def limits():
            nonlocal last_control_ms
            now_ms, elapsed = _clock(utc_now, monotonic)
            duration = elapsed - start_elapsed
            if duration < 0 or now_ms < start_ms or abs((now_ms - start_ms) - duration * 1000) > config.max_clock_skew_ms:
                raise _Issue(RuntimeReason.INVALID_CONFIGURATION, fatal=True)
            last_control_ms = now_ms
            if duration * 1000 >= config.reconciliation_timeout_ms or any(now_ms >= action.reconciliation_deadline_ms for action in active):
                raise _Issue(RuntimeReason.RECOVERY_EXHAUSTED, fatal=True)
            return now_ms

        def read(operation, **kwargs):
            limits()
            try:
                result = operation(**kwargs)
            except BrokerOrderNotFoundError:
                raise
            except BrokerReadError as error:
                if error.kind is BrokerReadFailureKind.TRANSIENT:
                    raise _Issue(RuntimeReason.EVIDENCE_MISSING) from None
                reason = (RuntimeReason.INVALID_CONFIGURATION
                          if error.kind is BrokerReadFailureKind.INVALID_CONFIGURATION
                          else RuntimeReason.INCONSISTENT_EVIDENCE)
                raise _Issue(reason, fatal=True) from None
            except Exception:
                raise _Issue(RuntimeReason.INCONSISTENT_EVIDENCE, fatal=True) from None
            limits()
            return result

        account = read(broker.get_account_state)
        if not isinstance(account, AccountState):
            raise _Issue(RuntimeReason.INCONSISTENT_EVIDENCE, fatal=True)
        _common(account, config, limits())
        opens = read(broker.get_open_orders, symbol=config.symbol)
        executions = read(broker.get_executions, symbol=config.symbol)
        _, candidates = _views(actions, opens, executions, config, limits())
        order = None
        if placement is not None:
            found = candidates.get(placement.logical_action_id, set())
            if placement.broker_order_id is not None:
                found = found | {placement.broker_order_id}
            if len(found) > 1:
                raise _Issue(RuntimeReason.OWNERSHIP_CONFLICT, fatal=True)
            if not found:
                raise _Issue(RuntimeReason.ACTION_OUTCOME_UNKNOWN)
            order_id = next(iter(found))
            if placement.broker_order_id is None:
                try:
                    discovered = replace(placement, broker_order_id=order_id)
                except RuntimeStoreError:
                    raise _Issue(RuntimeReason.INCONSISTENT_EVIDENCE, fatal=True) from None
            try:
                order = read(broker.get_order, order_id=order_id)
            except BrokerOrderNotFoundError:
                pass  # Absence is uncertainty, never failed-placement proof.
            if order is not None and (not isinstance(order, OrderState) or order.broker_order_id != order_id):
                raise _Issue(RuntimeReason.OWNERSHIP_CONFLICT, fatal=True)
            exact = read(broker.get_executions, order_id=order_id)
            if type(exact) is not tuple or any(not isinstance(fill, ExecutionState) or fill.broker_order_id != order_id for fill in exact):
                raise _Issue(RuntimeReason.OWNERSHIP_CONFLICT, fatal=True)
            # Exact-order results cannot be filtered as unrelated history. Bind
            # every execution even when discovery has not yet persisted the ID.
            for execution in exact:
                _execution(execution, discovered or placement, config, limits())
            executions += exact
        now_ms = limits()
        quantity, new = _evaluate(actions, durable, retained, current, account, opens, executions, order, placement, config, now_ms)
        now_ms = limits()  # Computation must not carry expired evidence into a commit.
        for record in (account, *opens, *executions, *((order,) if order is not None else ())):
            _common(record, config, now_ms)
        if placement is None:
            event = RuntimeEvent(RuntimeEventType.RECONCILED_FLAT if quantity == 0 else RuntimeEventType.RECONCILED_LONG,
                                 evidence=RuntimeEvidence(quantity))
            cp = _checkpoint(current, event, now_ms, reconciled=True)
            store.save_checkpoint(cp, expected_sequence=current.sequence)
            return _result(store, None, cancellation)
        observed = _observation(placement, order)
        terminal = order.status in _ORDER_TERMINAL
        if cancellation is not None and cancellation.phase not in _TERMINAL:
            if not terminal and cancellation.phase == ActionPhase.UNKNOWN_OUTCOME:
                raise _Issue(RuntimeReason.ACTION_OUTCOME_UNKNOWN)
            if terminal:
                # Terminal parent status closes the control's lifecycle, not proof
                # that cancellation succeeded: FILLED may have won the race.
                done = replace(cancellation, phase=ActionPhase.TERMINAL_CONFIRMED, order_status=order.status.value,
                               external_status=order.external_status, observed_at_ms=_milliseconds(order.fetched_at), terminal_at_ms=now_ms)
                cp = replace(current, sequence=current.sequence + 1)
                store.record_observation(done, cp, expected_sequence=current.sequence)
                current, cancellation = cp, done
        if terminal:
            observed = replace(observed, phase=ActionPhase.TERMINAL_CONFIRMED, terminal_at_ms=now_ms)
            event = RuntimeEvent(RuntimeEventType.RECONCILED_FLAT if quantity == 0 else RuntimeEventType.RECONCILED_LONG,
                                 evidence=RuntimeEvidence(quantity, terminal_action_id=placement.logical_action_id))
        else:
            event = RuntimeEvent(RuntimeEventType.RECONCILED_PENDING,
                                 evidence=RuntimeEvidence(quantity, current.snapshot.pending_action))
        cp = _checkpoint(current, event, now_ms, reconciled=True)
        store.record_observation(observed, cp, expected_sequence=current.sequence, fills=new)
        return _result(store, observed, cancellation, new)
    except _Issue as issue:
        return problem(issue)
