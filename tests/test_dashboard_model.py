"""Synthetic parser records, never a future executable runtime configuration."""

from dataclasses import FrozenInstanceError, replace
from decimal import Decimal as D
import hashlib
from pathlib import Path
import unittest

from trading_lab.dashboard import *
from trading_lab.dashboard.analytics import instance_name
from trading_lab.dashboard.formatting import field_rows
from trading_lab.observability import health as h, model as m
from tests import test_observability_model as event_fixtures

AT = 3_601_000
T = m.ObservabilityEventType


def health_fixture(*, strategy="ema_trend", symbol="BTCUSDT", bot="bot1", state="FLAT", active=True,
                   trip=False, **changes):
    values = dict.fromkeys(h.HEALTH_FIELDS)
    values.update(observability_version=1, generated_at_ms=AT, run_id="0"*32,
        broker_id="bybit-demo", account_binding="research", bot_id=bot, strategy_id=strategy,
        symbol=symbol, timeframe="60", process_started_at_ms=0, last_scheduler_activity_ms=AT,
        last_cycle_activity_ms=AT, last_cycle_outcome="NOOP", observability_status="OK",
        checkpoint_sequence=1, runtime_state=state, position_evidence="CONFIRMED",
        owned_base_quantity="0", desired_position=0, last_processed_candle_ms=0,
        last_reconciled_at_ms=AT, last_broker_observation_at_ms=AT, risk_active=active,
        latest_accepted_candle_open_ms=0, latest_accepted_mark_price="100", market_valued_at_ms=3_600_000,
        generated_freshness="FRESH", market_freshness="FRESH", reconciliation_freshness="FRESH",
        broker_freshness="FRESH", risk_freshness="FRESH", overall_health="OK", reason_codes=[])
    if active:
        config = dict(risk_contract_version=1, risk_capital_quote="1000", buy_quote_budget="10",
            max_entry_notional_quote="200", max_position_notional_quote="500", max_daily_loss_fraction="0.1",
            max_drawdown_fraction="0.2", max_entries_per_utc_day=2, base_currency=symbol[:-4], quote_currency="USDT")
        values.update({key: value for key, value in config.items() if key != "risk_contract_version"})
        values.update(risk_configuration_digest=hashlib.sha256(m.canonical_bytes(config)).hexdigest(),
            risk_epoch_id="a"*64, risk_epoch_sequence=1, valued_at_ms=3_600_000, risk_equity="1000",
            peak_risk_equity="1000", utc_day_start_risk_equity="1000", daily_pnl="0",
            entries_this_utc_day=0, drawdown_numerator="0", drawdown_denominator="1000")
    else:
        values["risk_freshness"] = "UNKNOWN"
    if state in ("LONG", "ORDER_PENDING"):
        values.update(owned_base_quantity="0.1", desired_position=1)
    if state == "ORDER_PENDING":
        values.update(pending_action_id="c"*64, pending_action_kind="ENTRY", pending_action_phase="ACKNOWLEDGED",
                      pending_reconciliation_deadline_ms=AT+600_000)
    if state in ("HALTED", "UNCERTAIN"):
        values.update(position_evidence="LAST_KNOWN", runtime_reason="EVIDENCE_MISSING")
        if state == "HALTED":
            values["halted_at_ms"] = AT
    if trip:
        values.update(risk_trip_reason="DAILY_LOSS_LIMIT", tripped_at_ms=3_600_000)
    values.update(changes)
    # Fixture presentation codes are explicit; production parsing remains frozen.
    critical, attention = [], []
    if state in ("HALTED", "UNCERTAIN"):
        critical.append("RUNTIME_" + state)
    if not active:
        attention.append("RISK_NOT_READY")
    if trip:
        attention.append("RISK_TRIPPED")
    for group in ("market", "reconciliation", "broker", "risk"):
        if values[group + "_freshness"] != "FRESH":
            attention.append(group.upper() + "_" + values[group + "_freshness"])
    values.update(overall_health="CRITICAL" if critical else "ATTENTION" if attention else "OK",
                  reason_codes=critical + attention)
    return h.health_from_json(m.canonical_bytes(values))


