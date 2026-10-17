"""Health reflects durable age and independent latches, never creates health."""

from dataclasses import FrozenInstanceError, replace
from decimal import Decimal as D
import hashlib
import unittest
from unittest.mock import patch

from trading_lab.observability import *
from trading_lab.observability import health as h
from trading_lab.runtime.state import RuntimeState as S, PositionEvidence as P, RuntimeReason as R, RuntimeStateSnapshot, PendingAction, PendingActionKind
from trading_lab.runtime.store import RuntimeCheckpoint, ActionPhase
from trading_lab.runtime.cycle import SingleCycleResult, CycleOutcome
from tests import test_runtime_store as fixtures
from tests import test_runtime_risk_rearm as rearm_fixtures

RUN = "0"*32
HOUR = fixtures.HOUR


def health(store, at=HOUR+1000, **changes):
    return build_health_snapshot(store, run_id=RUN, process_started_at_ms=0, generated_at_ms=at, **changes)


class FreshnessTests(unittest.TestCase):
    def test_inclusive_boundary_and_stale_next_ms(self):
        self.assertIs(freshness(100, 40, 60), EvidenceFreshness.FRESH)
        self.assertIs(freshness(101, 40, 60), EvidenceFreshness.STALE)

    def test_missing_and_future_are_unknown(self):
        self.assertIs(freshness(100, None, 60), EvidenceFreshness.UNKNOWN)
        self.assertIs(freshness(100, 101, 60), EvidenceFreshness.UNKNOWN)

    def test_invalid_times_and_age_bounds(self):
        for args in ((True, 0, 1), (0, -1, 1), (0, 0, 0), (1.0, 0, 1)):
            with self.subTest(args=args), self.assertRaises(ObservabilityValidationError):
                freshness(*args)


