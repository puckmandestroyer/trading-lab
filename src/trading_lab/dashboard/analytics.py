"""Pure, conservative display derivations from validated observability only."""

from decimal import Decimal, ROUND_HALF_UP, localcontext
import hashlib

from ..observability.health import HealthSnapshot, health_from_json
from ..observability.model import (ObservabilityEvent, ObservabilityEventType as T,
    ObservabilityError, EvidenceFreshness, ObservabilityHealthLevel, canonical_bytes, event_from_json)
from .model import (DashboardError, DashboardNotice, DashboardInstance, DashboardOverview,
    DashboardExecution, DashboardTrade, DashboardModel, DEFAULT_HISTORY_LIMIT, MAX_HISTORY_LIMIT,
    SNAPSHOT_MAX_AGE_MS)

MAX_INPUT_RECORDS = 10_000
IDENTITY_FIELDS = ("broker_id", "account_binding", "bot_id", "strategy_id", "symbol", "timeframe")


def instance_name(record):
    """Match frozen storage identity; strategy/symbol remain explicit in the model."""
    return hashlib.sha256(canonical_bytes({key: getattr(record, key)
        for key in ("broker_id", "account_binding", "bot_id")})).hexdigest()


def _limit(value, maximum):
    if type(value) is not int or not 1 <= value <= maximum:
        raise DashboardError("Invalid dashboard resource bound.")


def event_order(event):
    return (event.observed_at_ms, -1 if event.occurred_at_ms is None else event.occurred_at_ms, event.event_id)


def recent_events(events, *, limit=DEFAULT_HISTORY_LIMIT):
    """Latest observation wins per stable ID; canonical bytes break exact time ties."""
    _limit(limit, MAX_HISTORY_LIMIT)
    if type(events) is not tuple or len(events) > MAX_INPUT_RECORDS:
        raise DashboardError("Invalid dashboard event history.")
    unique = {}
    try:
        for event in events:
            if type(event) is not ObservabilityEvent:
                raise DashboardError("Validated dashboard events required.")
            event_from_json(event.to_json())
            old = unique.get(event.event_id)
            if old is None or (event_order(event), event.to_json()) > (event_order(old), old.to_json()):
                unique[event.event_id] = event
    except ObservabilityError:
        raise DashboardError("Invalid dashboard event history.") from None
    return tuple(sorted(unique.values(), key=event_order, reverse=True)[:limit])


def display_percentage(numerator, denominator):
    """Six decimal places for presentation only; source amounts stay exact."""
    if numerator is None or denominator is None:
        return None
    if (type(numerator) is not Decimal or type(denominator) is not Decimal
            or not numerator.is_finite() or not denominator.is_finite()
            or numerator < 0 or denominator <= 0):
        raise DashboardError("Invalid display ratio.")
    with localcontext() as context:
        context.prec = max(80, len(numerator.as_tuple().digits) + len(denominator.as_tuple().digits)
                           + abs(numerator.adjusted() - denominator.adjusted()) + 20)
        return (numerator * 100 / denominator).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


def reconstruct_trades(events):
    """Pair retained confirmed transitions, never signals, ACKs or current LONG.

    Position checkpoints order durable transitions, independently of catch-up
    observation order. Missing/inconsistent transitions leave history incomplete.
    Fees are individual referenced executions, never guessed currency conversions.
    """
    executions = {}
    positions = []
    for event in events:
        values = dict(event.details)
        if event.event_type is T.OWNED_EXECUTION_DISCOVERED:
            executions[values["broker_execution_id"]] = DashboardExecution(
                values["broker_execution_id"], values["side"], values["executed_quantity"],
                values["execution_price"], values["execution_fee"], values.get("fee_currency"), values["executed_at_ms"])
        if event.event_type in (T.POSITION_OPEN_CONFIRMED, T.POSITION_CLOSE_CONFIRMED, T.POSITION_QUANTITY_CHANGED):
            positions.append(event)
    positions.sort(key=lambda event: (event.checkpoint_sequence, event.event_id))
    sequences = [event.checkpoint_sequence for event in positions]
    if len(set(sequences)) != len(sequences):
        return (), True, None
    active, quantity, entries, exits = None, None, [], []
    trades, incomplete = [], False

    def references(values, name, *, include_contributing=True):
        ids = list(values.get("contributing_execution_ids") or ()) if include_contributing else []
        ids.extend(dict(fill)["broker_execution_id"] for fill in values.get(name) or ()
                   if dict(fill).get("broker_execution_id") is not None)
        return list(dict.fromkeys(ids))

    for event in positions:
        values = dict(event.details)
        before, after = values["previous_owned_base_quantity"], values["owned_base_quantity"]
        if event.event_type is T.POSITION_OPEN_CONFIRMED:
            incomplete |= active is not None
            active, quantity = event, after
            entries, exits = references(values, "entry_fills"), []
        elif active is None or before != quantity:
            incomplete = True
            active = None
        elif event.event_type is T.POSITION_QUANTITY_CHANGED:
            target = entries if after > before else exits
            target.extend(references(values, "entry_fills" if after > before else "exit_fills"))
            quantity = after
        else:
            if (active.occurred_at_ms is not None and event.occurred_at_ms is not None
                    and event.occurred_at_ms < active.occurred_at_ms):
                incomplete, active = True, None
                continue
            entries.extend(references(values, "entry_fills", include_contributing=False))
            exits.extend(references(values, "exit_fills"))
            entry_ids, exit_ids = tuple(dict.fromkeys(entries)), tuple(dict.fromkeys(exits))
            referenced = tuple(executions[key] for key in dict.fromkeys(entry_ids + exit_ids) if key in executions)
            trades.append(DashboardTrade(active.event_id, event.event_id, active.occurred_at_ms,
                event.occurred_at_ms, dict(active.details)["owned_base_quantity"], before,
                entry_ids, exit_ids, referenced, values.get("realized_trade_pnl_quote")))
            active = None
    return tuple(trades), incomplete, quantity if active is not None else None