def event_fixture(kind=T.PROCESS_STARTED, *, strategy="ema_trend", symbol="BTCUSDT", bot="bot1",
                  sequence=1, observed=AT, occurred=AT, details=None, **changes):
    original = event_fixtures.sample(kind)
    values = original.to_dict()
    values.update(strategy_id=strategy, symbol=symbol, bot_id=bot, observed_at_ms=observed, occurred_at_ms=occurred)
    if values["checkpoint_sequence"] is not None:
        values["checkpoint_sequence"] = sequence
    if details:
        values.update({key: m.encode_value(key, value) for key, value in details.items()})
    values.update(changes)
    decoded = {key: m.decode_value(key, value) for key, value in values.items()}
    detail_values = {key: decoded[key] for key in values if key not in m.ENVELOPE_FIELDS}
    # Frozen hashing creates synthetic canonical records, not a RuntimeConfiguration.
    values["event_id"] = m._id(kind, decoded, detail_values,
        "fixture" + str(sequence) if kind in m.PROCESS_TYPES else None)
    return m.event_from_json(m.canonical_bytes(values))


def write_instance(root, health=None, events=()):
    health = health or health_fixture()
    root = Path(root)
    root.mkdir(mode=0o700, exist_ok=True)
    directory = root / instance_name(health)
    directory.mkdir(mode=0o700, exist_ok=True)
    path = directory / "health.json"
    path.write_bytes(health.to_json())
    path.chmod(0o600)
    groups = {}
    for event in events:
        name = "events-" + format_timestamp(event.observed_at_ms)[:10] + ".jsonl"
        groups.setdefault(name, []).append(event.to_json() + b"\n")
    for name, lines in groups.items():
        path = directory / name
        path.write_bytes(b"".join(lines))
        path.chmod(0o600)
    return directory