class HealthTests(fixtures.RiskPersistenceCase):
    def fresh(self):
        self.activate()
        cp = self.store.get_checkpoint()
        self.store.save_checkpoint(replace(cp, sequence=cp.sequence+1, last_reconciled_at_ms=HOUR,
                                          observed_at_ms=HOUR), expected_sequence=cp.sequence)

    def test_empty_risk_is_not_ready_not_zero_or_disabled(self):
        result = health(self.store)
        self.assertFalse(result.risk_active)
        self.assertIsNone(result.risk_equity)
        self.assertIsNone(result.entries_this_utc_day)
        self.assertIs(result.overall_health, ObservabilityHealthLevel.ATTENTION)
        self.assertIn(HealthReason.RISK_NOT_READY, result.reason_codes)
        self.assertIs(result.market_freshness, EvidenceFreshness.UNKNOWN)

    def test_flat_fresh_all_fields_and_ok(self):
        self.fresh()
        result = health(self.store)
        self.assertIs(result.overall_health, ObservabilityHealthLevel.OK)
        self.assertEqual(result.reason_codes, ())
        self.assertEqual((result.risk_equity, result.peak_risk_equity, result.risk_capital_quote), (D(1000), D(1000), D(1000)))
        self.assertEqual((result.base_currency, result.quote_currency), ("BTC", "USDT"))
        self.assertEqual(result.buy_quote_budget, self.config.buy_quote_budget)
        self.assertEqual((result.drawdown_numerator, result.drawdown_denominator), (D(0), D(1000)))
        self.assertEqual(result.to_dict()["risk_equity"], "1000")

    def test_long_exact_book_and_configuration_bound(self):
        self.long_activation(fee="-0.01", currency="BTC")
        result = health(self.store, at=2*HOUR)
        self.assertEqual(result.owned_base_quantity, D("1.01"))
        self.assertEqual(result.risk_equity, self.store.get_latest_risk_valuation().risk_equity)
        self.assertEqual(result.risk_configuration_digest, self.store.get_risk_configuration().risk_configuration_digest)

    def test_regeneration_does_not_refresh_old_evidence(self):
        self.fresh()
        first, later = health(self.store), health(self.store, at=HOUR+60001)
        self.assertIs(first.market_freshness, EvidenceFreshness.FRESH)
        self.assertIs(later.market_freshness, EvidenceFreshness.STALE)
        self.assertIs(later.reconciliation_freshness, EvidenceFreshness.STALE)
        self.assertEqual(first.valued_at_ms, later.valued_at_ms)
        self.assertIn(HealthReason.MARKET_STALE, later.reason_codes)

    def test_different_existing_market_and_broker_age_bounds(self):
        self.fresh()
        cfg = replace(self.config, decision_max_age_ms=30000, observation_max_age_ms=60000)
        with patch.object(self.store, "get_configuration", return_value=cfg):
            result = health(self.store, at=HOUR+30001)
        self.assertIs(result.market_freshness, EvidenceFreshness.STALE)
        self.assertIs(result.broker_freshness, EvidenceFreshness.FRESH)

    def test_future_evidence_is_unknown_not_fresh(self):
        self.fresh()
        result = health(self.store, at=HOUR-1)
        self.assertIs(result.market_freshness, EvidenceFreshness.UNKNOWN)
        self.assertIs(result.risk_freshness, EvidenceFreshness.UNKNOWN)
        self.assertIs(result.broker_freshness, EvidenceFreshness.UNKNOWN)

    def test_missing_reconciliation_not_ok(self):
        self.activate()
        result = health(self.store)
        self.assertIn(HealthReason.RECONCILIATION_UNKNOWN, result.reason_codes)
        self.assertIs(result.overall_health, ObservabilityHealthLevel.ATTENTION)

    def test_record_slotted_frozen_and_json_roundtrip(self):
        self.fresh()
        result = health(self.store)
        self.assertEqual(health_from_json(result.to_json()), result)
        self.assertFalse(hasattr(result, "__dict__"))
        with self.assertRaises(FrozenInstanceError):
            result.risk_active = False

    def test_generic_strategy_ids_roundtrip_active_health(self):
        self.fresh()
        original = health(self.store)
        for strategy in ("ema_trend", "donchian", "donchian_breakout", "mean_reversion", "momentum_v2", "a", "x"*32):
            with self.subTest(strategy=strategy):
                record = replace(original, strategy_id=strategy)
                encoded = h.canonical_bytes({**original.to_dict(), "strategy_id": strategy})
                parsed = health_from_json(encoded)
                self.assertEqual(parsed, record)
                self.assertEqual(parsed.strategy_id, strategy)
                self.assertEqual(parsed.to_json(), encoded)

    def test_unsafe_strategy_ids_rejected_by_health_record_and_parser(self):
        original = health(self.store)
        for strategy in ("", "EMA Trend", "EMA", "../ema", "ema/trend", " strategy ", "x"*33,
                         "x"*10000, "1strategy", "_strategy", "mean-reversion", "mean.reversion",
                         "ema_trend\n", "ema\x00trend", "\u0435ma_trend", "\uff45ma_trend", None, True, 1, 1.0, [], {}):
            with self.subTest(strategy=strategy):
                with self.assertRaises(ObservabilityValidationError):
                    replace(original, strategy_id=strategy)
                with self.assertRaises(ObservabilityValidationError):
                    health_from_json(h.canonical_bytes({**original.to_dict(), "strategy_id": strategy}))

    def test_generic_strategy_does_not_broaden_health_broker_or_timeframe(self):
        original = health(self.store)
        for field, value in (("broker_id", "bybit-live"), ("broker_id", "other-demo"),
                             ("timeframe", "5"), ("timeframe", "240")):
            changes = {"strategy_id": "donchian", field: value}
            with self.subTest(field=field, value=value):
                with self.assertRaises(ObservabilityValidationError):
                    replace(original, **changes)
                with self.assertRaises(ObservabilityValidationError):
                    health_from_json(h.canonical_bytes({**original.to_dict(), **changes}))

    def test_future_identity_uses_same_health_schema_without_future_runtime(self):
        # Only the read-model identity changes; no Donchian execution is implemented.
        current = health(self.store)
        encoded = h.canonical_bytes({**current.to_dict(), "strategy_id": "donchian",
                                     "symbol": "ETHUSDT", "bot_id": "bot2"})
        future = health_from_json(encoded)
        self.assertEqual((current.strategy_id, current.symbol, current.bot_id), ("ema_trend", "BTCUSDT", "bot1"))
        self.assertEqual((future.strategy_id, future.symbol, future.bot_id), ("donchian", "ETHUSDT", "bot2"))
        self.assertEqual(type(current), type(future))
        self.assertEqual(set(current.to_dict()), set(future.to_dict()))
        self.assertEqual((future.broker_id, future.timeframe), ("bybit-demo", "60"))
        self.assertEqual(future.to_json(), encoded)
        self.assertEqual(health(self.store).strategy_id, "ema_trend")

    def test_pre_correction_ema_health_serialization_vectors(self):
        # Captured from frozen 557774a: inactive then fresh active risk snapshot.
        self.assertEqual(hashlib.sha256(health(self.store).to_json()).hexdigest(),
                         "345a8bebadd0f26d3b9daa730afb8a420cf2ee35af1fee5cebb982343c246ceb")
        self.fresh()
        self.assertEqual(hashlib.sha256(health(self.store).to_json()).hexdigest(),
                         "83d1011f8a03e5b722793a3e1360a7fc396687c6b33f93eb998d4f40c5e37276")

    def test_complete_snapshot_rejects_missing_unknown_wrong_type(self):
        self.fresh()
        values = health(self.store).to_dict()
        for name, value in (("risk_equity", 1000.0), ("run_id", "x"), ("unknown", "synthetic-token"), ("risk_active", 1)):
            with self.subTest(name=name), self.assertRaises(ObservabilityValidationError):
                health_from_json(h.canonical_bytes({**values, name:value}))
        del values["risk_active"]
        with self.assertRaises(ObservabilityValidationError):
            health_from_json(h.canonical_bytes(values))

    def test_malformed_or_invented_ok_rejected(self):
        values = health(self.store).to_dict()
        values.update(overall_health="OK", reason_codes=[])
        with self.assertRaises(ObservabilityValidationError):
            health_from_json(h.canonical_bytes(values))
        for raw in (b"", b"{}", b"[]", b"null", b"{", b"\xff"):
            with self.subTest(raw=raw), self.assertRaises(ObservabilityValidationError):
                health_from_json(raw)

    def test_checkpoint_sequence_race(self):
        cp = self.store.get_checkpoint()
        with patch.object(self.store, "get_checkpoint", side_effect=[cp, replace(cp, sequence=1)]) as get:
            with self.assertRaises(ObservabilityProjectionError):
                health(self.store)
            self.assertEqual(get.call_count, 2)

    def test_equal_sequence_different_payload_race(self):
        cp = self.store.get_checkpoint()
        with patch.object(self.store, "get_checkpoint", side_effect=[cp, replace(cp, observed_at_ms=1)]):
            with self.assertRaises(ObservabilityProjectionError):
                health(self.store)

    def test_active_epoch_race_even_without_checkpoint_change(self):
        self.fresh()
        epoch = self.store.get_current_risk_epoch()
        with patch.object(self.store, "get_current_risk_epoch", side_effect=[epoch, epoch, epoch, None]):
            with self.assertRaises(ObservabilityProjectionError):
                health(self.store)

    def test_risk_valuation_race_without_checkpoint_change(self):
        self.fresh()
        row = self.store.get_latest_risk_valuation()
        with patch.object(self.store, "get_latest_risk_valuation", side_effect=[row, None]):
            with self.assertRaises(ObservabilityProjectionError):
                health(self.store)

    def test_snapshot_risk_configuration_digest_cannot_be_rebound(self):
        self.fresh()
        values = health(self.store).to_dict()
        values["risk_capital_quote"] = "9999"
        with self.assertRaises(ObservabilityValidationError):
            health_from_json(h.canonical_bytes(values))

    def test_pending_exact_action_phase_and_not_automatically_unhealthy(self):
        self.fresh()
        action = fixtures.prepared()
        cp = self.store.get_checkpoint()
        pending = replace(cp, snapshot=RuntimeStateSnapshot(S.ORDER_PENDING, D(0), P.CONFIRMED, 1,
            PendingAction(action.logical_action_id, PendingActionKind.ENTRY)))
        with patch.object(self.store, "get_checkpoint", return_value=pending), patch.object(self.store, "get_action", return_value=action):
            result = health(self.store)
        self.assertEqual((result.pending_action_id, result.pending_action_phase), (action.logical_action_id, ActionPhase.PREPARED))
        self.assertIs(result.overall_health, ObservabilityHealthLevel.OK)

    def test_pending_missing_or_terminal_action_is_error(self):
        self.prepare()
        for value in (None, fixtures.terminal(replace(fixtures.prepared(), phase=ActionPhase.ATTEMPT_STARTED, attempt_count=1))):
            with patch.object(self.store, "get_action", return_value=value):
                with self.assertRaises(ObservabilityProjectionError):
                    health(self.store)

    def test_pending_deadline_attention_uses_retained_boundary(self):
        self.prepare()
        result = health(self.store, at=HOUR+600000)
        self.assertIn(HealthReason.PENDING_OVERDUE, result.reason_codes)

    def test_process_status_degraded_and_fatal_precedence(self):
        self.fresh()
        degraded = health(self.store, observability_status="DEGRADED")
        fatal = health(self.store, observability_status="CRITICAL")
        self.assertIs(degraded.overall_health, ObservabilityHealthLevel.ATTENTION)
        self.assertIn(HealthReason.OBSERVABILITY_DEGRADED, degraded.reason_codes)
        self.assertIs(fatal.overall_health, ObservabilityHealthLevel.CRITICAL)
        self.assertIn(HealthReason.FATAL_STATUS, fatal.reason_codes)

    def test_cycle_telemetry_does_not_relabel_observed_fill(self):
        self.fresh()
        result = SingleCycleResult(self.store.get_checkpoint(), CycleOutcome.OBSERVED)
        snapshot = health(self.store, last_cycle_result=result, last_cycle_activity_ms=HOUR+1,
                          last_scheduler_activity_ms=HOUR+2)
        self.assertEqual(snapshot.last_cycle_outcome, "OBSERVED")
        self.assertEqual(snapshot.last_cycle_activity_ms, HOUR+1)

    def test_all_runtime_states_preserve_raw_state_and_precedence(self):
        self.fresh()
        base = self.store.get_checkpoint()
        for state in S:
            operational = state in (S.FLAT, S.LONG, S.ORDER_PENDING)
            quantity = D(1) if state is S.LONG else D(0) if operational else None
            evidence = P.CONFIRMED if operational else P.UNKNOWN
            reason = R.EVIDENCE_MISSING if state in (S.HALTED, S.UNCERTAIN) else None
            pending = PendingAction(fixtures.ACTION_ID, PendingActionKind.ENTRY) if state is S.ORDER_PENDING else None
            if state is S.STOPPING:
                quantity, evidence = D(0), P.LAST_KNOWN
            snap = RuntimeStateSnapshot(state, quantity, evidence, 0, pending, reason,
                                        S.FLAT if state is S.STOPPING else None)
            cp = replace(base, snapshot=snap, halted_at_ms=HOUR if state is S.HALTED else None,
                         shutdown_at_ms=HOUR if state is S.STOPPING else None)
            with self.subTest(state=state), patch.object(self.store, "get_checkpoint", return_value=cp), \
                    patch.object(self.store, "get_action", return_value=fixtures.prepared()):
                result = health(self.store)
                self.assertIs(result.runtime_state, state)
                expected = (ObservabilityHealthLevel.CRITICAL if state in (S.HALTED, S.UNCERTAIN) else
                            ObservabilityHealthLevel.ATTENTION if state in (S.STARTING, S.SYNCHRONIZING, S.STOPPING) else
                            ObservabilityHealthLevel.OK)
                self.assertIs(result.overall_health, expected)

    def test_no_health_trading_write_and_no_open_transaction(self):
        self.fresh()
        before = self.risk_rows(), self.store.get_checkpoint()
        health(self.store)
        self.assertEqual(before, (self.risk_rows(), self.store.get_checkpoint()))
        self.assertFalse(self.store._connection.in_transaction)

    def test_stopping_retains_critical_uncertainty(self):
        self.fresh()
        cp = self.store.get_checkpoint()
        stopped = replace(cp, snapshot=RuntimeStateSnapshot(S.STOPPING, D(0), P.LAST_KNOWN, 0,
            reason=R.ACTION_OUTCOME_UNKNOWN, stopped_from=S.UNCERTAIN), shutdown_at_ms=HOUR)
        with patch.object(self.store, "get_checkpoint", return_value=stopped):
            result = health(self.store)
        self.assertIs(result.overall_health, ObservabilityHealthLevel.CRITICAL)
        self.assertIn(HealthReason.RUNTIME_UNCERTAIN, result.reason_codes)