def build_dashboard_model(health, events=(), *, now_ms, limit=DEFAULT_HISTORY_LIMIT,
                          snapshot_max_age_ms=SNAPSHOT_MAX_AGE_MS, notices=()):
    _limit(snapshot_max_age_ms, 86_400_000)
    if type(now_ms) is not int or not 0 <= now_ms < 2**63:
        raise DashboardError("Invalid dashboard display time.")
    if (type(notices) is not tuple or len(notices) > len(DashboardNotice)
            or any(type(value) is not DashboardNotice for value in notices)):
        raise DashboardError("Invalid dashboard history status.")
    try:
        if type(health) is not HealthSnapshot:
            raise DashboardError("A validated health snapshot is required.")
        health_from_json(health.to_json())
    except ObservabilityError:
        raise DashboardError("Invalid dashboard health snapshot.") from None
    selected = recent_events(events, limit=limit)
    identity = tuple(getattr(health, key) for key in IDENTITY_FIELDS)
    if any(tuple(getattr(event, key) for key in IDENTITY_FIELDS) != identity for event in events):
        raise DashboardError("Dashboard observability identity mismatch.")
    notices = tuple(dict.fromkeys(notices + ((DashboardNotice.HISTORY_LIMITED,)
        if len({event.event_id for event in events}) > limit else ())))
    age = now_ms - health.generated_at_ms
    fresh = (EvidenceFreshness.UNKNOWN if age < 0 else
             EvidenceFreshness.FRESH if age <= snapshot_max_age_ms else EvidenceFreshness.STALE)
    display_health = health.overall_health
    if fresh is not EvidenceFreshness.FRESH and display_health is ObservabilityHealthLevel.OK:
        display_health = ObservabilityHealthLevel.ATTENTION
    if notices and display_health is ObservabilityHealthLevel.OK:
        display_health = ObservabilityHealthLevel.ATTENTION
    overview = DashboardOverview(None if age < 0 else age, fresh, display_health,
                                display_percentage(health.drawdown_numerator, health.drawdown_denominator), snapshot_max_age_ms)
    trades, incomplete, retained_quantity = reconstruct_trades(selected)
    has_transitions = any(event.event_type in (T.POSITION_OPEN_CONFIRMED, T.POSITION_CLOSE_CONFIRMED,
                         T.POSITION_QUANTITY_CHANGED) for event in selected)
    incomplete |= bool(notices) or not has_transitions or (health.owned_base_quantity is not None
        and health.owned_base_quantity > 0 and retained_quantity != health.owned_base_quantity)
    incomplete |= health.owned_base_quantity == 0 and retained_quantity is not None
    return DashboardModel(DashboardInstance(instance_name(health), *identity), health, selected,
                          overview, trades, incomplete, notices)


def filter_events(model, *, severities=(), event_types=()):
    return tuple(event for event in model.events
        if (not severities or event.severity.value in severities)
        and (not event_types or event.event_type.value in event_types))


def history_series(model, field):
    """Exact retained points, never a synthetic history from current health."""
    if field not in ("owned_base_quantity", "risk_equity", "daily_pnl"):
        raise DashboardError("Unsupported dashboard history series.")
    points = {}
    for event in model.events:
        values = dict(event.details)
        if field == "owned_base_quantity" and event.event_type not in (
                T.POSITION_OPEN_CONFIRMED, T.POSITION_CLOSE_CONFIRMED, T.POSITION_QUANTITY_CHANGED):
            continue
        timestamp = event.occurred_at_ms if field == "owned_base_quantity" else values.get("valued_at_ms")
        value = values.get(field)
        if timestamp is not None and type(value) is Decimal:
            key = (timestamp, event.event_id)
            points[key] = value
    return tuple((timestamp, value) for (timestamp, _), value in sorted(points.items()))