class DashboardModelTests(unittest.TestCase):
    def test_generic_identity_same_shape_and_six_views(self):
        models = [build_dashboard_model(health_fixture(strategy=strategy, symbol=symbol, bot=bot),
                  (event_fixture(strategy=strategy, symbol=symbol, bot=bot),), now_ms=AT)
                  for strategy, symbol, bot in (("ema_trend", "BTCUSDT", "bot1"), ("donchian", "ETHUSDT", "bot2"))]
        self.assertEqual(type(models[0]), type(models[1]))
        self.assertEqual(models[0].views, DASHBOARD_VIEWS)
        self.assertEqual(models[1].views, DASHBOARD_VIEWS)
        self.assertEqual(len(DASHBOARD_VIEWS), 6)
        self.assertEqual(models[1].identity.strategy_id, "donchian")
        self.assertIn("ETHUSDT", models[1].identity.label)
        self.assertNotEqual(models[0].identity.instance_name, models[1].identity.instance_name)

    def test_model_and_nested_records_immutable(self):
        model = build_dashboard_model(health_fixture(), now_ms=AT)
        for target, field, value in ((model, "events", ()), (model.identity, "symbol", "OTHER"),
                                      (model.overview, "snapshot_age_ms", 0)):
            with self.assertRaises(FrozenInstanceError):
                setattr(target, field, value)
            self.assertFalse(hasattr(target, "__dict__"))

    def test_flat_and_long_preserve_exact_current_exposure(self):
        for state, quantity in (("FLAT", D(0)), ("LONG", D("0.1"))):
            model = build_dashboard_model(health_fixture(state=state), now_ms=AT)
            self.assertEqual(model.health.owned_base_quantity, quantity)
            self.assertEqual(model.health.runtime_state.value, state)

    def test_pending_ack_not_a_fill_or_trade(self):
        model = build_dashboard_model(health_fixture(state="ORDER_PENDING"),
                                      (event_fixture(T.ACTION_ACKNOWLEDGED),), now_ms=AT)
        self.assertEqual(model.health.pending_action_phase.value, "ACKNOWLEDGED")
        self.assertEqual(model.trades, ())

    def test_halt_and_uncertain_remain_critical(self):
        for state in ("HALTED", "UNCERTAIN"):
            model = build_dashboard_model(health_fixture(state=state), now_ms=AT+999999)
            self.assertEqual(model.overview.display_health.value, "CRITICAL")
            self.assertEqual(model.health.runtime_reason.value, "EVIDENCE_MISSING")

    def test_trip_is_attention_not_runtime_halt(self):
        model = build_dashboard_model(health_fixture(trip=True), now_ms=AT)
        self.assertEqual(model.health.runtime_state.value, "FLAT")
        self.assertEqual(model.health.risk_trip_reason.value, "DAILY_LOSS_LIMIT")
        self.assertEqual(model.overview.display_health.value, "ATTENTION")

    def test_not_ready_risk_values_unavailable_not_zero(self):
        model = build_dashboard_model(health_fixture(active=False), now_ms=AT)
        self.assertIsNone(model.health.risk_equity)
        self.assertEqual(format_value(model.health.risk_equity), "Unavailable")
        self.assertEqual(model.overview.display_health.value, "ATTENTION")

    def test_snapshot_ages_inclusively_at_display_boundary(self):
        health = health_fixture()
        first = build_dashboard_model(health, now_ms=AT+120000)
        later = build_dashboard_model(health, now_ms=AT+120001)
        self.assertEqual(first.overview.snapshot_freshness.value, "FRESH")
        self.assertEqual(later.overview.snapshot_freshness.value, "STALE")
        self.assertEqual(later.overview.display_health.value, "ATTENTION")
        self.assertEqual(later.health.overall_health.value, "OK")
        self.assertEqual(later.health.generated_freshness.value, "FRESH")

    def test_future_snapshot_unknown_age_not_zero(self):
        model = build_dashboard_model(health_fixture(), now_ms=AT-1)
        self.assertIsNone(model.overview.snapshot_age_ms)
        self.assertEqual(model.overview.snapshot_freshness.value, "UNKNOWN")

    def test_underlying_stale_and_unknown_evidence_not_refreshed(self):
        for value in ("STALE", "UNKNOWN"):
            health = health_fixture(market_freshness=value)
            model = build_dashboard_model(health, now_ms=AT)
            self.assertEqual(model.health.market_freshness.value, value)
            self.assertEqual(model.overview.display_health.value, "ATTENTION")

    def test_all_six_identity_fields_bound_to_health(self):
        for changes in (dict(strategy="donchian"), dict(bot="bot2"), dict(symbol="ETHUSDT")):
            with self.subTest(changes=changes), self.assertRaises(DashboardError):
                build_dashboard_model(health_fixture(), (event_fixture(**changes),), now_ms=AT)

    def test_invalid_time_and_limits_rejected(self):
        for changes in (dict(now_ms=True), dict(now_ms=-1), dict(limit=True), dict(limit=1001),
                        dict(snapshot_max_age_ms=0), dict(snapshot_max_age_ms=86_400_001)):
            with self.subTest(changes=changes), self.assertRaises(DashboardError):
                build_dashboard_model(health_fixture(), **{**dict(now_ms=AT), **changes})

    def test_validated_records_required(self):
        for health, events in (({}, ()), (health_fixture(), ({},)), (health_fixture(), [])):
            with self.assertRaises(DashboardError):
                build_dashboard_model(health, events, now_ms=AT)

    def test_exact_decimal_and_null_zero_distinct(self):
        self.assertEqual(format_value(D("123456789.12345678901234567890123456789")),
                         "123456789.12345678901234567890123456789")
        self.assertEqual(format_value(D("-0.000")), "0")
        self.assertEqual(format_value(D("1E-20")), "0.00000000000000000001")
        self.assertEqual(format_value(None), "Unavailable")
        self.assertEqual(format_value(D(0)), "0")
        self.assertEqual(format_value(D("1.2300")), "1.23")

    def test_utc_and_full_identifiers_in_details(self):
        self.assertEqual(format_timestamp(1), "1970-01-01 00:00:00.001 UTC")
        self.assertEqual(format_timestamp(None), "Unavailable")
        rows = field_rows(health_fixture(state="ORDER_PENDING"), ("pending_action_id", "last_reconciled_at_ms"))
        self.assertEqual(rows[0]["Value"], "c"*64)
        self.assertIn("UTC", rows[1]["Value"])

    def test_unsafe_format_values_not_dumped(self):
        for value in (object(), {}, D("NaN"), 1.0):
            with self.assertRaises(DashboardError):
                format_value(value)