class TrippedHealthTests(rearm_fixtures.LocalRearmCase):
    def test_trip_independent_halt_precedence_and_exact_count(self):
        row = self.tripped_long()
        snapshot = health(self.store, at=self.now_ms)
        self.assertEqual(snapshot.risk_trip_reason, row.trip_reason)
        self.assertEqual(snapshot.entries_this_utc_day, row.entries_this_utc_day)
        self.assertIn(HealthReason.RISK_TRIPPED, snapshot.reason_codes)
        self.assertIs(snapshot.overall_health, ObservabilityHealthLevel.ATTENTION)
        self.halt()
        halted = health(self.store, at=self.now_ms)
        self.assertIs(halted.overall_health, ObservabilityHealthLevel.CRITICAL)
        self.assertIn(HealthReason.RISK_TRIPPED, halted.reason_codes)

    def test_child_epoch_exact_config_and_same_day_count(self):
        row = self.tripped_long()
        self.rearm()
        snapshot = health(self.store, at=self.now_ms)
        self.assertEqual(snapshot.risk_epoch_sequence, 2)
        self.assertIsNone(snapshot.risk_trip_reason)
        self.assertEqual(snapshot.entries_this_utc_day, row.entries_this_utc_day)
        self.assertEqual(snapshot.risk_epoch_id, self.store.get_current_risk_epoch().epoch_id)
