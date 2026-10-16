"""Offline durable primitives, real temporary SQLite files and rollback faults."""

import ast
from dataclasses import FrozenInstanceError, fields, replace
from decimal import Decimal, localcontext
import hashlib
import inspect
import json
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from trading_lab.runtime.locking import RuntimeAccountLock, RuntimeLockError
from trading_lab.runtime.state import (
    PendingAction, PendingActionKind, PositionEvidence, RuntimeReason,
    RuntimeState, RuntimeStateSnapshot, RuntimeEvidence, RuntimeEvent,
    RuntimeEventType, RuntimeStateError, transition_runtime_state,
)
from trading_lab.runtime.store import (
    ActionPhase, ActionRecord, CandleRecord, DecisionDisposition, DecisionRecord,
    JournalActionKind, OwnedFillRecord, RuntimeCheckpoint, RuntimeConfiguration,
    RuntimeStore, RuntimeStoreConflictError, RuntimeStoreError,
    RuntimeStoreIntegrityError, deserialize_decimal, serialize_decimal,
)
import trading_lab.runtime.store as module


D = Decimal
HOUR = 3_600_000
ACTION_ID = "c" * 64


def configuration():
    return RuntimeConfiguration(
        "bybit-demo", "research", "bot1", "ema_trend", "a" * 64,
        (("fast_span", 20), ("slow_span", 50), ("warmup_candles", 50)),
        "BTCUSDT", "BTC", "USDT", "60", HOUR, "b" * 64, D("10.123456789"),
        0, 60000, 60000, 600000, 5, 3, 10000, 1000,
    )


def candle(time=0):
    return CandleRecord("BTCUSDT", "60", time, "d" * 64, D("100"), D("110"), D("90"), D("105.25"), D("1.23456789"))


def decision(time=0, *, action=False):
    return DecisionRecord("BTCUSDT", "60", time, "d" * 64,
                          "LONG_ENTRY" if action else "HOLD", int(action),
                          DecisionDisposition.ACTION if action else DecisionDisposition.BOOTSTRAP,
                          time + HOUR, ACTION_ID if action else None)


def prepared():
    return ActionRecord(ACTION_ID, JournalActionKind.ENTRY, "BTCUSDT", HOUR + 600000, 5, 3,
                        "bot1-" + ACTION_ID[:23], 0, side="BUY", amount_unit="QUOTE",
                        currency="USDT", authorized_amount=D("10.123456789"))


def receipt(action):
    return replace(action, phase=ActionPhase.ACKNOWLEDGED, broker_order_id="order-1",
                   submitted_amount=D("10.1234567"), acknowledgement_broker_ms=HOUR + 1,
                   acknowledgement_observed_ms=HOUR + 2)


def terminal(action):
    return replace(action, phase=ActionPhase.TERMINAL_CONFIRMED, broker_order_id="order-1",
                   order_status="FILLED", external_status="Filled", observed_at_ms=HOUR + 4,
                   terminal_at_ms=HOUR + 4)


def fill(execution_id="fill-1"):
    return OwnedFillRecord("bybit-demo", "research", execution_id, ACTION_ID, "order-1",
                           "bot1-" + ACTION_ID[:23], "BTCUSDT", "BUY", D("0.123456789"),
                           D("100.123456789"), D("-0.0000123456789"), "BTC", HOUR + 1, HOUR + 3)


class StoreCase(unittest.TestCase):
    def setUp(self):
        self.directory = self.enterContext(TemporaryDirectory())
        self.lock = self.enterContext(RuntimeAccountLock(Path(self.directory), "research"))
        self.config = configuration()
        self.store = RuntimeStore.open(self.lock, self.config, initialize=True)
        self.addCleanup(self.store.close)

    def next_checkpoint(self, **changes):
        current = self.store.get_checkpoint()
        return replace(current, sequence=current.sequence + 1, **changes)

    def flat(self):
        current = self.store.get_checkpoint()
        self.store.save_checkpoint(replace(current, sequence=current.sequence + 1, snapshot=RuntimeStateSnapshot(
            RuntimeState.FLAT, D("0"), PositionEvidence.CONFIRMED, 0,
        )), expected_sequence=current.sequence)

    def prepare(self):
        self.flat()
        current = self.store.get_checkpoint()
        cp = self.next_checkpoint(last_processed_candle_ms=0, snapshot=RuntimeStateSnapshot(
            RuntimeState.ORDER_PENDING, D("0"), PositionEvidence.CONFIRMED, 1,
            PendingAction(ACTION_ID, PendingActionKind.ENTRY),
        ))
        self.store.commit_decision(candle(), decision(action=True), cp, expected_sequence=current.sequence, action=prepared())
        return self.store.get_action(ACTION_ID)

    def attempt(self):
        self.prepare()
        current = self.store.get_checkpoint()
        self.store.start_attempt(ACTION_ID, self.next_checkpoint(), expected_sequence=current.sequence)
        return self.store.get_action(ACTION_ID)

    def acknowledge(self):
        action = receipt(self.attempt())
        current = self.store.get_checkpoint()
        self.store.record_observation(action, self.next_checkpoint(), expected_sequence=current.sequence)
        return action

    def settle(self, action, *fills):
        current = self.store.get_checkpoint()
        cp = self.next_checkpoint(snapshot=RuntimeStateSnapshot(RuntimeState.LONG, D("0.1234691346789"), PositionEvidence.CONFIRMED, 1))
        self.store.record_observation(terminal(action), cp, expected_sequence=current.sequence, fills=tuple(fills))
        return cp

    def reopen(self, config=None):
        self.store.close()
        self.store = RuntimeStore.open(self.lock, config or self.config)
        self.addCleanup(self.store.close)

    def corrupt(self, sql, args=(), *, ignore_checks=False):
        self.store.close()
        with sqlite3.connect(self.lock.database_path) as connection:
            if ignore_checks:
                connection.execute("PRAGMA ignore_check_constraints=ON")
            connection.execute(sql, args)

    def reject_reopen(self):
        with self.assertRaises(RuntimeStoreError):
            RuntimeStore.open(self.lock, self.config)


class DecimalTests(unittest.TestCase):
    def test_canonical_values_and_exact_roundtrip(self):
        cases = {D("0"): "0", D("1.2300"): "1.23", D("1E+3"): "1000", D("-0.0000012300"): "-0.00000123"}
        for value, text in cases.items():
            with self.subTest(value=value):
                self.assertEqual(serialize_decimal(value), text)
                self.assertEqual(deserialize_decimal(text), value)

    def test_signed_zero_is_canonical_zero(self):
        self.assertEqual(serialize_decimal(D("-0.000")), "0")

    def test_low_context_does_not_round_exact_money(self):
        exact = D("1234567890123456789.1234567890123456789")
        with localcontext() as context:
            context.prec = 2
            self.assertEqual(deserialize_decimal(serialize_decimal(exact)), exact)

    def test_tiny_positive_decimal_does_not_become_zero(self):
        tiny = D("1e-1000")
        self.assertEqual(deserialize_decimal(serialize_decimal(tiny)), tiny)
        self.assertGreater(tiny, 0)

    def test_serialization_rejects_non_decimal_and_nonfinite(self):
        for value in (1, 1.2, True, "1", None, D("NaN"), D("sNaN"), D("Infinity")):
            with self.subTest(kind=type(value).__name__), self.assertRaises(RuntimeStoreError):
                serialize_decimal(value)

    def test_deserialization_rejects_malformed_and_noncanonical(self):
        for value in (1, None, "", "NaN", "Inf", "1e-4", "+1", "01", "1.", ".1", "1.0", "-0", " 1", "1 ", "0.00", "0x12"):
            with self.subTest(value=value), self.assertRaises(RuntimeStoreIntegrityError):
                deserialize_decimal(value)

    def test_oversized_exact_decimal_fails_before_large_formatting(self):
        with self.assertRaises(RuntimeStoreError):
            serialize_decimal(D("1e-99999999"))


class RecordTests(unittest.TestCase):
    def test_all_records_are_immutable_and_slotted(self):
        for record in (configuration(), RuntimeCheckpoint(0, RuntimeStateSnapshot()), candle(), decision(), prepared(), fill()):
            with self.subTest(record=type(record).__name__):
                self.assertFalse(hasattr(record, "__dict__"))
                with self.assertRaises(FrozenInstanceError):
                    setattr(record, fields(record)[0].name, None)

    def test_phase_enum_exact_separate_from_operational_state(self):
        self.assertEqual([value.value for value in ActionPhase], ["PREPARED", "ATTEMPT_STARTED", "ACKNOWLEDGED", "UNKNOWN_OUTCOME", "TERMINAL_CONFIRMED", "REJECTED", "ABANDONED_UNSENT"])
        self.assertIsNot(ActionPhase, RuntimeState)

    def test_config_disallows_raw_parameters_or_secret_fields(self):
        for parameters in ({"api_key": "private"}, (("api_key", "private"),), (("fast_span", True), ("slow_span", 50), ("warmup_candles", 50))):
            with self.subTest(parameters=parameters), self.assertRaises(RuntimeStoreError):
                replace(configuration(), strategy_parameters=parameters)
        with self.assertRaises(TypeError):
            RuntimeConfiguration(**{field.name: getattr(configuration(), field.name) for field in fields(configuration())}, api_key="private")

    def test_config_rejects_unsupported_runtime_bindings(self):
        for name, value in (("broker_id", "live"), ("bot_id", "CAPS"), ("symbol", "btcusdt"), ("timeframe", "15"), ("interval_ms", True), ("schema_version", 0), ("runtime_contract_version", 2), ("read_attempt_limit", 4), ("buy_quote_budget", D("0")), ("history_anchor_ms", 1)):
            with self.subTest(field=name), self.assertRaises(RuntimeStoreError):
                replace(configuration(), **{name: value})

    def test_integer_times_reject_naive_aware_datetime_float_bool(self):
        from datetime import datetime, timezone
        for value in (datetime(2026, 1, 1), datetime(2026, 1, 1, tzinfo=timezone.utc), 1.5, True, -1, 2**63):
            with self.subTest(value=value), self.assertRaises(RuntimeStoreError):
                replace(fill(), observed_at_ms=value)

    def test_checkpoint_requires_halt_shutdown_and_coverage_consistency(self):
        for kwargs in ({"coverage_start_ms": 0}, {"coverage_start_ms": 2, "coverage_end_ms": 1}, {"halted_at_ms": 1}, {"shutdown_at_ms": 1}):
            with self.subTest(kwargs=kwargs), self.assertRaises(RuntimeStoreError):
                RuntimeCheckpoint(0, RuntimeStateSnapshot(), **kwargs)

    def test_action_attempt_semantics_reject_invalid_counts(self):
        for phase, count in ((ActionPhase.PREPARED, 1), (ActionPhase.ATTEMPT_STARTED, 0), (ActionPhase.ATTEMPT_STARTED, 2), (ActionPhase.PREPARED, True)):
            with self.subTest(phase=phase, count=count), self.assertRaises(RuntimeStoreError):
                replace(prepared(), phase=phase, attempt_count=count)

    def test_action_rejects_fake_receipt_terminal_or_unknown(self):
        for kwargs in ({"phase": ActionPhase.ACKNOWLEDGED, "attempt_count": 1}, {"phase": ActionPhase.UNKNOWN_OUTCOME, "attempt_count": 1}, {"phase": ActionPhase.TERMINAL_CONFIRMED, "attempt_count": 1, "terminal_at_ms": 1}, {"broker_order_id": "order-1"}, {"phase": "PREPARED"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(RuntimeStoreError):
                replace(prepared(), **kwargs)
        for code in (0, True, 2**63, -(2**63)-1):
            with self.subTest(code=code), self.assertRaises(RuntimeStoreError):
                replace(prepared(), phase=ActionPhase.REJECTED, attempt_count=1, terminal_at_ms=1, rejection_code=code)

    def test_receipt_cannot_increase_authorized_amount(self):
        with self.assertRaises(RuntimeStoreError):
            replace(receipt(replace(prepared(), phase=ActionPhase.ATTEMPT_STARTED, attempt_count=1)), submitted_amount=D("999"))

    def test_fills_keep_signed_fees_and_unavailable_currency(self):
        self.assertLess(fill().execution_fee, 0)
        self.assertIsNone(replace(fill(), fee_currency=None).fee_currency)


class StoreSchemaTests(StoreCase):
    def test_initial_checkpoint_is_unknown_not_flat(self):
        cp = self.store.get_checkpoint()
        self.assertEqual(cp, RuntimeCheckpoint(0, RuntimeStateSnapshot()))
        self.assertIsNone(cp.snapshot.owned_base_quantity)

    def test_effective_pragmas(self):
        settings = self.store.durability_settings()
        self.assertEqual((settings["journal_mode"], settings["synchronous"], settings["foreign_keys"]), ("delete", 3, 1))
        if sys.platform == "darwin":
            self.assertEqual(settings["fullfsync"], 1)

    def test_durability_drift_blocks_reads_and_writes(self):
        for pragma in ("synchronous=OFF", "foreign_keys=OFF", "journal_mode=WAL"):
            with self.subTest(pragma=pragma):
                self.store._connection.execute("PRAGMA " + pragma)
                with self.assertRaises(RuntimeStoreIntegrityError):
                    self.store.get_checkpoint()
                with self.assertRaises(RuntimeStoreIntegrityError):
                    self.store.save_checkpoint(self.next_checkpoint(), expected_sequence=0)
                self.store._configure()

    def test_mac_fullfsync_drift_fails_closed(self):
        self.store._connection.execute("PRAGMA fullfsync=OFF")
        with patch.object(module.sys, "platform", "darwin"), self.assertRaises(RuntimeStoreIntegrityError):
            self.store.get_checkpoint()
        self.store._configure()

    def test_fresh_initialization_is_explicit(self):
        self.store.close()
        other = self.enterContext(RuntimeAccountLock(Path(self.directory), "other"))
        with self.assertRaises(RuntimeStoreIntegrityError):
            RuntimeStore.open(other, replace(self.config, account_binding="other"))
        self.assertFalse(other.database_path.exists())

    def test_existing_file_cannot_be_reinitialized(self):
        before = self.lock.database_path.read_bytes()
        with self.assertRaises(RuntimeStoreIntegrityError):
            RuntimeStore.open(self.lock, self.config, initialize=True)
        self.assertEqual(self.lock.database_path.read_bytes(), before)

    def test_reopen_preserves_binding_and_missing_values(self):
        self.reopen()
        self.assertEqual(self.store.get_configuration(), self.config)
        self.assertEqual(self.store.get_checkpoint().sequence, 0)
        self.assertIsNone(self.store.get_checkpoint().last_reconciled_at_ms)

    def test_bot_identity_mismatch_cannot_reuse_database(self):
        self.store.close()
        with self.assertRaises(RuntimeStoreError):
            RuntimeStore.open(self.lock, replace(self.config, bot_id="bot2"))

    def test_account_lock_binding_mismatch(self):
        with self.assertRaises(RuntimeStoreConflictError):
            RuntimeStore.open(self.lock, replace(self.config, account_binding="other"))

    def test_config_mismatch_cannot_reuse_database(self):
        for name, value in (("buy_quote_budget", D("11")), ("configuration_digest", "f" * 64), ("history_anchor_ms", HOUR), ("request_timeout_ms", 20000), ("strategy_implementation_digest", "f" * 64)):
            with self.subTest(field=name), self.assertRaises(RuntimeStoreError):
                RuntimeStore.open(self.lock, replace(self.config, **{name: value}))

    def test_unknown_schema_fails_without_reset(self):
        self.corrupt("PRAGMA user_version=3")
        before = self.lock.database_path.read_bytes()
        self.reject_reopen()
        self.assertEqual(self.lock.database_path.read_bytes(), before)

    def test_missing_table_fails_without_recreation(self):
        self.corrupt("DROP TABLE fills")
        self.reject_reopen()
        with sqlite3.connect(self.lock.database_path) as connection:
            self.assertIsNone(connection.execute("SELECT name FROM sqlite_master WHERE name='fills'").fetchone())

    def test_missing_unique_index_fails(self):
        self.corrupt("DROP INDEX one_pending_placement")
        self.reject_reopen()

    def test_old_schema_version_is_not_migrated(self):
        self.corrupt("PRAGMA user_version=0")
        self.reject_reopen()

    def test_unknown_stored_decision_enum_fails(self):
        self.prepare()
        self.corrupt("UPDATE decisions SET disposition='FUTURE_DISPOSITION'")
        self.reject_reopen()

    def test_unknown_stored_position_evidence_fails(self):
        self.corrupt("UPDATE checkpoint SET position_evidence='FUTURE_EVIDENCE'")
        self.reject_reopen()

    def test_negative_stored_budget_fails(self):
        self.corrupt("UPDATE identity SET buy_quote_budget='-1'")
        self.reject_reopen()

    def test_inconsistent_known_pending_identity_fails(self):
        self.prepare()
        self.corrupt("UPDATE checkpoint SET pending_action_kind='EXIT'")
        self.reject_reopen()

    def test_corrupt_file_fails_without_reset(self):
        self.store.close()
        self.lock.database_path.write_bytes(b"synthetic-private-not-a-database")
        with self.assertRaises(RuntimeStoreIntegrityError) as caught:
            RuntimeStore.open(self.lock, self.config)
        self.assertNotIn("synthetic-private", str(caught.exception))
        self.assertEqual(self.lock.database_path.read_bytes(), b"synthetic-private-not-a-database")

    def test_unknown_stored_runtime_enum_fails(self):
        self.corrupt("UPDATE checkpoint SET state='FUTURE_STATE'")
        self.reject_reopen()

    def test_malformed_stored_decimal_fails(self):
        self.corrupt("UPDATE identity SET buy_quote_budget='NaN'")
        self.reject_reopen()

    def test_noncanonical_stored_decimal_fails(self):
        self.corrupt("UPDATE identity SET buy_quote_budget='10.1234567890'")
        self.reject_reopen()

    def test_invalid_stored_quantity_evidence_fails(self):
        self.corrupt("UPDATE checkpoint SET owned_base_quantity='0'")
        self.reject_reopen()

    def test_missing_identity_row_fails(self):
        self.corrupt("DELETE FROM identity")
        self.reject_reopen()

    def test_unknown_action_kind_fails(self):
        self.prepare()
        self.corrupt("UPDATE actions SET kind='FUTURE_ACTION'", ignore_checks=True)
        self.reject_reopen()

    def test_unknown_action_phase_fails(self):
        self.prepare()
        self.corrupt("UPDATE actions SET phase='FUTURE_PHASE'", ignore_checks=True)
        self.reject_reopen()

    def test_broken_foreign_key_fails(self):
        self.prepare()
        self.corrupt("UPDATE checkpoint SET pending_action_id=?", ("e" * 64,))
        self.reject_reopen()

    def test_frontier_tampering_fails(self):
        self.flat()
        self.corrupt("UPDATE checkpoint SET last_processed_candle_ms=0")
        self.reject_reopen()

    def test_all_financial_columns_are_sqlite_text(self):
        self.settle(self.acknowledge(), fill())
        for table, names in module._DECIMALS.items():
            declared = {row[1]: row[2] for row in self.store._connection.execute("PRAGMA table_info(" + table + ")")}
            for name in names:
                self.assertEqual(declared[name], "TEXT", (table, name))
                for row in self.store._connection.execute("SELECT typeof(" + name + ") FROM " + table + " WHERE " + name + " IS NOT NULL"):
                    self.assertEqual(row[0], "text")

    def test_database_is_private_and_account_scoped(self):
        self.assertEqual(self.lock.database_path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.lock.database_path.name, "runtime.sqlite3")
        self.assertEqual(self.lock.database_path.parent.name, self.lock.account_key)

    def test_safe_failure_does_not_dump_sql_values(self):
        private = "synthetic-private-diagnostic"
        with patch.object(self.store, "_commit", side_effect=sqlite3.OperationalError(private)), self.assertRaises(RuntimeStoreError) as caught:
            self.store.save_checkpoint(self.next_checkpoint(), expected_sequence=0)
        self.assertNotIn(private, str(caught.exception))
        self.assertTrue(caught.exception.__suppress_context__)


class DecisionCheckpointTests(StoreCase):
    def test_bootstrap_decision_and_frontier_roundtrip(self):
        cp = self.next_checkpoint(last_processed_candle_ms=0, snapshot=replace(RuntimeStateSnapshot(), desired_position=0), bootstrap_until_ms=0)
        self.assertTrue(self.store.commit_decision(candle(), decision(), cp, expected_sequence=0))
        self.reopen()
        self.assertEqual(self.store.get_candle(0), candle())
        self.assertEqual(self.store.get_decision(0), decision())
        self.assertEqual(self.store.get_checkpoint(), cp)

    def test_identical_replay_does_not_advance_checkpoint(self):
        cp = self.next_checkpoint(last_processed_candle_ms=0, snapshot=replace(RuntimeStateSnapshot(), desired_position=0))
        self.store.commit_decision(candle(), decision(), cp, expected_sequence=0)
        self.assertFalse(self.store.commit_decision(candle(), decision(), cp, expected_sequence=0))
        self.assertEqual(self.store.get_checkpoint(), cp)

    def test_conflicting_fingerprint_rolls_back(self):
        self.prepare()
        before = self.store.get_checkpoint()
        with self.assertRaises(RuntimeStoreConflictError):
            self.store.commit_decision(replace(candle(), input_fingerprint="e"*64), replace(decision(action=True), input_fingerprint="e"*64), before, expected_sequence=1, action=prepared())
        self.assertEqual(self.store.get_checkpoint(), before)

    def test_conflicting_signal_intent_disposition_or_reference_fails(self):
        self.prepare()
        original = decision(action=True)
        variants = [replace(original, signal="HOLD"), replace(original, signal="LONG_EXIT", desired_position=0), replace(original, disposition=DecisionDisposition.WAIT, action_id=None), replace(original, action_id="e"*64)]
        for changed in variants:
            with self.subTest(changed=changed), self.assertRaises(RuntimeStoreConflictError):
                self.store.commit_decision(candle(), changed, self.store.get_checkpoint(), expected_sequence=1)

    def test_same_fingerprint_changed_candle_values_conflicts(self):
        self.prepare()
        with self.assertRaises(RuntimeStoreConflictError):
            self.store.commit_decision(replace(candle(), close=D("106")), decision(action=True), self.store.get_checkpoint(), expected_sequence=1)

    def test_missing_hour_is_not_skipped(self):
        cp = self.next_checkpoint(last_processed_candle_ms=HOUR, snapshot=replace(RuntimeStateSnapshot(), desired_position=0))
        with self.assertRaises(RuntimeStoreConflictError):
            self.store.commit_decision(candle(HOUR), decision(HOUR), cp, expected_sequence=0)
        self.assertIsNone(self.store.get_decision(HOUR))

    def test_consecutive_decisions_advance_frontier(self):
        for time in (0, HOUR, 2*HOUR):
            previous = self.store.get_checkpoint()
            self.store.commit_decision(candle(time), decision(time), self.next_checkpoint(last_processed_candle_ms=time, snapshot=replace(RuntimeStateSnapshot(), desired_position=0)), expected_sequence=previous.sequence)
        self.assertEqual(self.store.get_checkpoint().last_processed_candle_ms, 2*HOUR)

    def test_frontier_cannot_advance_without_a_decision(self):
        with self.assertRaises(RuntimeStoreIntegrityError):
            self.store.save_checkpoint(self.next_checkpoint(last_processed_candle_ms=0), expected_sequence=0)
        self.assertIsNone(self.store.get_checkpoint().last_processed_candle_ms)

    def test_stale_checkpoint_cannot_overwrite_newer(self):
        self.store.save_checkpoint(self.next_checkpoint(), expected_sequence=0)
        with self.assertRaises(RuntimeStoreConflictError):
            self.store.save_checkpoint(RuntimeCheckpoint(1, RuntimeStateSnapshot()), expected_sequence=0)
        self.assertEqual(self.store.get_checkpoint().sequence, 1)

    def test_sequence_must_advance_exactly_once(self):
        for sequence in (0, 2):
            with self.subTest(sequence=sequence), self.assertRaises(RuntimeStoreConflictError):
                self.store.save_checkpoint(RuntimeCheckpoint(sequence, RuntimeStateSnapshot()), expected_sequence=0)

    def test_last_observation_cannot_regress_or_disappear(self):
        self.store.save_checkpoint(self.next_checkpoint(observed_at_ms=10), expected_sequence=0)
        for time in (9, None):
            with self.subTest(time=time), self.assertRaises(RuntimeStoreConflictError):
                self.store.save_checkpoint(self.next_checkpoint(observed_at_ms=time), expected_sequence=1)

    def test_replay_cutoffs_and_coverage_roundtrip(self):
        cp = self.next_checkpoint(bootstrap_until_ms=HOUR, replay_until_ms=2*HOUR, observed_at_ms=5, coverage_start_ms=0, coverage_end_ms=5)
        self.store.save_checkpoint(cp, expected_sequence=0)
        self.reopen()
        self.assertEqual(self.store.get_checkpoint(), cp)

    def test_input_records_are_not_mutated(self):
        before = (candle(), decision(), RuntimeCheckpoint(1, replace(RuntimeStateSnapshot(), desired_position=0), last_processed_candle_ms=0))
        self.store.commit_decision(*before, expected_sequence=0)
        self.assertEqual(before, (candle(), decision(), before[2]))

    def test_halt_rearm_must_be_explicit_and_synchronized(self):
        halt = RuntimeStateSnapshot(RuntimeState.HALTED, reason=RuntimeReason.INVALID_CONFIGURATION)
        self.store.save_checkpoint(self.next_checkpoint(snapshot=halt, halted_at_ms=10), expected_sequence=0)
        with self.assertRaises(RuntimeStoreConflictError):
            self.store.save_checkpoint(self.next_checkpoint(snapshot=RuntimeStateSnapshot(RuntimeState.SYNCHRONIZING), halted_at_ms=None), expected_sequence=1)
        repaired = self.next_checkpoint(snapshot=RuntimeStateSnapshot(RuntimeState.SYNCHRONIZING), halted_at_ms=None, rearmed_at_ms=11)
        self.store.save_checkpoint(repaired, expected_sequence=1)
        self.assertEqual(self.store.get_checkpoint(), repaired)

    def test_shutdown_marker_cannot_bypass_halt_latch(self):
        halt = RuntimeStateSnapshot(RuntimeState.HALTED, reason=RuntimeReason.INVALID_CONFIGURATION)
        self.store.save_checkpoint(self.next_checkpoint(snapshot=halt, halted_at_ms=10), expected_sequence=0)
        stopped = replace(halt, state=RuntimeState.STOPPING, stopped_from=RuntimeState.HALTED)
        self.store.save_checkpoint(self.next_checkpoint(snapshot=stopped, shutdown_at_ms=11), expected_sequence=1)
        before = self.store.get_checkpoint()
        for changes in (
            {"snapshot": replace(stopped, stopped_from=RuntimeState.SYNCHRONIZING, reason=None), "halted_at_ms": None},
            {"halted_at_ms": 12},
        ):
            with self.subTest(changes=changes), self.assertRaises(RuntimeStoreConflictError):
                self.store.save_checkpoint(self.next_checkpoint(**changes), expected_sequence=2)
        with self.assertRaises(RuntimeStoreConflictError):
            self.store.save_checkpoint(self.next_checkpoint(snapshot=RuntimeStateSnapshot(RuntimeState.SYNCHRONIZING), halted_at_ms=None, shutdown_at_ms=None), expected_sequence=2)
        self.assertEqual(self.store.get_checkpoint(), before)
        repaired = self.next_checkpoint(snapshot=RuntimeStateSnapshot(RuntimeState.SYNCHRONIZING), halted_at_ms=None, shutdown_at_ms=None, rearmed_at_ms=12)
        self.store.save_checkpoint(repaired, expected_sequence=2)
        self.assertEqual(self.store.get_checkpoint(), repaired)


class ActionTransactionTests(StoreCase):
    def test_prepared_intent_decision_and_pending_checkpoint_persist_together(self):
        self.prepare()
        self.reopen()
        self.assertEqual(self.store.get_action(ACTION_ID), prepared())
        self.assertEqual(self.store.get_action(ACTION_ID).attempt_count, 0)
        self.assertEqual(self.store.get_checkpoint().snapshot.pending_action.logical_action_id, ACTION_ID)

    def test_prepared_failure_after_action_insert_rolls_back_every_write(self):
        self.flat()
        before = self.store.get_checkpoint()
        cp = replace(before, sequence=before.sequence + 1, last_processed_candle_ms=0, snapshot=RuntimeStateSnapshot(RuntimeState.ORDER_PENDING, D("0"), PositionEvidence.CONFIRMED, 1, PendingAction(ACTION_ID, PendingActionKind.ENTRY)))
        with patch.object(self.store, "_save_checkpoint", side_effect=RuntimeStoreError("Injected checkpoint fault")), self.assertRaises(RuntimeStoreError):
            self.store.commit_decision(candle(), decision(action=True), cp, expected_sequence=before.sequence, action=prepared())
        self.assertIsNone(self.store.get_action(ACTION_ID))
        self.assertIsNone(self.store.get_decision(0))
        self.assertIsNone(self.store.get_candle(0))
        self.assertEqual(self.store.get_checkpoint(), before)

    def test_prepared_commit_failure_rolls_back(self):
        self.flat()
        before = self.store.get_checkpoint()
        cp = replace(before, sequence=2, last_processed_candle_ms=0, snapshot=RuntimeStateSnapshot(RuntimeState.ORDER_PENDING, D("0"), PositionEvidence.CONFIRMED, 1, PendingAction(ACTION_ID, PendingActionKind.ENTRY)))
        with patch.object(self.store, "_commit", side_effect=sqlite3.OperationalError("Injected disk failure")), self.assertRaises(RuntimeStoreError):
            self.store.commit_decision(candle(), decision(action=True), cp, expected_sequence=1, action=prepared())
        self.assertIsNone(self.store.get_action(ACTION_ID))
        self.assertEqual(self.store.get_checkpoint(), before)

    def test_attempt_started_is_durable_one_attempt(self):
        self.attempt()
        self.reopen()
        action = self.store.get_action(ACTION_ID)
        self.assertEqual((action.phase, action.attempt_count), (ActionPhase.ATTEMPT_STARTED, 1))

    def test_attempt_commit_failure_remains_prepared(self):
        self.prepare()
        before = self.store.get_checkpoint()
        with patch.object(self.store, "_commit", side_effect=sqlite3.OperationalError("Injected commit fault")), self.assertRaises(RuntimeStoreError):
            self.store.start_attempt(ACTION_ID, self.next_checkpoint(), expected_sequence=before.sequence)
        self.assertEqual(self.store.get_action(ACTION_ID), prepared())
        self.assertEqual(self.store.get_checkpoint(), before)
        self.reopen()
        self.assertIs(self.store.get_action(ACTION_ID).phase, ActionPhase.PREPARED)

    def test_indeterminate_attempt_commit_closes_store_and_retains_marker(self):
        self.prepare()
        before = self.store.get_checkpoint()
        real_commit = self.store._commit

        def commit_then_report_error():
            real_commit()
            raise sqlite3.OperationalError("Injected failure after commit")

        with patch.object(self.store, "_commit", side_effect=commit_then_report_error), self.assertRaisesRegex(RuntimeStoreError, "reopening"):
            self.store.start_attempt(ACTION_ID, self.next_checkpoint(), expected_sequence=before.sequence)
        with self.assertRaises(RuntimeStoreError):
            self.store.get_checkpoint()
        self.reopen()
        self.assertIs(self.store.get_action(ACTION_ID).phase, ActionPhase.ATTEMPT_STARTED)
        with self.assertRaises(RuntimeStoreConflictError):
            self.store.start_attempt(ACTION_ID, self.next_checkpoint(), expected_sequence=3)

    def test_second_attempt_is_explicitly_forbidden(self):
        self.attempt()
        with self.assertRaises(RuntimeStoreConflictError):
            self.store.start_attempt(ACTION_ID, self.next_checkpoint(), expected_sequence=3)
        self.assertEqual(self.store.get_action(ACTION_ID).attempt_count, 1)

    def test_unsafe_runtime_state_cannot_mark_send(self):
        self.prepare()
        cp = self.next_checkpoint(snapshot=replace(self.store.get_checkpoint().snapshot, state=RuntimeState.UNCERTAIN, position_evidence=PositionEvidence.LAST_KNOWN, reason=RuntimeReason.EVIDENCE_MISSING))
        self.store.save_checkpoint(cp, expected_sequence=2)
        with self.assertRaises(RuntimeStoreConflictError):
            self.store.start_attempt(ACTION_ID, self.next_checkpoint(), expected_sequence=3)

    def test_acknowledgement_persists_without_fill_or_position_change(self):
        action = self.acknowledge()
        cp = self.store.get_checkpoint()
        self.reopen()
        self.assertEqual(self.store.get_action(ACTION_ID), action)
        self.assertIs(self.store.get_checkpoint().snapshot.state, RuntimeState.ORDER_PENDING)
        self.assertEqual(cp.snapshot.owned_base_quantity, 0)
        self.assertIsNone(self.store.get_fill("fill-1"))

    def test_acknowledgement_cannot_clear_pending_work(self):
        action = self.attempt()
        cp = self.next_checkpoint(snapshot=RuntimeStateSnapshot(RuntimeState.LONG, D("1"), PositionEvidence.CONFIRMED, 1))
        with self.assertRaises(RuntimeStoreIntegrityError):
            self.store.record_observation(receipt(action), cp, expected_sequence=3)
        self.assertIs(self.store.get_action(ACTION_ID).phase, ActionPhase.ATTEMPT_STARTED)

    def test_unknown_outcome_persists_original_id_and_uncertainty(self):
        action = replace(self.attempt(), phase=ActionPhase.UNKNOWN_OUTCOME, safe_reason=RuntimeReason.ACTION_OUTCOME_UNKNOWN)
        snapshot = replace(self.store.get_checkpoint().snapshot, state=RuntimeState.UNCERTAIN, position_evidence=PositionEvidence.LAST_KNOWN, reason=RuntimeReason.ACTION_OUTCOME_UNKNOWN)
        cp = self.next_checkpoint(snapshot=snapshot)
        self.store.record_observation(action, cp, expected_sequence=3)
        self.reopen()
        self.assertEqual(self.store.get_action(ACTION_ID), action)
        self.assertEqual(self.store.get_checkpoint(), cp)
        with self.assertRaises(RuntimeStoreConflictError):
            self.store.start_attempt(ACTION_ID, self.next_checkpoint(), expected_sequence=4)

    def test_unknown_outcome_cannot_claim_confirmed_certainty(self):
        action = replace(self.attempt(), phase=ActionPhase.UNKNOWN_OUTCOME, safe_reason=RuntimeReason.ACTION_OUTCOME_UNKNOWN)
        with self.assertRaises(RuntimeStoreIntegrityError):
            self.store.record_observation(action, self.next_checkpoint(), expected_sequence=3)

    def test_phase_regression_cannot_erase_attempt(self):
        self.attempt()
        with self.assertRaises(RuntimeStoreConflictError):
            self.store.record_observation(prepared(), self.next_checkpoint(), expected_sequence=3)

    def test_recovery_bounds_cannot_reset(self):
        action = self.acknowledge()
        reduced = replace(action, remaining_read_attempts=1, remaining_reconciliation_rounds=1)
        self.store.record_observation(reduced, self.next_checkpoint(), expected_sequence=4)
        with self.assertRaises(RuntimeStoreConflictError):
            self.store.record_observation(action, self.next_checkpoint(), expected_sequence=5)

    def test_known_broker_identity_and_submitted_amount_cannot_change(self):
        action = self.acknowledge()
        for changed in (replace(action, broker_order_id="other-order"), replace(action, submitted_amount=D("9")), replace(action, order_link_id="other-link")):
            with self.subTest(changed=changed), self.assertRaises(RuntimeStoreConflictError):
                self.store.record_observation(changed, self.next_checkpoint(), expected_sequence=4)

    def test_preflight_unsent_abandonment_preserves_consumed_ids(self):
        self.prepare()
        cp = self.next_checkpoint(snapshot=RuntimeStateSnapshot(RuntimeState.FLAT, D("0"), PositionEvidence.CONFIRMED, 1))
        self.store.abandon_prepared(ACTION_ID, cp, expected_sequence=2, terminal_at_ms=HOUR + 1)
        self.reopen()
        self.assertIs(self.store.get_action(ACTION_ID).phase, ActionPhase.ABANDONED_UNSENT)
        self.assertEqual(self.store.get_action(ACTION_ID).order_link_id, prepared().order_link_id)
        with self.assertRaises(RuntimeStoreConflictError):
            self.store.start_attempt(ACTION_ID, self.next_checkpoint(), expected_sequence=3)

    def test_attempted_action_cannot_be_abandoned_as_unsent(self):
        self.attempt()
        with self.assertRaises(RuntimeStoreConflictError):
            self.store.abandon_prepared(ACTION_ID, self.next_checkpoint(), expected_sequence=3, terminal_at_ms=HOUR + 1)

    def test_confirmed_rejection_remains_separate_from_uncertainty(self):
        action = replace(self.attempt(), phase=ActionPhase.REJECTED, rejection_code=10001, terminal_at_ms=HOUR + 1)
        cp = self.next_checkpoint(snapshot=RuntimeStateSnapshot(RuntimeState.FLAT, D("0"), PositionEvidence.CONFIRMED, 1))
        self.store.record_observation(action, cp, expected_sequence=3)
        self.assertEqual(self.store.get_action(ACTION_ID).rejection_code, 10001)

    def test_no_observation_can_bypass_attempt_start(self):
        self.prepare()
        ack = receipt(replace(prepared(), phase=ActionPhase.ATTEMPT_STARTED, attempt_count=1))
        with self.assertRaises(RuntimeStoreConflictError):
            self.store.record_observation(ack, self.next_checkpoint(), expected_sequence=2)

    def test_cancellation_control_is_subordinate_and_receipt_not_terminal(self):
        parent = self.acknowledge()
        cancel = ActionRecord("e"*64, JournalActionKind.CANCEL, "BTCUSDT", HOUR + 600000, 5, 3,
                              control_id="operator1", parent_action_id=ACTION_ID, target_broker_order_id="order-1")
        self.store.prepare_cancellation(cancel, self.next_checkpoint(), expected_sequence=4)
        self.store.start_attempt(cancel.logical_action_id, self.next_checkpoint(), expected_sequence=5)
        cancel = replace(cancel, phase=ActionPhase.ACKNOWLEDGED, attempt_count=1,
                         acknowledgement_broker_ms=HOUR + 5, acknowledgement_observed_ms=HOUR + 6)
        self.store.record_observation(cancel, self.next_checkpoint(), expected_sequence=6)
        self.assertEqual(self.store.get_action(ACTION_ID), parent)
        self.assertEqual(self.store.get_checkpoint().snapshot.pending_action.logical_action_id, ACTION_ID)

    def test_cancellation_target_must_be_exact_known_owned_order(self):
        self.acknowledge()
        cancel = ActionRecord("e"*64, JournalActionKind.CANCEL, "BTCUSDT", HOUR + 600000, 5, 3,
                              control_id="operator1", parent_action_id=ACTION_ID, target_broker_order_id="wrong-order")
        with self.assertRaises(RuntimeStoreIntegrityError):
            self.store.prepare_cancellation(cancel, self.next_checkpoint(), expected_sequence=4)
        self.assertIsNone(self.store.get_action("e"*64))


class UnknownOutcomeRecoveryTests(StoreCase):
    """Supplied observations may recover pending work without inventing receipts."""

    def unknown_action(self):
        action = replace(self.attempt(), phase=ActionPhase.UNKNOWN_OUTCOME,
                         safe_reason=RuntimeReason.ACTION_OUTCOME_UNKNOWN,
                         remaining_reconciliation_rounds=4, remaining_read_attempts=2)
        current = self.store.get_checkpoint()
        snapshot = transition_runtime_state(current.snapshot, RuntimeEvent(
            RuntimeEventType.UNCERTAINTY_DETECTED, reason=RuntimeReason.ACTION_OUTCOME_UNKNOWN))
        self.store.record_observation(action, self.next_checkpoint(snapshot=snapshot),
                                      expected_sequence=current.sequence)
        return action

    def observed_action(self, action, status="OPEN"):
        return replace(action, broker_order_id="order-1", observed_at_ms=HOUR + 4,
                       order_status=status, external_status="New" if status == "OPEN" else "PartiallyFilled")

    def pending_checkpoint(self, quantity=D("0"), observed_at_ms=HOUR + 4):
        current = self.store.get_checkpoint()
        snapshot = transition_runtime_state(current.snapshot, RuntimeEvent(
            RuntimeEventType.RECONCILED_PENDING,
            evidence=RuntimeEvidence(quantity, current.snapshot.pending_action)))
        return replace(current, sequence=current.sequence + 1, snapshot=snapshot,
                       observed_at_ms=observed_at_ms, last_reconciled_at_ms=observed_at_ms)

    def test_observed_open_recovers_original_pending_identity_without_receipt(self):
        original = self.unknown_action()
        observed = self.observed_action(original)
        before = self.store.get_checkpoint()
        checkpoint = self.pending_checkpoint()
        self.store.record_observation(observed, checkpoint, expected_sequence=before.sequence)
        self.reopen()
        saved = self.store.get_action(ACTION_ID)
        self.assertEqual(saved, observed)
        self.assertEqual(self.store.get_checkpoint(), checkpoint)
        self.assertIs(checkpoint.snapshot.state, RuntimeState.ORDER_PENDING)
        self.assertEqual(checkpoint.snapshot.pending_action, PendingAction(ACTION_ID, PendingActionKind.ENTRY))
        self.assertEqual((saved.logical_action_id, saved.order_link_id),
                         (original.logical_action_id, original.order_link_id))
        self.assertEqual(saved.broker_order_id, "order-1")
        self.assertIs(saved.phase, ActionPhase.UNKNOWN_OUTCOME)
        self.assertEqual(saved.attempt_count, 1)
        self.assertIs(saved.safe_reason, RuntimeReason.ACTION_OUTCOME_UNKNOWN)
        self.assertIsNone(saved.acknowledgement_broker_ms)
        self.assertIsNone(saved.acknowledgement_observed_ms)
        self.assertIsNone(saved.submitted_amount)
        self.assertIsNone(saved.terminal_at_ms)
        self.assertIsNone(self.store.get_fill("fill-1"))

    def test_observed_partial_fill_recovers_atomically_and_replays_once(self):
        observed = self.observed_action(self.unknown_action(), "PARTIALLY_FILLED")
        execution = replace(fill(), executed_quantity=D("0.05"), execution_price=D("100"),
                            execution_fee=D("0.00005"))
        checkpoint = self.pending_checkpoint(D("0.04995"))
        self.store.record_observation(observed, checkpoint, expected_sequence=checkpoint.sequence - 1,
                                      fills=(execution, execution))
        self.reopen()
        self.assertEqual(self.store.get_action(ACTION_ID), observed)
        self.assertEqual(self.store.get_fill("fill-1"), execution)
        self.assertEqual(self.store.get_checkpoint(), checkpoint)
        replay = self.pending_checkpoint(D("0.04995"))
        self.store.record_observation(observed, replay, expected_sequence=checkpoint.sequence,
                                      fills=(replace(execution, observed_at_ms=HOUR + 10),))
        self.reopen()
        self.assertEqual(self.store.get_fill("fill-1"), execution)
        self.assertEqual(self.store._connection.execute("SELECT count(*) FROM fills").fetchone()[0], 1)
        self.assertEqual(self.store.get_checkpoint().snapshot.owned_base_quantity, D("0.04995"))
        self.assertIs(self.store.get_checkpoint().snapshot.state, RuntimeState.ORDER_PENDING)
        self.assertIsNone(self.store.get_action(ACTION_ID).acknowledgement_broker_ms)
        self.assertEqual(self.store.get_action(ACTION_ID).attempt_count, 1)

    def test_synchronization_retains_unknown_work_and_last_known_quantity(self):
        action = self.unknown_action()
        current = self.store.get_checkpoint()
        snapshot = transition_runtime_state(current.snapshot, RuntimeEvent(
            RuntimeEventType.RECOVERY_VALIDATED,
            evidence=RuntimeEvidence(D("0"), current.snapshot.pending_action)))
        checkpoint = self.next_checkpoint(snapshot=snapshot)
        self.store.save_checkpoint(checkpoint, expected_sequence=current.sequence)
        self.reopen()
        self.assertEqual(self.store.get_checkpoint(), checkpoint)
        self.assertIs(snapshot.state, RuntimeState.SYNCHRONIZING)
        self.assertIs(snapshot.position_evidence, PositionEvidence.LAST_KNOWN)
        self.assertEqual(snapshot.pending_action, current.snapshot.pending_action)
        self.assertEqual(self.store.get_action(ACTION_ID), action)

    def test_explicit_halt_rearm_retains_unknown_action_and_last_known_quantity(self):
        action = self.unknown_action()
        current = self.store.get_checkpoint()
        halted = transition_runtime_state(current.snapshot, RuntimeEvent(
            RuntimeEventType.FATAL_INCONSISTENCY, reason=RuntimeReason.RECOVERY_EXHAUSTED))
        self.store.save_checkpoint(self.next_checkpoint(snapshot=halted, halted_at_ms=HOUR + 5),
                                   expected_sequence=current.sequence)
        current = self.store.get_checkpoint()
        synchronized = transition_runtime_state(current.snapshot, RuntimeEvent(RuntimeEventType.OPERATOR_REARMED))
        checkpoint = self.next_checkpoint(snapshot=synchronized, halted_at_ms=None, rearmed_at_ms=HOUR + 6)
        self.store.save_checkpoint(checkpoint, expected_sequence=current.sequence)
        self.reopen()
        self.assertEqual(self.store.get_checkpoint(), checkpoint)
        self.assertIs(synchronized.position_evidence, PositionEvidence.LAST_KNOWN)
        self.assertEqual(synchronized.pending_action, halted.pending_action)
        self.assertEqual(self.store.get_action(ACTION_ID), action)

    def test_synchronization_retains_unknown_quantity_without_fabricating_zero(self):
        action = self.unknown_action()
        current = self.store.get_checkpoint()
        halted = RuntimeStateSnapshot(RuntimeState.HALTED, desired_position=1,
                                     pending_action=current.snapshot.pending_action,
                                     reason=RuntimeReason.EVIDENCE_MISSING)
        self.store.save_checkpoint(self.next_checkpoint(snapshot=halted, halted_at_ms=HOUR + 5),
                                   expected_sequence=current.sequence)
        current = self.store.get_checkpoint()
        synchronized = transition_runtime_state(current.snapshot, RuntimeEvent(RuntimeEventType.OPERATOR_REARMED))
        checkpoint = self.next_checkpoint(snapshot=synchronized, halted_at_ms=None, rearmed_at_ms=HOUR + 6)
        self.store.save_checkpoint(checkpoint, expected_sequence=current.sequence)
        self.reopen()
        self.assertEqual(self.store.get_checkpoint(), checkpoint)
        self.assertIs(synchronized.position_evidence, PositionEvidence.UNKNOWN)
        self.assertIsNone(synchronized.owned_base_quantity)
        self.assertEqual(synchronized.pending_action, halted.pending_action)
        self.assertEqual(self.store.get_action(ACTION_ID), action)

    def test_synchronization_cannot_drop_original_pending_identity(self):
        action = self.unknown_action()
        current = self.store.get_checkpoint()
        synchronized = RuntimeStateSnapshot(RuntimeState.SYNCHRONIZING, desired_position=1)
        with self.assertRaises(RuntimeStoreIntegrityError):
            self.store.save_checkpoint(self.next_checkpoint(snapshot=synchronized), expected_sequence=current.sequence)
        self.assertEqual(self.store.get_checkpoint(), current)
        self.assertEqual(self.store.get_action(ACTION_ID), action)

    def test_synchronization_cannot_claim_confirmed_exposure(self):
        self.unknown_action()
        current = self.store.get_checkpoint()
        with self.assertRaises(RuntimeStateError):
            replace(current.snapshot, state=RuntimeState.SYNCHRONIZING,
                    position_evidence=PositionEvidence.CONFIRMED, reason=None)
        self.assertEqual(self.store.get_checkpoint(), current)

    def test_unknown_and_other_unapproved_statuses_cannot_claim_pending(self):
        action = self.unknown_action()
        current = self.store.get_checkpoint()
        for status in ("UNKNOWN", "NEW", "FILLED", "CANCELLED", "REJECTED", "EXPIRED", None):
            observed = replace(self.observed_action(action), order_status=status)
            with self.subTest(status=status), self.assertRaises(RuntimeStoreIntegrityError):
                self.store.record_observation(observed, self.pending_checkpoint(), expected_sequence=current.sequence)
            self.assertEqual(self.store.get_checkpoint(), current)
            self.assertEqual(self.store.get_action(ACTION_ID), action)

    def test_missing_broker_order_id_cannot_claim_pending(self):
        action = self.unknown_action()
        current = self.store.get_checkpoint()
        observed = replace(self.observed_action(action), broker_order_id=None)
        with self.assertRaises(RuntimeStoreIntegrityError):
            self.store.record_observation(observed, self.pending_checkpoint(), expected_sequence=current.sequence)
        self.assertEqual(self.store.get_checkpoint(), current)
        self.assertEqual(self.store.get_action(ACTION_ID), action)

    def test_missing_observation_timestamp_cannot_claim_pending(self):
        action = self.unknown_action()
        current = self.store.get_checkpoint()
        with self.assertRaises(RuntimeStoreError):
            replace(self.observed_action(action), observed_at_ms=None)
        observed = replace(action, broker_order_id="order-1")
        with self.assertRaises(RuntimeStoreIntegrityError):
            self.store.record_observation(observed, self.pending_checkpoint(), expected_sequence=current.sequence)
        self.assertEqual(self.store.get_checkpoint(), current)
        self.assertEqual(self.store.get_action(ACTION_ID), action)

    def test_wrong_pending_action_id_or_kind_cannot_claim_recovery(self):
        action = self.unknown_action()
        current = self.store.get_checkpoint()
        for pending, error in ((PendingAction("e" * 64, PendingActionKind.ENTRY), RuntimeStoreConflictError),
                               (PendingAction(ACTION_ID, PendingActionKind.EXIT), RuntimeStoreIntegrityError)):
            checkpoint = self.pending_checkpoint()
            checkpoint = replace(checkpoint, snapshot=replace(checkpoint.snapshot, pending_action=pending))
            with self.subTest(pending=pending), self.assertRaises(error):
                self.store.record_observation(self.observed_action(action), checkpoint, expected_sequence=current.sequence)
        self.assertEqual(self.store.get_checkpoint(), current)
        self.assertEqual(self.store.get_action(ACTION_ID), action)

    def test_unresolved_unknown_action_cannot_claim_flat_or_long(self):
        action = self.unknown_action()
        current = self.store.get_checkpoint()
        for state, quantity in ((RuntimeState.FLAT, D("0")), (RuntimeState.LONG, D("1"))):
            snapshot = RuntimeStateSnapshot(state, quantity, PositionEvidence.CONFIRMED, 1)
            with self.subTest(state=state), self.assertRaises(RuntimeStoreIntegrityError):
                self.store.record_observation(self.observed_action(action), self.next_checkpoint(snapshot=snapshot),
                                              expected_sequence=current.sequence)
        self.assertEqual(self.store.get_checkpoint(), current)
        self.assertEqual(self.store.get_action(ACTION_ID), action)

    def test_recovery_cannot_change_original_action_link(self):
        action = self.unknown_action()
        current = self.store.get_checkpoint()
        observed = replace(self.observed_action(action), order_link_id="other-link")
        with self.assertRaises(RuntimeStoreConflictError):
            self.store.record_observation(observed, self.pending_checkpoint(), expected_sequence=current.sequence)
        self.assertEqual(self.store.get_checkpoint(), current)
        self.assertEqual(self.store.get_action(ACTION_ID), action)

    def test_recovered_broker_order_id_cannot_be_rebound(self):
        observed = self.observed_action(self.unknown_action())
        checkpoint = self.pending_checkpoint()
        self.store.record_observation(observed, checkpoint, expected_sequence=checkpoint.sequence - 1)
        with self.assertRaises(RuntimeStoreConflictError):
            self.store.record_observation(replace(observed, broker_order_id="other-order"),
                                          self.pending_checkpoint(), expected_sequence=checkpoint.sequence)
        self.assertEqual(self.store.get_checkpoint(), checkpoint)
        self.assertEqual(self.store.get_action(ACTION_ID), observed)

    def test_conflicting_fill_rolls_back_recovered_observation_and_new_fill(self):
        observed = self.observed_action(self.unknown_action(), "PARTIALLY_FILLED")
        execution = replace(fill(), executed_quantity=D("0.05"), execution_price=D("100"),
                            execution_fee=D("0.00005"))
        checkpoint = self.pending_checkpoint(D("0.04995"))
        self.store.record_observation(observed, checkpoint, expected_sequence=checkpoint.sequence - 1, fills=(execution,))
        changed = replace(observed, observed_at_ms=HOUR + 10)
        with self.assertRaises(RuntimeStoreConflictError):
            self.store.record_observation(changed, self.pending_checkpoint(D("0.1"), HOUR + 10),
                                          expected_sequence=checkpoint.sequence,
                                          fills=(replace(execution, broker_execution_id="fill-2"),
                                                 replace(execution, execution_price=D("101"))))
        self.reopen()
        self.assertEqual(self.store.get_checkpoint(), checkpoint)
        self.assertEqual(self.store.get_action(ACTION_ID), observed)
        self.assertEqual(self.store.get_fill("fill-1"), execution)
        self.assertIsNone(self.store.get_fill("fill-2"))

    def test_wrong_fill_identity_rolls_back_pending_recovery(self):
        action = self.unknown_action()
        current = self.store.get_checkpoint()
        for name, value in (("action_id", "e" * 64), ("broker_order_id", "wrong"),
                            ("order_link_id", "wrong"), ("symbol", "ETHUSDT"),
                            ("side", "SELL"), ("account_binding", "other")):
            with self.subTest(field=name), self.assertRaises(RuntimeStoreError):
                self.store.record_observation(self.observed_action(action, "PARTIALLY_FILLED"),
                                              self.pending_checkpoint(D("0.1")), expected_sequence=current.sequence,
                                              fills=(replace(fill(), **{name: value}),))
            self.assertEqual(self.store.get_checkpoint(), current)
            self.assertEqual(self.store.get_action(ACTION_ID), action)
            self.assertIsNone(self.store.get_fill("fill-1"))

    def test_commit_failure_rolls_back_action_fill_and_pending_checkpoint(self):
        action = self.unknown_action()
        current = self.store.get_checkpoint()
        with patch.object(self.store, "_commit", side_effect=sqlite3.OperationalError("Injected commit fault")), self.assertRaises(RuntimeStoreError):
            self.store.record_observation(self.observed_action(action, "PARTIALLY_FILLED"),
                                          self.pending_checkpoint(D("0.1")), expected_sequence=current.sequence,
                                          fills=(fill(),))
        self.reopen()
        self.assertEqual(self.store.get_checkpoint(), current)
        self.assertEqual(self.store.get_action(ACTION_ID), action)
        self.assertIsNone(self.store.get_fill("fill-1"))

    def test_unknown_recovery_cannot_regress_phase_or_reset_attempt_count(self):
        action = self.unknown_action()
        current = self.store.get_checkpoint()
        for phase in (ActionPhase.PREPARED, ActionPhase.ATTEMPT_STARTED):
            regressed = replace(action, phase=phase, attempt_count=0 if phase == ActionPhase.PREPARED else 1)
            with self.subTest(phase=phase), self.assertRaises(RuntimeStoreConflictError):
                self.store.record_observation(regressed, self.pending_checkpoint(), expected_sequence=current.sequence)
        for count in (0, 2):
            with self.subTest(count=count), self.assertRaises(RuntimeStoreError):
                replace(action, attempt_count=count)
        self.assertEqual(self.store.get_checkpoint(), current)
        self.assertEqual(self.store.get_action(ACTION_ID), action)

    def test_unknown_recovery_cannot_reset_remaining_budgets(self):
        action = self.unknown_action()
        current = self.store.get_checkpoint()
        for field, value in (("remaining_reconciliation_rounds", 5), ("remaining_read_attempts", 3)):
            observed = replace(self.observed_action(action), **{field: value})
            with self.subTest(field=field), self.assertRaises(RuntimeStoreConflictError):
                self.store.record_observation(observed, self.pending_checkpoint(), expected_sequence=current.sequence)
        self.assertEqual(self.store.get_checkpoint(), current)
        self.assertEqual(self.store.get_action(ACTION_ID), action)

    def test_recovered_pending_action_still_cannot_start_second_attempt(self):
        observed = self.observed_action(self.unknown_action())
        checkpoint = self.pending_checkpoint()
        self.store.record_observation(observed, checkpoint, expected_sequence=checkpoint.sequence - 1)
        with self.assertRaises(RuntimeStoreConflictError):
            self.store.start_attempt(ACTION_ID, self.pending_checkpoint(), expected_sequence=checkpoint.sequence)
        self.assertEqual(self.store.get_checkpoint(), checkpoint)
        self.assertEqual(self.store.get_action(ACTION_ID), observed)

    def test_observing_parent_does_not_resolve_unknown_cancellation(self):
        parent = self.observed_action(self.unknown_action())
        checkpoint = self.pending_checkpoint()
        self.store.record_observation(parent, checkpoint, expected_sequence=checkpoint.sequence - 1)
        cancel = ActionRecord("e" * 64, JournalActionKind.CANCEL, "BTCUSDT", HOUR + 600000, 5, 3,
                              control_id="operator1", parent_action_id=ACTION_ID, target_broker_order_id="order-1")
        self.store.prepare_cancellation(cancel, self.next_checkpoint(), expected_sequence=checkpoint.sequence)
        current = self.store.get_checkpoint()
        self.store.start_attempt(cancel.logical_action_id, self.next_checkpoint(), expected_sequence=current.sequence)
        current = self.store.get_checkpoint()
        cancel = replace(self.store.get_action(cancel.logical_action_id), phase=ActionPhase.UNKNOWN_OUTCOME,
                         safe_reason=RuntimeReason.ACTION_OUTCOME_UNKNOWN)
        uncertain = transition_runtime_state(current.snapshot, RuntimeEvent(
            RuntimeEventType.UNCERTAINTY_DETECTED, reason=RuntimeReason.ACTION_OUTCOME_UNKNOWN))
        self.store.record_observation(cancel, self.next_checkpoint(snapshot=uncertain), expected_sequence=current.sequence)
        current = self.store.get_checkpoint()
        with self.assertRaises(RuntimeStoreIntegrityError):
            self.store.record_observation(replace(parent, observed_at_ms=HOUR + 10),
                                          self.pending_checkpoint(observed_at_ms=HOUR + 10), expected_sequence=current.sequence)
        self.reopen()
        self.assertEqual(self.store.get_checkpoint(), current)
        self.assertEqual(self.store.get_action(ACTION_ID), parent)
        self.assertEqual(self.store.get_action(cancel.logical_action_id), cancel)

    def test_unknown_action_halt_cannot_clear_without_valid_explicit_rearm(self):
        action = self.unknown_action()
        current = self.store.get_checkpoint()
        halted = transition_runtime_state(current.snapshot, RuntimeEvent(
            RuntimeEventType.FATAL_INCONSISTENCY, reason=RuntimeReason.RECOVERY_EXHAUSTED))
        self.store.save_checkpoint(self.next_checkpoint(snapshot=halted, halted_at_ms=HOUR + 5),
                                   expected_sequence=current.sequence)
        current = self.store.get_checkpoint()
        synchronized = transition_runtime_state(current.snapshot, RuntimeEvent(RuntimeEventType.OPERATOR_REARMED))
        for rearm_time in (None, HOUR + 4, HOUR + 5):
            with self.subTest(rearm_time=rearm_time), self.assertRaises(RuntimeStoreConflictError):
                self.store.save_checkpoint(self.next_checkpoint(snapshot=synchronized, halted_at_ms=None,
                                                                rearmed_at_ms=rearm_time), expected_sequence=current.sequence)
        with self.assertRaises(RuntimeStoreConflictError):
            self.store.record_observation(self.observed_action(action),
                                          self.next_checkpoint(snapshot=RuntimeStateSnapshot(
                                              RuntimeState.ORDER_PENDING, D("0"), PositionEvidence.CONFIRMED, 1,
                                              current.snapshot.pending_action), halted_at_ms=None, rearmed_at_ms=HOUR + 6),
                                          expected_sequence=current.sequence)
        self.reopen()
        self.assertEqual(self.store.get_checkpoint(), current)
        self.assertEqual(self.store.get_action(ACTION_ID), action)


class StartingUnknownOutcomeTests(StoreCase):
    """Approved nonconfirmed STARTING allowance; no process recovery policy."""

    def setUp(self):
        self.directory = self.enterContext(TemporaryDirectory())
        self.config = configuration()
        self.lock = RuntimeAccountLock(Path(self.directory), "research").acquire()
        self.store = RuntimeStore.open(self.lock, self.config, initialize=True)
        self.addCleanup(self.close_current)
        self.enterContext(patch("socket.create_connection", side_effect=AssertionError("No broker network")))
        self.enterContext(patch("os.getenv", side_effect=AssertionError("No credentials")))

    def close_current(self):
        self.store.close()
        self.lock.release()

    def reopen_new_lock(self):
        old_lock, old_path = self.lock, self.lock.database_path
        self.store.close()
        old_lock.release()
        self.lock = RuntimeAccountLock(Path(self.directory), "research").acquire()
        self.assertIsNot(self.lock, old_lock)
        self.assertEqual(self.lock.database_path, old_path)
        self.store = RuntimeStore.open(self.lock, self.config, initialize=False)

    def unknown_placement(self):
        action = replace(self.attempt(), phase=ActionPhase.UNKNOWN_OUTCOME,
                         safe_reason=RuntimeReason.ACTION_OUTCOME_UNKNOWN,
                         remaining_reconciliation_rounds=4, remaining_read_attempts=2)
        current = self.store.get_checkpoint()
        snapshot = transition_runtime_state(current.snapshot, RuntimeEvent(
            RuntimeEventType.UNCERTAINTY_DETECTED, reason=RuntimeReason.ACTION_OUTCOME_UNKNOWN))
        self.store.record_observation(action, self.next_checkpoint(snapshot=snapshot),
                                      expected_sequence=current.sequence)
        return action

    def starting_checkpoint(self, *, quantity=D("0"), pending=None):
        current = self.store.get_checkpoint()
        snapshot = RuntimeStateSnapshot(
            RuntimeState.STARTING, quantity,
            PositionEvidence.UNKNOWN if quantity is None else PositionEvidence.LAST_KNOWN,
            current.snapshot.desired_position, pending or current.snapshot.pending_action,
        )
        return replace(current, sequence=current.sequence + 1, snapshot=snapshot, halted_at_ms=None, shutdown_at_ms=None)

    def persist_starting(self, **kwargs):
        cp = self.starting_checkpoint(**kwargs)
        self.store.save_checkpoint(cp, expected_sequence=cp.sequence - 1)
        return cp

    def assert_reopen_preserves(self, checkpoint):
        actions, fills = self.store.list_actions(), self.store.list_fills()
        candle_before, decision_before = self.store.get_candle(0), self.store.get_decision(0)
        database_bytes = self.lock.database_path.read_bytes()
        self.reopen_new_lock()
        self.assertEqual(self.store.get_configuration(), self.config)
        self.assertEqual(self.store.get_checkpoint(), checkpoint)
        self.assertEqual(self.store.list_actions(), actions)
        self.assertEqual(self.store.list_fills(), fills)
        self.assertEqual(self.store.get_candle(0), candle_before)
        self.assertEqual(self.store.get_decision(0), decision_before)
        self.assertEqual(self.lock.database_path.read_bytes(), database_bytes)
        self.assertIs(checkpoint.snapshot.state, RuntimeState.STARTING)
        self.assertIsNot(checkpoint.snapshot.position_evidence, PositionEvidence.CONFIRMED)

    def test_starting_known_zero_unknown_placement_validates_and_reopens(self):
        action = self.unknown_placement()
        before = self.store.get_checkpoint()
        cp = self.persist_starting()
        self.assertEqual(cp.snapshot.owned_base_quantity, D("0"))
        self.assertIs(cp.snapshot.position_evidence, PositionEvidence.LAST_KNOWN)
        self.assertEqual(cp.snapshot.pending_action, before.snapshot.pending_action)
        self.assert_reopen_preserves(cp)
        self.assertEqual(self.store.get_action(ACTION_ID), action)
        self.assertEqual((action.remaining_reconciliation_rounds, action.remaining_read_attempts,
                          action.reconciliation_deadline_ms), (4, 2, HOUR + 600000))
        self.assertIsNone(action.acknowledgement_broker_ms)
        self.assertIsNone(action.submitted_amount)

    def test_starting_positive_partial_exposure_preserves_fill_and_missing_receipt(self):
        action = replace(self.unknown_placement(), broker_order_id="order-1", order_status="PARTIALLY_FILLED",
                         external_status="PartiallyFilled", observed_at_ms=HOUR + 4)
        execution = replace(fill(), executed_quantity=D("0.05"), execution_price=D("100"), execution_fee=D("0.00005"))
        current = self.store.get_checkpoint()
        snapshot = transition_runtime_state(current.snapshot, RuntimeEvent(
            RuntimeEventType.RECONCILED_PENDING,
            evidence=RuntimeEvidence(D("0.04995"), current.snapshot.pending_action)))
        self.store.record_observation(action, self.next_checkpoint(snapshot=snapshot),
                                      expected_sequence=current.sequence, fills=(execution,))
        cp = self.persist_starting(quantity=D("0.04995"))
        self.assert_reopen_preserves(cp)
        self.assertEqual(cp.snapshot.owned_base_quantity, D("0.04995"))
        self.assertIs(cp.snapshot.position_evidence, PositionEvidence.LAST_KNOWN)
        self.assertEqual(self.store.get_fill("fill-1"), execution)
        self.assertEqual(self.store.get_action(ACTION_ID), action)
        self.assertIsNone(action.acknowledgement_broker_ms)

    def test_starting_unknown_quantity_retains_exact_pending_unknown_action(self):
        action = self.unknown_placement()
        cp = self.persist_starting(quantity=None)
        self.assert_reopen_preserves(cp)
        self.assertIsNone(cp.snapshot.owned_base_quantity)
        self.assertIs(cp.snapshot.position_evidence, PositionEvidence.UNKNOWN)
        self.assertEqual(cp.snapshot.pending_action, PendingAction(ACTION_ID, PendingActionKind.ENTRY))
        self.assertEqual(self.store.get_action(ACTION_ID), action)

    def test_starting_preserves_frontier_cutoffs_coverage_and_observation_fields(self):
        self.unknown_placement()
        before = self.next_checkpoint(last_reconciled_at_ms=HOUR + 2, observed_at_ms=HOUR + 3,
                                      coverage_start_ms=0, coverage_end_ms=HOUR,
                                      rearmed_at_ms=1, bootstrap_until_ms=0, replay_until_ms=HOUR)
        self.store.save_checkpoint(before, expected_sequence=before.sequence - 1)
        cp = self.persist_starting()
        self.assertEqual(cp, replace(before, sequence=before.sequence + 1, snapshot=cp.snapshot))
        self.assert_reopen_preserves(cp)

    def test_starting_reopen_does_not_reset_exhausted_counters_or_deadline(self):
        action = replace(self.unknown_placement(), remaining_reconciliation_rounds=0, remaining_read_attempts=0)
        current = self.store.get_checkpoint()
        self.store.record_observation(action, self.next_checkpoint(), expected_sequence=current.sequence)
        cp = self.persist_starting()
        self.assert_reopen_preserves(cp)
        self.assertEqual(self.store.get_action(ACTION_ID), action)
        self.assertEqual((action.remaining_reconciliation_rounds, action.remaining_read_attempts,
                          action.reconciliation_deadline_ms), (0, 0, HOUR + 600000))

    def assert_checkpoint_rejected(self, proposed):
        before, actions = self.store.get_checkpoint(), self.store.list_actions()
        with self.assertRaises(RuntimeStoreError):
            self.store.save_checkpoint(proposed, expected_sequence=before.sequence)
        self.assertEqual(self.store.get_checkpoint(), before)
        self.assertEqual(self.store.list_actions(), actions)

    def test_flat_still_rejects_unresolved_unknown_placement(self):
        self.unknown_placement()
        snapshot = RuntimeStateSnapshot(RuntimeState.FLAT, D("0"), PositionEvidence.CONFIRMED, 1)
        self.assert_checkpoint_rejected(self.next_checkpoint(snapshot=snapshot))

    def test_long_still_rejects_unresolved_unknown_placement(self):
        self.unknown_placement()
        snapshot = RuntimeStateSnapshot(RuntimeState.LONG, D("0.05"), PositionEvidence.CONFIRMED, 1)
        self.assert_checkpoint_rejected(self.next_checkpoint(snapshot=snapshot))

    def test_starting_cannot_claim_confirmed_position_evidence(self):
        self.unknown_placement()
        with self.assertRaises(RuntimeStateError):
            replace(self.starting_checkpoint().snapshot, position_evidence=PositionEvidence.CONFIRMED)

    def test_starting_requires_pending_action_when_unknown_placement_exists(self):
        self.unknown_placement()
        cp = self.starting_checkpoint()
        self.assert_checkpoint_rejected(replace(cp, snapshot=replace(cp.snapshot, pending_action=None)))

    def test_starting_cannot_change_pending_logical_id(self):
        self.unknown_placement()
        cp = self.starting_checkpoint(pending=PendingAction("e" * 64, PendingActionKind.ENTRY))
        self.assert_checkpoint_rejected(cp)

    def test_starting_cannot_change_pending_action_kind(self):
        self.unknown_placement()
        cp = self.starting_checkpoint(pending=PendingAction(ACTION_ID, PendingActionKind.EXIT))
        self.assert_checkpoint_rejected(cp)

    def test_starting_cannot_add_a_second_unresolved_placement(self):
        original = self.unknown_placement()
        self.persist_starting()
        before = self.store.get_checkpoint()
        second = replace(prepared(), logical_action_id="e" * 64, order_link_id="bot1-" + "e" * 23,
                         candle_open_ms=HOUR, reconciliation_deadline_ms=2 * HOUR + 600000)
        next_decision = replace(decision(HOUR, action=True), action_id=second.logical_action_id)
        cp = replace(self.starting_checkpoint(pending=PendingAction(second.logical_action_id, PendingActionKind.ENTRY)),
                     last_processed_candle_ms=HOUR)
        with self.assertRaises(RuntimeStoreError):
            self.store.commit_decision(candle(HOUR), next_decision, cp, expected_sequence=before.sequence, action=second)
        self.assertEqual(self.store.get_checkpoint(), before)
        self.assertEqual(self.store.list_actions(), (original,))
        self.assertIsNone(self.store.get_action(second.logical_action_id))
        self.assertIsNone(self.store.get_decision(HOUR))
        self.assertIsNone(self.store.get_candle(HOUR))

    def unknown_cancellation(self):
        parent = self.acknowledge()
        cancel = ActionRecord("e" * 64, JournalActionKind.CANCEL, "BTCUSDT", HOUR + 600000, 5, 3,
                              control_id="operator1", parent_action_id=ACTION_ID, target_broker_order_id="order-1")
        current = self.store.get_checkpoint()
        self.store.prepare_cancellation(cancel, self.next_checkpoint(), expected_sequence=current.sequence)
        current = self.store.get_checkpoint()
        self.store.start_attempt(cancel.logical_action_id, self.next_checkpoint(), expected_sequence=current.sequence)
        cancel = replace(self.store.get_action(cancel.logical_action_id), phase=ActionPhase.UNKNOWN_OUTCOME,
                         safe_reason=RuntimeReason.ACTION_OUTCOME_UNKNOWN,
                         remaining_reconciliation_rounds=4, remaining_read_attempts=2)
        current = self.store.get_checkpoint()
        snapshot = transition_runtime_state(current.snapshot, RuntimeEvent(
            RuntimeEventType.UNCERTAINTY_DETECTED, reason=RuntimeReason.ACTION_OUTCOME_UNKNOWN))
        self.store.record_observation(cancel, self.next_checkpoint(snapshot=snapshot), expected_sequence=current.sequence)
        return parent, cancel

    def test_starting_preserves_valid_subordinate_unknown_cancellation_on_reopen(self):
        parent, cancel = self.unknown_cancellation()
        cp = self.persist_starting()
        self.assert_reopen_preserves(cp)
        self.assertEqual(self.store.list_actions(), (parent, cancel))
        self.assertEqual(cp.snapshot.pending_action.logical_action_id, parent.logical_action_id)
        self.assertEqual(cancel.parent_action_id, parent.logical_action_id)
        self.assertEqual(cancel.target_broker_order_id, parent.broker_order_id)

    def test_starting_does_not_allow_cancellation_parent_or_target_rebinding(self):
        parent, cancel = self.unknown_cancellation()
        self.persist_starting()
        before = self.store.get_checkpoint()
        for field, value in (("parent_action_id", "f" * 64), ("target_broker_order_id", "different-order")):
            with self.subTest(field=field), self.assertRaises(RuntimeStoreConflictError):
                self.store.record_observation(replace(cancel, **{field: value}), self.next_checkpoint(),
                                              expected_sequence=before.sequence)
            self.assertEqual(self.store.get_checkpoint(), before)
            self.assertEqual(self.store.list_actions(), (parent, cancel))

    def test_starting_does_not_license_new_cancellation_control(self):
        parent = self.acknowledge()
        self.persist_starting()
        before = self.store.get_checkpoint()
        cancel = ActionRecord("e" * 64, JournalActionKind.CANCEL, "BTCUSDT", HOUR + 600000, 5, 3,
                              control_id="operator1", parent_action_id=ACTION_ID, target_broker_order_id="order-1")
        with self.assertRaises(RuntimeStoreConflictError):
            self.store.prepare_cancellation(cancel, self.next_checkpoint(), expected_sequence=before.sequence)
        self.assertEqual(self.store.get_checkpoint(), before)
        self.assertEqual(self.store.list_actions(), (parent,))

    def test_starting_does_not_license_attempt_start(self):
        action = self.prepare()
        self.persist_starting()
        before = self.store.get_checkpoint()
        with self.assertRaises(RuntimeStoreConflictError):
            self.store.start_attempt(ACTION_ID, self.next_checkpoint(), expected_sequence=before.sequence)
        self.assertEqual(self.store.get_checkpoint(), before)
        self.assertEqual(self.store.get_action(ACTION_ID), action)

    def test_starting_does_not_reset_unknown_action_budgets(self):
        action = self.unknown_placement()
        self.persist_starting()
        before = self.store.get_checkpoint()
        for field, value in (("remaining_reconciliation_rounds", 5), ("remaining_read_attempts", 3)):
            with self.subTest(field=field), self.assertRaises(RuntimeStoreConflictError):
                self.store.record_observation(replace(action, **{field: value}), self.next_checkpoint(),
                                              expected_sequence=before.sequence)
            self.assertEqual(self.store.get_checkpoint(), before)
            self.assertEqual(self.store.get_action(ACTION_ID), action)

    def test_starting_cannot_clear_existing_halt_latch(self):
        self.unknown_placement()
        current = self.store.get_checkpoint()
        snapshot = transition_runtime_state(current.snapshot, RuntimeEvent(
            RuntimeEventType.FATAL_INCONSISTENCY, reason=RuntimeReason.RECOVERY_EXHAUSTED))
        self.store.save_checkpoint(self.next_checkpoint(snapshot=snapshot, halted_at_ms=HOUR + 5),
                                   expected_sequence=current.sequence)
        self.assert_checkpoint_rejected(replace(self.starting_checkpoint(), rearmed_at_ms=HOUR + 6))

    def test_starting_cannot_clear_halt_retained_by_shutdown(self):
        self.unknown_placement()
        current = self.store.get_checkpoint()
        snapshot = transition_runtime_state(current.snapshot, RuntimeEvent(
            RuntimeEventType.FATAL_INCONSISTENCY, reason=RuntimeReason.RECOVERY_EXHAUSTED))
        self.store.save_checkpoint(self.next_checkpoint(snapshot=snapshot, halted_at_ms=HOUR + 5),
                                   expected_sequence=current.sequence)
        current = self.store.get_checkpoint()
        stopped = transition_runtime_state(current.snapshot, RuntimeEvent(RuntimeEventType.SHUTDOWN_REQUESTED))
        self.store.save_checkpoint(self.next_checkpoint(snapshot=stopped, shutdown_at_ms=HOUR + 6),
                                   expected_sequence=current.sequence)
        self.assert_checkpoint_rejected(replace(self.starting_checkpoint(), shutdown_at_ms=None, rearmed_at_ms=HOUR + 7))


class FillAtomicityTests(StoreCase):
    def test_fill_terminal_inventory_and_checkpoint_atomic_roundtrip(self):
        cp = self.settle(self.acknowledge(), fill())
        self.reopen()
        self.assertEqual(self.store.get_checkpoint(), cp)
        self.assertEqual(self.store.get_fill("fill-1"), fill())
        self.assertIs(self.store.get_action(ACTION_ID).phase, ActionPhase.TERMINAL_CONFIRMED)

    def test_multiple_partial_fills_remain_separate(self):
        action = replace(self.acknowledge(), observed_at_ms=HOUR + 4, order_status="PARTIALLY_FILLED", external_status="PartiallyFilled")
        self.store.record_observation(action, self.next_checkpoint(snapshot=replace(self.store.get_checkpoint().snapshot, owned_base_quantity=D("0.1"))), expected_sequence=4, fills=(fill(), fill("fill-2")))
        self.assertIs(self.store.get_checkpoint().snapshot.state, RuntimeState.ORDER_PENDING)
        self.assertIsNotNone(self.store.get_fill("fill-2"))

    def test_exact_duplicate_fill_is_stored_once(self):
        self.settle(self.acknowledge(), fill(), fill())
        self.assertEqual(self.store._connection.execute("SELECT count(*) FROM fills").fetchone()[0], 1)

    def test_later_observation_of_same_fill_retains_first_observation(self):
        action = self.acknowledge()
        self.store.record_observation(action, self.next_checkpoint(), expected_sequence=4, fills=(fill(),))
        self.store.record_observation(action, self.next_checkpoint(), expected_sequence=5, fills=(replace(fill(), observed_at_ms=HOUR + 10),))
        self.assertEqual(self.store.get_fill("fill-1"), fill())

    def test_conflicting_duplicate_fill_rolls_back_entire_settlement(self):
        action = self.acknowledge()
        before = self.store.get_checkpoint()
        with self.assertRaises(RuntimeStoreConflictError):
            self.settle(action, fill(), replace(fill(), execution_price=D("101")))
        self.assertEqual(self.store.get_checkpoint(), before)
        self.assertEqual(self.store.get_action(ACTION_ID), action)
        self.assertIsNone(self.store.get_fill("fill-1"))

    def test_wrong_action_order_link_symbol_side_and_account_rejected(self):
        action = self.acknowledge()
        for name, value in (("action_id", "e"*64), ("broker_order_id", "wrong"), ("order_link_id", "wrong"), ("symbol", "ETHUSDT"), ("side", "SELL"), ("account_binding", "other")):
            with self.subTest(field=name), self.assertRaises(RuntimeStoreError):
                self.settle(action, replace(fill(), **{name: value}))
        self.assertIsNone(self.store.get_fill("fill-1"))

    def test_fill_commit_failure_rolls_back_quantity_terminal_and_fill(self):
        action = self.acknowledge()
        before = self.store.get_checkpoint()
        with patch.object(self.store, "_commit", side_effect=sqlite3.OperationalError("Injected disk failure")), self.assertRaises(RuntimeStoreError):
            self.settle(action, fill())
        self.assertEqual(self.store.get_checkpoint(), before)
        self.assertEqual(self.store.get_action(ACTION_ID), action)
        self.assertIsNone(self.store.get_fill("fill-1"))

    def test_nonzero_fee_without_currency_blocks_terminal_settlement(self):
        action = self.acknowledge()
        with self.assertRaises(RuntimeStoreIntegrityError):
            self.settle(action, replace(fill(), fee_currency=None))
        self.assertIsNone(self.store.get_fill("fill-1"))

    def test_zero_fee_needs_no_invented_currency(self):
        self.settle(self.acknowledge(), replace(fill(), execution_fee=D("0"), fee_currency=None))
        self.assertIsNone(self.store.get_fill("fill-1").fee_currency)

    def test_signed_fee_and_exact_decimal_survive_small_context(self):
        action = self.acknowledge()
        with localcontext() as context:
            context.prec = 2
            self.settle(action, fill())
        self.reopen()
        self.assertEqual(self.store.get_fill("fill-1"), fill())

    def test_terminal_action_cannot_be_rewritten_or_receive_missing_late_fill(self):
        self.settle(self.acknowledge(), fill())
        action = self.store.get_action(ACTION_ID)
        with self.assertRaises(RuntimeStoreConflictError):
            self.store.record_observation(replace(action, terminal_at_ms=HOUR + 10), self.next_checkpoint(), expected_sequence=5)
        with self.assertRaises(RuntimeStoreConflictError):
            self.store.record_observation(action, self.next_checkpoint(), expected_sequence=5, fills=(fill("late"),))

    def test_completed_logical_action_and_link_tombstones_are_unique(self):
        self.settle(self.acknowledge(), fill())
        for candidate in (prepared(), replace(prepared(), logical_action_id="e"*64)):
            with self.subTest(candidate=candidate), self.assertRaises((sqlite3.IntegrityError, RuntimeStoreError)):
                with self.store._transaction():
                    self.store._insert("actions", module._encode(candidate))
        self.assertIs(self.store.get_action(ACTION_ID).phase, ActionPhase.TERMINAL_CONFIRMED)

    def test_full_buy_sell_lifecycle_uses_supplied_owned_base_and_exact_facts(self):
        self.settle(self.acknowledge(), fill())
        owned = self.store.get_checkpoint().snapshot.owned_base_quantity
        exit_id = "e"*64
        exit_action = ActionRecord(exit_id, JournalActionKind.EXIT, "BTCUSDT", 2*HOUR + 600000, 5, 3,
                                   "bot1-" + exit_id[:23], HOUR, side="SELL", amount_unit="BASE",
                                   currency="BTC", authorized_amount=owned)
        exit_decision = DecisionRecord("BTCUSDT", "60", HOUR, "d"*64, "LONG_EXIT", 0,
                                       DecisionDisposition.ACTION, 2*HOUR, exit_id)
        pending = RuntimeStateSnapshot(RuntimeState.ORDER_PENDING, owned, PositionEvidence.CONFIRMED, 0,
                                       PendingAction(exit_id, PendingActionKind.EXIT))
        self.store.commit_decision(candle(HOUR), exit_decision, self.next_checkpoint(snapshot=pending, last_processed_candle_ms=HOUR), expected_sequence=5, action=exit_action)
        self.store.start_attempt(exit_id, self.next_checkpoint(), expected_sequence=6)
        done = replace(exit_action, phase=ActionPhase.TERMINAL_CONFIRMED, attempt_count=1, broker_order_id="order-2",
                       order_status="FILLED", external_status="Filled", observed_at_ms=2*HOUR + 3, terminal_at_ms=2*HOUR + 3)
        execution = OwnedFillRecord("bybit-demo", "research", "sell-fill", exit_id, "order-2",
                                    exit_action.order_link_id, "BTCUSDT", "SELL", owned, D("111"), D("0.01"), "USDT", 2*HOUR + 2, 2*HOUR + 3)
        self.store.record_observation(done, self.next_checkpoint(snapshot=RuntimeStateSnapshot(RuntimeState.FLAT, D("0"), PositionEvidence.CONFIRMED, 0)), expected_sequence=7, fills=(execution,))
        self.reopen()
        self.assertEqual(self.store.get_fill("sell-fill"), execution)
        self.assertIs(self.store.get_checkpoint().snapshot.state, RuntimeState.FLAT)
        self.assertEqual(self.store.get_action(exit_id).authorized_amount, owned)

    def test_same_execution_id_changed_fee_currency_or_quantity_conflicts(self):
        action = self.acknowledge()
        self.store.record_observation(action, self.next_checkpoint(), expected_sequence=4, fills=(fill(),))
        for name, value in (("execution_fee", D("0.1")), ("fee_currency", "USDT"), ("executed_quantity", D("0.2")), ("executed_at_ms", HOUR + 2)):
            with self.subTest(field=name), self.assertRaises(RuntimeStoreConflictError):
                self.store.record_observation(action, self.next_checkpoint(), expected_sequence=5, fills=(replace(fill(), **{name: value}),))
        self.assertEqual(self.store.get_fill("fill-1"), fill())


class StoreBoundaryTests(StoreCase):
    def test_store_requires_held_lock_before_file_access(self):
        unlocked = RuntimeAccountLock(Path(self.directory), "other")
        with patch.object(module.sqlite3, "connect", side_effect=AssertionError("No DB without lock")), self.assertRaises(RuntimeLockError):
            RuntimeStore.open(unlocked, replace(self.config, account_binding="other"), initialize=True)
        self.assertFalse(unlocked.database_path.exists())

    def test_lock_cannot_be_released_before_store_close(self):
        with self.assertRaises(RuntimeLockError):
            self.lock.release()
        self.assertEqual(self.store.get_checkpoint().sequence, 0)

    def test_alternate_database_path_cannot_bypass_canonical_binding(self):
        alternate = Path(self.directory) / "other.sqlite3"
        with self.assertRaises(TypeError):
            RuntimeStore.open(self.lock, self.config, database_path=alternate)
        self.assertFalse(alternate.exists())

    def test_symlink_database_is_rejected(self):
        self.store.close()
        path = self.lock.database_path
        target = path.with_name("saved.sqlite3")
        path.rename(target)
        path.symlink_to(target)
        with self.assertRaises(RuntimeStoreIntegrityError):
            RuntimeStore.open(self.lock, self.config)

    def test_hardlinked_database_is_rejected(self):
        import os
        self.store.close()
        os.link(self.lock.database_path, self.lock.database_path.with_name("alias.sqlite3"))
        with self.assertRaises(RuntimeStoreIntegrityError):
            RuntimeStore.open(self.lock, self.config)

    def test_symlink_account_directory_is_rejected(self):
        self.store.close()
        directory = self.lock.database_path.parent
        target = directory.with_name("moved")
        directory.rename(target)
        directory.symlink_to(target, target_is_directory=True)
        with self.assertRaises(RuntimeStoreError):
            RuntimeStore.open(self.lock, self.config)

    def test_symlink_sqlite_journal_is_rejected_without_touching_target(self):
        self.store.close()
        unrelated = Path(self.directory) / "unrelated"
        unrelated.write_text("preserve")
        self.lock.database_path.with_name("runtime.sqlite3-journal").symlink_to(unrelated)
        with self.assertRaises(RuntimeStoreError):
            RuntimeStore.open(self.lock, self.config)
        self.assertEqual(unrelated.read_text(), "preserve")

    def test_wal_database_is_rejected_without_mode_conversion(self):
        self.corrupt("PRAGMA journal_mode=WAL")
        self.reject_reopen()
        with sqlite3.connect(self.lock.database_path) as connection:
            self.assertEqual(connection.execute("PRAGMA journal_mode").fetchone()[0], "wal")

    def test_existing_database_replaced_during_session_blocks_access(self):
        path = self.lock.database_path
        path.rename(path.with_name("original.sqlite3"))
        path.write_text("unrelated")
        with self.assertRaises(RuntimeStoreIntegrityError):
            self.store.get_checkpoint()
        self.assertEqual(path.read_text(), "unrelated")

    def test_record_bound_fails_instead_of_truncating(self):
        self.prepare()
        self.store.close()
        with patch.object(module, "_MAX_ROWS", 0), self.assertRaises(RuntimeStoreIntegrityError):
            RuntimeStore.open(self.lock, self.config)

    def test_file_size_bound_fails_closed(self):
        self.store.close()
        with patch.object(module, "_MAX_DATABASE_BYTES", 1), self.assertRaises(RuntimeStoreIntegrityError):
            RuntimeStore.open(self.lock, self.config)

    def test_row_bound_rejects_write_atomically(self):
        action = self.acknowledge()
        before = self.store.get_checkpoint()
        with patch.object(module, "_MAX_ROWS", 1), self.assertRaises(RuntimeStoreError):
            self.settle(action, fill("fill-1"), fill("fill-2"))
        self.assertEqual(self.store.get_checkpoint(), before)
        self.assertEqual(self.store.get_action(ACTION_ID), action)
        self.assertIsNone(self.store.get_fill("fill-1"))

    def test_size_bound_rejects_write_atomically(self):
        before = self.store.get_checkpoint()
        with patch.object(module, "_MAX_DATABASE_BYTES", 1), self.assertRaises(RuntimeStoreError):
            self.flat()
        self.assertEqual(self.store.get_checkpoint(), before)

    def test_live_checkpoint_sql_failure_has_safe_persistence_error(self):
        self.store._connection.execute("DROP TABLE fills")
        with self.assertRaises(RuntimeStoreIntegrityError) as caught:
            self.store.get_checkpoint()
        self.assertNotIn("fills", str(caught.exception))

    def test_multiple_store_handles_keep_lock_until_last_close(self):
        second = RuntimeStore.open(self.lock, self.config)
        self.addCleanup(second.close)
        self.store.close()
        with self.assertRaises(RuntimeLockError):
            self.lock.release()
        second.close()
        self.assertEqual(self.lock._stores, 0)

    def test_closed_store_fails_explicitly(self):
        self.store.close()
        with self.assertRaises(RuntimeStoreError):
            self.store.get_checkpoint()

    def test_modules_have_no_broker_network_strategy_or_scheduler_imports(self):
        from trading_lab.runtime import locking
        allowed = {"contextlib", "dataclasses", "decimal", "enum", "hashlib", "json", "os", "pathlib", "re", "sqlite3", "stat", "sys", "fcntl", "locking", "state", "risk.runtime_risk"}
        for source in (module, locking):
            tree = ast.parse(inspect.getsource(source))
            names = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
            names.update(alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names)
            self.assertLessEqual(names, allowed)
            self.assertFalse(any(isinstance(node, (ast.While, ast.AsyncFunctionDef, ast.Await)) for node in ast.walk(tree)))

    def test_frozen_state_source_and_package_are_unchanged(self):
        root = Path(__file__).resolve().parents[1]
        # Literal hashes of published 8b41427 files, never production constants.
        expected = {
            "src/trading_lab/runtime/state.py": "014b92aca145d61a57df230d3c3747025768090d2b96cdeaa97a96e5ad2675bc",
            "src/trading_lab/runtime/__init__.py": "8843b5105846f5386e9ac799f06b8446688043482618cbb8d3fc5a6655f40b60",
        }
        for name, digest in expected.items():
            self.assertEqual(hashlib.sha256((root / name).read_bytes()).hexdigest(), digest)


# Independent contract expectations. Identical terminal/rejection evidence can
# be replayed without rewriting it; attempt-start is never replayed as a send.
PHASE_EXPECTED = {
    ActionPhase.PREPARED: {ActionPhase.ATTEMPT_STARTED, ActionPhase.ABANDONED_UNSENT},
    ActionPhase.ATTEMPT_STARTED: {ActionPhase.ACKNOWLEDGED, ActionPhase.UNKNOWN_OUTCOME, ActionPhase.TERMINAL_CONFIRMED, ActionPhase.REJECTED},
    ActionPhase.ACKNOWLEDGED: {ActionPhase.ACKNOWLEDGED, ActionPhase.UNKNOWN_OUTCOME, ActionPhase.TERMINAL_CONFIRMED},
    ActionPhase.UNKNOWN_OUTCOME: {ActionPhase.UNKNOWN_OUTCOME, ActionPhase.ACKNOWLEDGED, ActionPhase.TERMINAL_CONFIRMED},
    ActionPhase.TERMINAL_CONFIRMED: {ActionPhase.TERMINAL_CONFIRMED},
    ActionPhase.REJECTED: {ActionPhase.REJECTED},
    ActionPhase.ABANDONED_UNSENT: set(),
}


class PhaseMatrixTests(StoreCase):
    def reach_phase(self, phase):
        if phase == ActionPhase.PREPARED:
            return self.prepare()
        if phase == ActionPhase.ATTEMPT_STARTED:
            return self.attempt()
        if phase == ActionPhase.ACKNOWLEDGED:
            return self.acknowledge()
        if phase == ActionPhase.TERMINAL_CONFIRMED:
            self.settle(self.acknowledge())
        elif phase == ActionPhase.UNKNOWN_OUTCOME:
            action = replace(self.attempt(), phase=phase, safe_reason=RuntimeReason.ACTION_OUTCOME_UNKNOWN)
            state = replace(self.store.get_checkpoint().snapshot, state=RuntimeState.UNCERTAIN,
                            position_evidence=PositionEvidence.LAST_KNOWN, reason=RuntimeReason.ACTION_OUTCOME_UNKNOWN)
            self.store.record_observation(action, self.next_checkpoint(snapshot=state), expected_sequence=3)
        elif phase == ActionPhase.REJECTED:
            action = replace(self.attempt(), phase=phase, rejection_code=10001, terminal_at_ms=HOUR + 1)
            state = RuntimeStateSnapshot(RuntimeState.FLAT, D("0"), PositionEvidence.CONFIRMED, 1)
            self.store.record_observation(action, self.next_checkpoint(snapshot=state), expected_sequence=3)
        else:
            self.prepare()
            state = RuntimeStateSnapshot(RuntimeState.FLAT, D("0"), PositionEvidence.CONFIRMED, 1)
            self.store.abandon_prepared(ACTION_ID, self.next_checkpoint(snapshot=state), expected_sequence=2, terminal_at_ms=HOUR + 1)
        return self.store.get_action(ACTION_ID)

    def apply_phase(self, previous, target):
        current = self.store.get_checkpoint()
        if target == ActionPhase.ATTEMPT_STARTED:
            return self.store.start_attempt(ACTION_ID, self.next_checkpoint(), expected_sequence=current.sequence)
        if target == ActionPhase.ABANDONED_UNSENT:
            state = RuntimeStateSnapshot(RuntimeState.FLAT, D("0"), PositionEvidence.CONFIRMED, 1)
            return self.store.abandon_prepared(ACTION_ID, self.next_checkpoint(snapshot=state), expected_sequence=current.sequence, terminal_at_ms=HOUR + 1)
        if target == ActionPhase.PREPARED:
            action, cp = prepared(), self.next_checkpoint()
        elif target == ActionPhase.ACKNOWLEDGED:
            action = receipt(replace(previous, phase=ActionPhase.ATTEMPT_STARTED, attempt_count=1,
                                     terminal_at_ms=None, rejection_code=None))
            cp = self.next_checkpoint()
        elif target == ActionPhase.UNKNOWN_OUTCOME:
            action = replace(previous, phase=target, attempt_count=1, terminal_at_ms=None,
                             rejection_code=None, safe_reason=RuntimeReason.ACTION_OUTCOME_UNKNOWN)
            state = replace(current.snapshot, state=RuntimeState.UNCERTAIN,
                            position_evidence=PositionEvidence.LAST_KNOWN, reason=RuntimeReason.ACTION_OUTCOME_UNKNOWN)
            cp = self.next_checkpoint(snapshot=state)
        elif target == ActionPhase.TERMINAL_CONFIRMED:
            action = terminal(replace(previous, phase=ActionPhase.ATTEMPT_STARTED, attempt_count=1,
                                      terminal_at_ms=None, rejection_code=None))
            cp = self.next_checkpoint(snapshot=RuntimeStateSnapshot(RuntimeState.LONG, D("0.1234691346789"), PositionEvidence.CONFIRMED, 1))
        else:
            action = replace(previous, phase=target, attempt_count=1, rejection_code=10001, terminal_at_ms=HOUR + 1)
            cp = self.next_checkpoint(snapshot=RuntimeStateSnapshot(RuntimeState.FLAT, D("0"), PositionEvidence.CONFIRMED, 1))
        return self.store.record_observation(action, cp, expected_sequence=current.sequence)


def phase_case(source, target):
    def test(self):
        previous = self.reach_phase(source)
        checkpoint = self.store.get_checkpoint()
        if target in PHASE_EXPECTED[source]:
            self.apply_phase(previous, target)
            self.assertIs(self.store.get_action(ACTION_ID).phase, target)
            self.assertEqual(self.store.get_checkpoint().sequence, checkpoint.sequence + 1)
        else:
            with self.assertRaises(RuntimeStoreError):
                self.apply_phase(previous, target)
            self.assertEqual(self.store.get_action(ACTION_ID), previous)
            self.assertEqual(self.store.get_checkpoint(), checkpoint)
    return test


for source in ActionPhase:
    for target in ActionPhase:
        setattr(PhaseMatrixTests, "test_" + source.value.lower() + "__" + target.value.lower(), phase_case(source, target))


class DurableEnumerationTests(StoreCase):
    """Discover local history after restart, without broker or recovery policy."""

    def history(self):
        # Valid public writes insert ENTRY, EXIT, CANCEL in a different order
        # from their IDs. Terminal ENTRY and unresolved EXIT/CANCEL coexist.
        first = replace(fill("buy-z"), executed_quantity=D("0.05"), executed_at_ms=HOUR + 2)
        second = replace(fill("buy-a"), executed_quantity=D("0.073456789"),
                         execution_fee=D("0"), executed_at_ms=HOUR + 1)
        self.settle(self.acknowledge(), first, second)
        owned = self.store.get_checkpoint().snapshot.owned_base_quantity
        exit_id = "a" * 64
        exit_action = ActionRecord(exit_id, JournalActionKind.EXIT, "BTCUSDT", 2 * HOUR + 600000, 5, 3,
                                   "bot1-" + exit_id[:23], HOUR, side="SELL", amount_unit="BASE",
                                   currency="BTC", authorized_amount=owned)
        exit_decision = DecisionRecord("BTCUSDT", "60", HOUR, "d" * 64, "LONG_EXIT", 0,
                                       DecisionDisposition.ACTION, 2 * HOUR, exit_id)
        pending = RuntimeStateSnapshot(RuntimeState.ORDER_PENDING, owned, PositionEvidence.CONFIRMED, 0,
                                       PendingAction(exit_id, PendingActionKind.EXIT))
        current = self.store.get_checkpoint()
        self.store.commit_decision(candle(HOUR), exit_decision,
                                   self.next_checkpoint(snapshot=pending, last_processed_candle_ms=HOUR),
                                   expected_sequence=current.sequence, action=exit_action)
        current = self.store.get_checkpoint()
        self.store.start_attempt(exit_id, self.next_checkpoint(), expected_sequence=current.sequence)
        exit_action = replace(self.store.get_action(exit_id), phase=ActionPhase.ACKNOWLEDGED,
                              broker_order_id="order-2", submitted_amount=owned,
                              acknowledgement_broker_ms=2 * HOUR + 1, acknowledgement_observed_ms=2 * HOUR + 2,
                              order_status="PARTIALLY_FILLED", external_status="PartiallyFilled",
                              observed_at_ms=2 * HOUR + 4)
        third = OwnedFillRecord("bybit-demo", "research", "sell-fill", exit_id, "order-2",
                               exit_action.order_link_id, "BTCUSDT", "SELL", D("0.02"),
                               D("111.123456789"), D("0.01"), "USDT", 2 * HOUR + 3, 2 * HOUR + 4)
        current = self.store.get_checkpoint()
        self.store.record_observation(exit_action,
                                      self.next_checkpoint(snapshot=replace(pending, owned_base_quantity=D("0.1034691346789"))),
                                      expected_sequence=current.sequence, fills=(third,))
        cancel = ActionRecord("b" * 64, JournalActionKind.CANCEL, "BTCUSDT", 2 * HOUR + 600000, 4, 2,
                              control_id="operator-cancel", parent_action_id=exit_id, target_broker_order_id="order-2")
        current = self.store.get_checkpoint()
        self.store.prepare_cancellation(cancel, self.next_checkpoint(), expected_sequence=current.sequence)
        current = self.store.get_checkpoint()
        self.store.start_attempt(cancel.logical_action_id, self.next_checkpoint(), expected_sequence=current.sequence)
        cancel = replace(self.store.get_action(cancel.logical_action_id), phase=ActionPhase.UNKNOWN_OUTCOME,
                         safe_reason=RuntimeReason.ACTION_OUTCOME_UNKNOWN,
                         remaining_reconciliation_rounds=3, remaining_read_attempts=1)
        current = self.store.get_checkpoint()
        uncertain = transition_runtime_state(current.snapshot, RuntimeEvent(
            RuntimeEventType.UNCERTAINTY_DETECTED, reason=RuntimeReason.ACTION_OUTCOME_UNKNOWN))
        self.store.record_observation(cancel, self.next_checkpoint(snapshot=uncertain), expected_sequence=current.sequence)
        return (exit_action, cancel, self.store.get_action(ACTION_ID)), (second, first, third)

    def test_empty_actions_are_an_immutable_tuple(self):
        self.assertEqual(self.store.list_actions(), ())
        self.assertIs(type(self.store.list_actions()), tuple)

    def test_one_prepared_action_is_returned_without_attempting_it(self):
        action = self.prepare()
        self.assertEqual(self.store.list_actions(), (action,))
        self.assertIs(action.phase, ActionPhase.PREPARED)
        self.assertEqual(action.attempt_count, 0)

    def test_all_action_kinds_and_terminal_history_are_returned_in_id_order(self):
        actions, _ = self.history()
        self.assertEqual(self.store.list_actions(), actions)
        self.assertEqual([action.kind for action in actions],
                         [JournalActionKind.EXIT, JournalActionKind.CANCEL, JournalActionKind.ENTRY])
        self.assertIs(actions[-1].phase, ActionPhase.TERMINAL_CONFIRMED)
        self.assertIs(actions[1].phase, ActionPhase.UNKNOWN_OUTCOME)

    def test_cancellation_can_be_discovered_after_restart_from_parent_checkpoint(self):
        actions, _ = self.history()
        before = self.store.get_checkpoint()
        expected_cancel = actions[1]
        self.assertEqual(before.snapshot.pending_action.logical_action_id, expected_cancel.parent_action_id)
        self.assertNotEqual(before.snapshot.pending_action.logical_action_id, expected_cancel.logical_action_id)
        self.reopen()
        # Discovery supplies the control ID; it is not an input to the read.
        discovered = tuple(action for action in self.store.list_actions() if action.kind == JournalActionKind.CANCEL)
        self.assertEqual(discovered, (expected_cancel,))
        self.assertEqual(self.store.get_checkpoint(), before)
        self.assertIsNone(discovered[0].observed_at_ms)
        self.assertIsNone(discovered[0].terminal_at_ms)

    def test_action_and_fill_records_remain_frozen_and_slotted(self):
        self.settle(self.acknowledge(), fill())
        for record in (*self.store.list_actions(), *self.store.list_fills()):
            self.assertFalse(hasattr(record, "__dict__"))
            with self.assertRaises(FrozenInstanceError):
                setattr(record, fields(record)[0].name, "changed")
        with self.assertRaises(TypeError):
            self.store.list_actions()[0] = prepared()

    def test_empty_fills_and_valid_unknown_action_return_empty_tuple(self):
        self.assertEqual(self.store.list_fills(), ())
        self.assertEqual(self.store.list_fills("f" * 64), ())

    def test_one_fill_is_exactly_preserved(self):
        self.settle(self.acknowledge(), fill())
        self.assertEqual(self.store.list_fills(), (fill(),))
        self.assertEqual(self.store.list_fills(ACTION_ID), (fill(),))
        self.assertIs(type(self.store.list_fills()), tuple)

    def test_all_fills_across_actions_are_returned_in_execution_time_order(self):
        _, executions = self.history()
        self.assertEqual(self.store.list_fills(), executions)
        self.assertEqual({record.action_id for record in executions}, {ACTION_ID, "a" * 64})

    def test_fill_filter_is_exact_and_unknown_action_is_empty(self):
        _, executions = self.history()
        self.assertEqual(self.store.list_fills(ACTION_ID), executions[:2])
        self.assertEqual(self.store.list_fills("a" * 64), executions[2:])
        self.assertEqual(self.store.list_fills("f" * 64), ())

    def test_fill_filter_rejects_noncanonical_action_ids(self):
        for value in (True, 1, "", "a" * 63, "a" * 65, "A" * 64, "g" * 64, " " + "a" * 64, [], {}):
            with self.subTest(value=value), self.assertRaises(RuntimeStoreError):
                self.store.list_fills(value)

    def test_equal_execution_times_use_execution_id_order_not_insertion_order(self):
        z = replace(fill("z-fill"), execution_fee=D("0"))
        a = replace(fill("a-fill"), execution_fee=D("0"))
        self.settle(self.acknowledge(), z, a)
        self.assertEqual(self.store.list_fills(), (a, z))
        self.assertEqual(self.store.list_fills(ACTION_ID), (a, z))

    def test_retained_fills_are_discovered_after_restart_without_execution_ids(self):
        _, executions = self.history()
        self.reopen()
        with localcontext() as context:
            context.prec = 2
            discovered = self.store.list_fills(ACTION_ID)
        self.assertEqual(discovered, executions[:2])
        for actual, expected in zip(discovered, executions):
            # Dataclass equality covers IDs, ownership, exact money and times.
            self.assertEqual(actual, expected)
            for name in ("executed_quantity", "execution_price", "execution_fee"):
                self.assertEqual(getattr(actual, name).as_tuple(), getattr(expected, name).as_tuple())

    def test_signed_fees_and_fee_currencies_are_not_inferred_or_changed(self):
        _, executions = self.history()
        self.assertEqual([record.execution_fee for record in self.store.list_fills()],
                         [D("0"), D("-0.0000123456789"), D("0.01")])
        self.assertEqual([record.fee_currency for record in executions], ["BTC", "BTC", "USDT"])

    def test_zero_fee_with_unavailable_currency_remains_unavailable(self):
        execution = replace(fill(), execution_fee=D("0"), fee_currency=None)
        self.settle(self.acknowledge(), execution)
        self.reopen()
        self.assertEqual(self.store.list_fills(), (execution,))

    def test_enumeration_does_not_change_checkpoint_journal_or_database_bytes(self):
        actions, executions = self.history()
        checkpoint = self.store.get_checkpoint()
        before = self.lock.database_path.read_bytes()
        changes = self.store._connection.total_changes
        self.assertFalse(self.store._connection.in_transaction)
        for _ in range(2):
            self.assertEqual(self.store.list_actions(), actions)
            self.assertEqual(self.store.list_fills(), executions)
            self.assertEqual(self.store.list_fills(ACTION_ID), executions[:2])
        self.assertFalse(self.store._connection.in_transaction)
        self.assertEqual(self.store._connection.total_changes, changes)
        self.assertEqual(self.lock.database_path.read_bytes(), before)
        self.assertEqual(self.store.get_checkpoint(), checkpoint)
        for action in actions:
            self.assertEqual(self.store.get_action(action.logical_action_id), action)
        for execution in executions:
            self.assertEqual(self.store.get_fill(execution.broker_execution_id), execution)
        self.reopen()
        self.assertEqual(self.store.list_actions(), actions)
        self.assertEqual(self.store.list_fills(), executions)

    def test_corrupt_later_action_fails_entire_enumeration_without_repair(self):
        self.history()
        self.store._connection.execute("UPDATE actions SET authorized_amount='not-decimal' WHERE logical_action_id=?", (ACTION_ID,))
        before = self.lock.database_path.read_bytes()
        with self.assertRaises(RuntimeStoreIntegrityError):
            self.store.list_actions()
        self.assertEqual(self.lock.database_path.read_bytes(), before)

    def test_corrupt_later_fill_fails_entire_enumeration_without_repair(self):
        self.history()
        self.store._connection.execute("UPDATE fills SET execution_fee='NaN' WHERE broker_execution_id='sell-fill'")
        before = self.lock.database_path.read_bytes()
        with self.assertRaises(RuntimeStoreIntegrityError):
            self.store.list_fills()
        self.assertEqual(self.lock.database_path.read_bytes(), before)

    def test_filtered_read_does_not_hide_corrupt_durable_history(self):
        self.history()
        self.store._connection.execute("UPDATE fills SET execution_price='invalid' WHERE broker_execution_id='sell-fill'")
        with self.assertRaises(RuntimeStoreIntegrityError):
            self.store.list_fills(ACTION_ID)

    def test_action_count_over_existing_bound_fails_without_truncation(self):
        self.history()
        with patch.object(module, "_MAX_ROWS", 2), self.assertRaises(RuntimeStoreIntegrityError):
            self.store.list_actions()

    def test_fill_count_over_existing_bound_fails_even_for_filtered_query(self):
        self.settle(self.acknowledge(), fill("fill-1"), fill("fill-2"), fill("fill-3"))
        with patch.object(module, "_MAX_ROWS", 2):
            for action_id in (None, ACTION_ID, "f" * 64):
                with self.subTest(action_id=action_id), self.assertRaises(RuntimeStoreIntegrityError):
                    self.store.list_fills(action_id)

    def test_complete_history_at_row_bound_returns_every_record(self):
        actions, executions = self.history()
        with patch.object(module, "_MAX_ROWS", 3):
            self.assertEqual(self.store.list_actions(), actions)
            self.assertEqual(self.store.list_fills(), executions)

    def test_both_enumerations_fail_closed_on_durability_setting_drift(self):
        self.store._connection.execute("PRAGMA foreign_keys=OFF")
        for read in (self.store.list_actions, self.store.list_fills):
            with self.subTest(read=read.__name__), self.assertRaises(RuntimeStoreIntegrityError):
                read()

    def test_both_enumerations_require_a_live_store(self):
        self.store.close()
        for read in (self.store.list_actions, self.store.list_fills):
            with self.subTest(read=read.__name__), self.assertRaises(RuntimeStoreError):
                read()

    def test_final_sqlite_query_failure_is_safe_and_returns_no_partial_history(self):
        self.history()
        connection = self.store._connection

        class FailedEnumeration:
            def execute(self, query, *args):
                if " ORDER BY " in query:
                    raise sqlite3.OperationalError("synthetic-private-query-detail")
                return connection.execute(query, *args)

        for read in (self.store.list_actions, self.store.list_fills):
            with self.subTest(read=read.__name__), patch.object(self.store, "_connection", FailedEnumeration()):
                with self.assertRaises(RuntimeStoreIntegrityError) as caught:
                    read()
                self.assertNotIn("synthetic-private", str(caught.exception))
                self.assertIsNone(caught.exception.__cause__)
                self.assertTrue(caught.exception.__suppress_context__)


# Literal frozen 9807ed8 v1 DDL: fixtures never construct v2 or drop risk tables.
LEGACY_V1_SCHEMA = {'identity': 'CREATE TABLE identity (\n'
             '        singleton INTEGER PRIMARY KEY CHECK(singleton=1),\n'
             '        broker_id TEXT NOT NULL, account_binding TEXT NOT NULL, bot_id TEXT NOT NULL,\n'
             '        strategy_id TEXT NOT NULL, strategy_implementation_digest TEXT NOT NULL,\n'
             '        strategy_parameters TEXT NOT NULL, symbol TEXT NOT NULL, base_currency TEXT NOT NULL,\n'
             '        quote_currency TEXT NOT NULL, timeframe TEXT NOT NULL, interval_ms INTEGER NOT NULL,\n'
             '        configuration_digest TEXT NOT NULL, buy_quote_budget TEXT NOT NULL,\n'
             '        history_anchor_ms INTEGER NOT NULL, decision_max_age_ms INTEGER NOT NULL,\n'
             '        observation_max_age_ms INTEGER NOT NULL, reconciliation_timeout_ms INTEGER NOT NULL,\n'
             '        reconciliation_round_limit INTEGER NOT NULL, read_attempt_limit INTEGER NOT NULL,\n'
             '        request_timeout_ms INTEGER NOT NULL, max_clock_skew_ms INTEGER NOT NULL,\n'
             '        broker_account_id TEXT, schema_version INTEGER NOT NULL,\n'
             '        runtime_contract_version INTEGER NOT NULL,\n'
             '        UNIQUE(broker_id, account_binding, bot_id), UNIQUE(broker_id, account_binding)\n'
             '    )',
 'candles': 'CREATE TABLE candles (\n'
            '        symbol TEXT NOT NULL, timeframe TEXT NOT NULL, candle_open_ms INTEGER NOT NULL,\n'
            '        input_fingerprint TEXT NOT NULL, open TEXT NOT NULL, high TEXT NOT NULL,\n'
            '        low TEXT NOT NULL, close TEXT NOT NULL, volume TEXT NOT NULL,\n'
            '        PRIMARY KEY(symbol, timeframe, candle_open_ms), UNIQUE(symbol, candle_open_ms)\n'
            '    )',
 'actions': 'CREATE TABLE actions (\n'
            '        logical_action_id TEXT PRIMARY KEY NOT NULL, kind TEXT NOT NULL CHECK(kind IN '
            "('ENTRY','EXIT','CANCEL')),\n"
            '        symbol TEXT NOT NULL, reconciliation_deadline_ms INTEGER NOT NULL,\n'
            '        remaining_reconciliation_rounds INTEGER NOT NULL '
            'CHECK(remaining_reconciliation_rounds>=0),\n'
            '        remaining_read_attempts INTEGER NOT NULL CHECK(remaining_read_attempts BETWEEN 0 AND '
            '3),\n'
            '        order_link_id TEXT UNIQUE, candle_open_ms INTEGER, control_id TEXT UNIQUE,\n'
            '        parent_action_id TEXT REFERENCES actions(logical_action_id), target_broker_order_id '
            'TEXT,\n'
            '        side TEXT, amount_unit TEXT, currency TEXT, authorized_amount TEXT,\n'
            '        phase TEXT NOT NULL CHECK(phase IN '
            "('PREPARED','ATTEMPT_STARTED','ACKNOWLEDGED','UNKNOWN_OUTCOME','TERMINAL_CONFIRMED','REJECTED','ABANDONED_UNSENT')),\n"
            '        attempt_count INTEGER NOT NULL CHECK(attempt_count IN (0,1)), broker_order_id TEXT '
            'UNIQUE,\n'
            '        submitted_amount TEXT, acknowledgement_broker_ms INTEGER,\n'
            '        acknowledgement_observed_ms INTEGER, observed_at_ms INTEGER, order_status TEXT,\n'
            '        external_status TEXT, terminal_at_ms INTEGER, safe_reason TEXT, rejection_code '
            'INTEGER,\n'
            '        UNIQUE(logical_action_id, broker_order_id, order_link_id),\n'
            '        FOREIGN KEY(symbol, candle_open_ms) REFERENCES candles(symbol, candle_open_ms)\n'
            '    )',
 'decisions': 'CREATE TABLE decisions (\n'
              '        symbol TEXT NOT NULL, timeframe TEXT NOT NULL, candle_open_ms INTEGER NOT NULL,\n'
              '        input_fingerprint TEXT NOT NULL, signal TEXT NOT NULL, desired_position INTEGER NOT '
              'NULL CHECK(desired_position IN (0,1)),\n'
              '        disposition TEXT NOT NULL, available_at_ms INTEGER NOT NULL,\n'
              '        action_id TEXT UNIQUE REFERENCES actions(logical_action_id),\n'
              '        PRIMARY KEY(symbol, timeframe, candle_open_ms),\n'
              '        FOREIGN KEY(symbol, timeframe, candle_open_ms) REFERENCES candles(symbol, timeframe, '
              'candle_open_ms)\n'
              '    )',
 'fills': 'CREATE TABLE fills (\n'
          '        broker_id TEXT NOT NULL, account_binding TEXT NOT NULL,\n'
          '        broker_execution_id TEXT NOT NULL, action_id TEXT NOT NULL,\n'
          '        broker_order_id TEXT NOT NULL, order_link_id TEXT NOT NULL,\n'
          '        symbol TEXT NOT NULL, side TEXT NOT NULL, executed_quantity TEXT NOT NULL,\n'
          '        execution_price TEXT NOT NULL, execution_fee TEXT NOT NULL, fee_currency TEXT,\n'
          '        executed_at_ms INTEGER NOT NULL, observed_at_ms INTEGER NOT NULL,\n'
          '        PRIMARY KEY(broker_id, account_binding, broker_execution_id),\n'
          '        FOREIGN KEY(broker_id, account_binding) REFERENCES identity(broker_id, account_binding),\n'
          '        FOREIGN KEY(action_id, broker_order_id, order_link_id) REFERENCES '
          'actions(logical_action_id, broker_order_id, order_link_id)\n'
          '    )',
 'checkpoint': 'CREATE TABLE checkpoint (\n'
               '        singleton INTEGER PRIMARY KEY CHECK(singleton=1), sequence INTEGER NOT NULL '
               'CHECK(sequence>=0),\n'
               '        state TEXT NOT NULL, owned_base_quantity TEXT, position_evidence TEXT NOT NULL,\n'
               '        desired_position INTEGER CHECK(desired_position IN (0,1)),\n'
               '        pending_action_id TEXT REFERENCES actions(logical_action_id), pending_action_kind '
               'TEXT,\n'
               '        reason TEXT, stopped_from TEXT, last_processed_candle_ms INTEGER,\n'
               '        last_reconciled_at_ms INTEGER, observed_at_ms INTEGER, coverage_start_ms INTEGER,\n'
               '        coverage_end_ms INTEGER, halted_at_ms INTEGER, shutdown_at_ms INTEGER,\n'
               '        rearmed_at_ms INTEGER, bootstrap_until_ms INTEGER, replay_until_ms INTEGER\n'
               '    )'}
LEGACY_V1_INDEXES = {'one_pending_placement': 'CREATE UNIQUE INDEX one_pending_placement ON actions((1)) WHERE kind IN '
                          "('ENTRY','EXIT') AND phase IN "
                          "('PREPARED','ATTEMPT_STARTED','ACKNOWLEDGED','UNKNOWN_OUTCOME')",
 'one_pending_cancel': 'CREATE UNIQUE INDEX one_pending_cancel ON actions(parent_action_id) WHERE '
                       "kind='CANCEL' AND phase IN "
                       "('PREPARED','ATTEMPT_STARTED','ACKNOWLEDGED','UNKNOWN_OUTCOME')"}

# Stage 11.3b: temporary local fixtures only; no runtime/operator DB is touched.
from trading_lab.risk.runtime_risk import (
    RuntimeRiskConfiguration, RiskBook, RiskState, RiskReason, RiskVerdict,
    RiskActionKind, initialize_risk_state, advance_risk_state, apply_owned_execution,
)
from trading_lab.runtime.store import (
    RuntimeStoreMigrationRequiredError, RiskValuationMode, RiskConfigurationRecord,
    RiskEpochRecord, RiskValuationRecord, RiskVerdictRecord,
)


def risk_configuration(**changes):
    return replace(RuntimeRiskConfiguration(D(1000), configuration().buy_quote_budget,
        D(200), D(500), D("0.1"), D("0.2"), 2, "BTC", "USDT"), **changes)


def sql_insert(connection, table, values):
    connection.execute("INSERT INTO " + table + " (" + ",".join(values) + ") VALUES ("
                       + ",".join("?" for _ in values) + ")", tuple(values.values()))


def legacy_fixture(lock, state=RuntimeState.FLAT):
    """Independent authentic v1 schema/rows, including exact financial TEXT."""
    lock.database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(lock.database_path)
    with connection:
        for sql in (*LEGACY_V1_SCHEMA.values(), *LEGACY_V1_INDEXES.values()):
            connection.execute(sql)
        connection.execute("PRAGMA user_version=1")
        identity = module._encode(configuration())
        identity.update(schema_version=1, configuration_digest="1" * 64)
        sql_insert(connection, "identity", dict(singleton=1, **identity))
        has_action = state is not RuntimeState.FLAT
        current_candle = replace(candle(), open=D("123456789.123456789"),
                                 high=D("123456790"), low=D("100"), close=D("105.25"),
                                 volume=D("0.00000001"))
        sql_insert(connection, "candles", module._encode(current_candle))
        pending = state in (RuntimeState.ORDER_PENDING, RuntimeState.UNCERTAIN, RuntimeState.HALTED)
        quantity = D("0.00001001") if has_action else D(0)
        if has_action:
            action = receipt(replace(prepared(), phase=ActionPhase.ATTEMPT_STARTED, attempt_count=1))
            if not pending:
                action = terminal(action)
            if state is RuntimeState.UNCERTAIN:
                action = replace(action, phase=ActionPhase.UNKNOWN_OUTCOME, safe_reason=RuntimeReason.ACTION_OUTCOME_UNKNOWN)
            sql_insert(connection, "actions", module._encode(action))
            execution = replace(fill(), executed_quantity=D("0.00000001"),
                                execution_price=D("123456789.123456789"), execution_fee=D("-0.00001"))
            sql_insert(connection, "fills", module._encode(execution))
        sql_insert(connection, "decisions", module._encode(decision(action=has_action)))
        evidence = PositionEvidence.CONFIRMED if state in (RuntimeState.FLAT, RuntimeState.LONG, RuntimeState.ORDER_PENDING) else PositionEvidence.LAST_KNOWN
        reason = RuntimeReason.INCONSISTENT_EVIDENCE if state in (RuntimeState.UNCERTAIN, RuntimeState.HALTED) else None
        snapshot = RuntimeStateSnapshot(state, quantity, evidence, int(has_action),
            PendingAction(ACTION_ID, PendingActionKind.ENTRY) if pending else None, reason,
            RuntimeState.LONG if state is RuntimeState.STOPPING else None)
        cp = RuntimeCheckpoint(17, snapshot, last_processed_candle_ms=0,
            observed_at_ms=HOUR+5, coverage_start_ms=0, coverage_end_ms=HOUR,
            halted_at_ms=HOUR+5 if state is RuntimeState.HALTED else None,
            shutdown_at_ms=HOUR+6 if state is RuntimeState.STOPPING else None,
            bootstrap_until_ms=0, replay_until_ms=HOUR)
        sql_insert(connection, "checkpoint", dict(singleton=1, **module._checkpoint_values(cp)))
    connection.close()
    return replace(configuration(), configuration_digest="2" * 64)


def raw_legacy(path):
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        return {table: tuple(dict(row) for row in connection.execute("SELECT * FROM " + table + " ORDER BY rowid"))
                for table in LEGACY_V1_SCHEMA}


class RiskMigrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = self.enterContext(TemporaryDirectory())
        self.lock = self.enterContext(RuntimeAccountLock(Path(self.directory), "research"))
        self.enterContext(patch("socket.create_connection", side_effect=AssertionError("No network")))
        self.enterContext(patch("os.getenv", side_effect=AssertionError("No credentials")))

    def fixture(self, state=RuntimeState.FLAT):
        self.config = legacy_fixture(self.lock, state)
        return self.config

    def assert_legacy(self, before):
        self.assertEqual(raw_legacy(self.lock.database_path), before)
        with self.assertRaises(RuntimeStoreMigrationRequiredError):
            RuntimeStore.open(self.lock, self.config)
        with sqlite3.connect(self.lock.database_path) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 1)
            names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertEqual(names, set(LEGACY_V1_SCHEMA))

    def migrate_state(self, state):
        self.fixture(state)
        before = raw_legacy(self.lock.database_path)
        RuntimeStore.migrate_v1_to_v2(self.lock, self.config)
        after = raw_legacy(self.lock.database_path)
        expected = {table: tuple(dict(row) for row in rows) for table, rows in before.items()}
        expected["identity"][0].update(schema_version=2, configuration_digest=self.config.configuration_digest)
        self.assertEqual(after, expected)
        with RuntimeStore.open(self.lock, self.config) as store:
            self.assertEqual(store.get_checkpoint().sequence, 17)
            self.assertEqual(store.get_checkpoint().snapshot.state, state)
            self.assertEqual(store.list_risk_valuations(), ())
            for table in module._RISK_SCHEMA:
                self.assertEqual(store._connection.execute("SELECT count(*) FROM " + table).fetchone()[0], 0)
            self.assertEqual(store._connection.execute("PRAGMA user_version").fetchone()[0], 2)

    def test_migrate_flat(self):
        self.migrate_state(RuntimeState.FLAT)

    def test_migrate_long(self):
        self.migrate_state(RuntimeState.LONG)

    def test_migrate_order_pending(self):
        self.migrate_state(RuntimeState.ORDER_PENDING)

    def test_migrate_uncertain(self):
        self.migrate_state(RuntimeState.UNCERTAIN)

    def test_migrate_halted(self):
        self.migrate_state(RuntimeState.HALTED)

    def test_migrate_stopping(self):
        self.migrate_state(RuntimeState.STOPPING)

    def test_raw_decimal_text_and_consumed_ids_survive(self):
        self.migrate_state(RuntimeState.LONG)
        with sqlite3.connect(self.lock.database_path) as connection:
            self.assertEqual(connection.execute("SELECT executed_quantity,execution_price,execution_fee FROM fills").fetchone(),
                             ("0.00000001", "123456789.123456789", "-0.00001"))
            self.assertEqual(connection.execute("SELECT logical_action_id,order_link_id FROM actions").fetchone(),
                             (ACTION_ID, "bot1-" + ACTION_ID[:23]))

    def test_normal_open_requires_explicit_migration_without_byte_changes(self):
        self.fixture()
        before = self.lock.database_path.read_bytes()
        with self.assertRaises(RuntimeStoreMigrationRequiredError) as caught:
            RuntimeStore.open(self.lock, self.config)
        self.assertIsInstance(caught.exception, RuntimeStoreIntegrityError)
        self.assertEqual(str(caught.exception), "Explicit runtime schema v1 to v2 migration is required.")
        self.assertEqual(self.lock.database_path.read_bytes(), before)

    def test_literal_legacy_schema_matches_frozen_definition(self):
        self.assertEqual(LEGACY_V1_SCHEMA, module._SCHEMA_V1)
        self.assertEqual(LEGACY_V1_INDEXES, module._INDEXES_V1)
        self.assertEqual(set(module._SCHEMA), set(LEGACY_V1_SCHEMA) | set(module._RISK_SCHEMA))

    def test_missing_database_is_not_created(self):
        with self.assertRaises(RuntimeStoreError):
            RuntimeStore.migrate_v1_to_v2(self.lock, configuration())
        self.assertFalse(self.lock.database_path.exists())

    def test_unheld_lock_is_refused(self):
        self.fixture()
        unheld = RuntimeAccountLock(Path(self.directory), "research")
        with self.assertRaises(RuntimeLockError):
            RuntimeStore.migrate_v1_to_v2(unheld, self.config)

    def test_wrong_lock_binding_is_refused(self):
        self.fixture()
        other = self.enterContext(RuntimeAccountLock(Path(self.directory), "other"))
        with self.assertRaises(RuntimeStoreConflictError):
            RuntimeStore.migrate_v1_to_v2(other, self.config)
        self.assertFalse(other.database_path.exists())

    def test_open_store_exclusion_and_close_cleanup(self):
        store = RuntimeStore.open(self.lock, configuration(), initialize=True)
        try:
            self.assertEqual(module._OPEN_DATABASES[self.lock.database_path], 1)
            with self.assertRaisesRegex(RuntimeStoreConflictError, "no open store"):
                RuntimeStore.migrate_v1_to_v2(self.lock, configuration())
        finally:
            store.close()
        self.assertNotIn(self.lock.database_path, module._OPEN_DATABASES)
        with self.assertRaisesRegex(RuntimeStoreIntegrityError, "legacy v1"):
            RuntimeStore.migrate_v1_to_v2(self.lock, configuration())

    def test_close_one_of_two_handles_still_excludes_migration(self):
        first = RuntimeStore.open(self.lock, configuration(), initialize=True)
        second = RuntimeStore.open(self.lock, configuration())
        first.close()
        try:
            self.assertEqual(module._OPEN_DATABASES[self.lock.database_path], 1)
            with self.assertRaises(RuntimeStoreConflictError):
                RuntimeStore.migrate_v1_to_v2(self.lock, configuration())
        finally:
            second.close()
        self.assertNotIn(self.lock.database_path, module._OPEN_DATABASES)

    def test_symlink_database_is_not_followed(self):
        self.fixture()
        original = self.lock.database_path.with_name("original.sqlite3")
        self.lock.database_path.rename(original)
        before = original.read_bytes()
        self.lock.database_path.symlink_to(original)
        with self.assertRaises(RuntimeStoreError):
            RuntimeStore.migrate_v1_to_v2(self.lock, self.config)
        self.assertEqual(original.read_bytes(), before)

    def test_nonregular_database_is_refused(self):
        self.lock.database_path.mkdir(parents=True)
        with self.assertRaises(RuntimeStoreError):
            RuntimeStore.migrate_v1_to_v2(self.lock, configuration())
        self.assertTrue(self.lock.database_path.is_dir())

    def refuse_corruption(self, sql, args=()):
        self.fixture()
        with sqlite3.connect(self.lock.database_path) as connection:
            connection.execute(sql, args)
        before = self.lock.database_path.read_bytes()
        with self.assertRaises(RuntimeStoreError):
            RuntimeStore.migrate_v1_to_v2(self.lock, self.config)
        self.assertEqual(self.lock.database_path.read_bytes(), before)

    def test_unknown_version_is_refused(self):
        self.refuse_corruption("PRAGMA user_version=7")

    def test_wrong_index_is_refused(self):
        self.refuse_corruption("DROP INDEX one_pending_cancel")

    def test_partial_risk_schema_is_refused(self):
        self.refuse_corruption(module._RISK_SCHEMA["risk_configurations"])

    def test_malformed_schema_is_refused(self):
        self.refuse_corruption("ALTER TABLE candles ADD COLUMN unexpected TEXT")

    def test_malformed_source_decimal_is_refused(self):
        self.refuse_corruption("UPDATE candles SET volume='1e-8'")

    def test_malformed_source_contract_is_refused(self):
        self.refuse_corruption("UPDATE identity SET runtime_contract_version=2")

    def test_broken_source_foreign_key_is_refused(self):
        self.refuse_corruption("UPDATE checkpoint SET pending_action_id=?", ("f"*64,))

    def test_source_configuration_mismatches_are_never_adjusted(self):
        self.fixture()
        before = raw_legacy(self.lock.database_path)
        for changes in ({"buy_quote_budget":D(11)}, {"bot_id":"bot2"},
                        {"strategy_implementation_digest":"f"*64}, {"history_anchor_ms":HOUR},
                        {"symbol":"ETHUSDT", "base_currency":"ETH"}, {"broker_account_id":"different"}):
            with self.subTest(changes=changes), self.assertRaises(RuntimeStoreError):
                RuntimeStore.migrate_v1_to_v2(self.lock, replace(self.config, **changes))
        self.assert_legacy(before)

    def test_fault_before_transaction_preserves_v1(self):
        self.fixture()
        before = raw_legacy(self.lock.database_path)
        with patch.object(RuntimeStore, "_validate_v1", side_effect=RuntimeStoreIntegrityError("Injected")), self.assertRaises(RuntimeStoreError):
            RuntimeStore.migrate_v1_to_v2(self.lock, self.config)
        self.assert_legacy(before)

    def migration_fault(self, predicate, *, after=False):
        self.fixture()
        before = raw_legacy(self.lock.database_path)
        connect = sqlite3.connect
        class FaultConnection(sqlite3.Connection):
            def execute(inner, sql, *args):
                if predicate(sql):
                    if after:
                        super(FaultConnection, inner).execute(sql, *args)
                    raise sqlite3.OperationalError("Injected private SQL failure")
                return super(FaultConnection, inner).execute(sql, *args)
        def wrapped(*args, **kwargs):
            return connect(*args, factory=FaultConnection, **kwargs)
        with patch.object(module.sqlite3, "connect", side_effect=wrapped), self.assertRaises(RuntimeStoreError) as caught:
            RuntimeStore.migrate_v1_to_v2(self.lock, self.config)
        self.assertNotIn("private", str(caught.exception))
        self.assert_legacy(before)

    def test_fault_after_first_table_rolls_back(self):
        self.migration_fault(lambda sql: sql.startswith("CREATE TABLE risk_epochs"))

    def test_fault_after_all_tables_rolls_back(self):
        self.migration_fault(lambda sql: sql.startswith("UPDATE identity"))

    def test_fault_after_identity_before_version_rolls_back(self):
        self.migration_fault(lambda sql: sql == "PRAGMA user_version=2")

    def test_fault_before_commit_rolls_back(self):
        self.migration_fault(lambda sql: sql == "COMMIT")

    def test_commit_then_error_requires_reopen_without_retry(self):
        self.fixture()
        commit = RuntimeStore._commit
        calls = []
        def committed(store):
            calls.append(1)
            commit(store)
            raise sqlite3.OperationalError("Injected lost commit return")
        with patch.object(RuntimeStore, "_commit", committed), self.assertRaisesRegex(RuntimeStoreError, "reopening"):
            RuntimeStore.migrate_v1_to_v2(self.lock, self.config)
        self.assertEqual(calls, [1])
        with RuntimeStore.open(self.lock, self.config) as store:
            self.assertIsNone(store.get_current_risk_epoch())
        self.assertNotIn(self.lock.database_path, module._OPEN_DATABASES)

    def test_post_commit_validation_error_does_not_claim_v1(self):
        self.fixture()
        with patch.object(RuntimeStore, "open", side_effect=RuntimeStoreIntegrityError("Injected")), self.assertRaisesRegex(RuntimeStoreError, "Post-commit"):
            RuntimeStore.migrate_v1_to_v2(self.lock, self.config)
        with RuntimeStore.open(self.lock, self.config) as store:
            self.assertEqual(store.get_configuration().schema_version, 2)


    def test_rollback_failure_closes_and_requires_outcome_inspection(self):
        self.fixture()
        before=raw_legacy(self.lock.database_path)
        connect=sqlite3.connect
        class FaultConnection(sqlite3.Connection):
            def execute(inner,sql,*args):
                if sql.startswith("UPDATE identity") or sql=="ROLLBACK":
                    raise sqlite3.OperationalError("Injected uncertain rollback")
                return super(FaultConnection,inner).execute(sql,*args)
        def wrapped(*args,**kwargs):
            return connect(*args,factory=FaultConnection,**kwargs)
        with patch.object(module.sqlite3,"connect",side_effect=wrapped),self.assertRaisesRegex(RuntimeStoreError,"reopening"):
            RuntimeStore.migrate_v1_to_v2(self.lock,self.config)
        self.assert_legacy(before)
        self.assertEqual(self.lock._stores,0)

    def test_source_is_revalidated_after_begin(self):
        self.fixture()
        before=raw_legacy(self.lock.database_path)
        validate=RuntimeStore._validate_v1
        count=[]
        def checked(store):
            count.append(store._connection.in_transaction)
            if len(count)==2:
                raise RuntimeStoreIntegrityError("Injected changed source")
            return validate(store)
        with patch.object(RuntimeStore,"_validate_v1",checked),self.assertRaises(RuntimeStoreError):
            RuntimeStore.migrate_v1_to_v2(self.lock,self.config)
        self.assertEqual(count,[False,True])
        self.assert_legacy(before)

    def test_hardlinked_database_is_refused(self):
        import os
        self.fixture()
        os.link(self.lock.database_path,self.lock.database_path.with_name("alias.sqlite3"))
        before=self.lock.database_path.read_bytes()
        with self.assertRaises(RuntimeStoreError):
            RuntimeStore.migrate_v1_to_v2(self.lock,self.config)
        self.assertEqual(self.lock.database_path.read_bytes(),before)

    def test_legacy_source_strategy_id_is_not_repaired(self):
        self.refuse_corruption("UPDATE identity SET strategy_id='different'")

    def test_legacy_source_version_identity_mismatch_is_refused(self):
        self.refuse_corruption("UPDATE identity SET schema_version=2")

    def test_legacy_source_invalid_digest_is_refused(self):
        self.refuse_corruption("UPDATE identity SET configuration_digest='invalid'")

    def test_legacy_source_bad_fk_definition_is_refused(self):
        # Literal malformed legacy DDL, not v2 with tables removed.
        self.lock.database_path.parent.mkdir(parents=True)
        with sqlite3.connect(self.lock.database_path) as connection:
            for name,sql in LEGACY_V1_SCHEMA.items():
                connection.execute(sql.replace("REFERENCES actions(logical_action_id)","REFERENCES candles(candle_open_ms)") if name=="checkpoint" else sql)
            for sql in LEGACY_V1_INDEXES.values():
                connection.execute(sql)
            connection.execute("PRAGMA user_version=1")
        before=self.lock.database_path.read_bytes()
        with self.assertRaises(RuntimeStoreError):
            RuntimeStore.migrate_v1_to_v2(self.lock,configuration())
        self.assertEqual(self.lock.database_path.read_bytes(),before)

    def test_legacy_wal_is_refused_before_settings_change(self):
        self.fixture()
        with sqlite3.connect(self.lock.database_path) as connection:
            connection.execute("PRAGMA journal_mode=WAL")
        before=self.lock.database_path.read_bytes()
        with self.assertRaises(RuntimeStoreError):
            RuntimeStore.migrate_v1_to_v2(self.lock,self.config)
        self.assertEqual(self.lock.database_path.read_bytes(),before)

    def test_already_v2_is_not_migrated_twice(self):
        self.fixture()
        RuntimeStore.migrate_v1_to_v2(self.lock,self.config)
        before=self.lock.database_path.read_bytes()
        with self.assertRaises(RuntimeStoreError):
            RuntimeStore.migrate_v1_to_v2(self.lock,self.config)
        self.assertEqual(self.lock.database_path.read_bytes(),before)


class RiskPersistenceCase(StoreCase):
    def commit_candle(self, at=0, close="105.25"):
        current = self.store.get_checkpoint()
        last = current.last_processed_candle_ms
        for time in range(0 if last is None else last+HOUR, at+1, HOUR):
            value = D(close)
            c = replace(candle(time), open=value, high=value, low=value, close=value)
            desired = self.store.get_checkpoint().snapshot.desired_position or 0
            d = replace(decision(time), desired_position=desired)
            cp = self.next_checkpoint(last_processed_candle_ms=time, snapshot=replace(self.store.get_checkpoint().snapshot, desired_position=desired))
            self.store.commit_decision(c, d, cp, expected_sequence=cp.sequence-1)

    def activate(self, at=0, cfg=None, close="105.25"):
        self.flat()
        self.commit_candle(at, close)
        return self.store.initialize_risk_journal(cfg or risk_configuration(), candle_open_ms=at)

    def long_activation(self, *, fee="0", currency=None, at=HOUR, close="105.25", cfg=None):
        action = self.acknowledge()
        execution = replace(fill(), executed_quantity=D(1), execution_price=D(100),
                            execution_fee=D(fee), fee_currency=currency)
        book = module._risk_book(cfg or risk_configuration(), (execution,))
        cp = self.next_checkpoint(snapshot=RuntimeStateSnapshot(RuntimeState.LONG, book.owned_base_quantity, PositionEvidence.CONFIRMED, 1))
        self.store.record_observation(terminal(action), cp, expected_sequence=cp.sequence-1, fills=(execution,))
        self.commit_candle(at, close)
        return self.store.initialize_risk_journal(cfg or risk_configuration(), candle_open_ms=at)

    def risk_rows(self):
        return {table: tuple(tuple(row) for row in self.store._connection.execute("SELECT * FROM " + table + " ORDER BY rowid"))
                for table in module._RISK_SCHEMA}


class RiskActivationTests(RiskPersistenceCase):
    def test_flat_activation_is_exact_pure_initializer(self):
        before_cp = None
        self.flat()
        self.commit_candle()
        before_cp = self.store.get_checkpoint()
        valuation = self.store.initialize_risk_journal(risk_configuration(), candle_open_ms=0)
        self.assertIs(valuation.mode, RiskValuationMode.ACTIVATION)
        self.assertEqual(valuation.book, RiskBook(D(1000), D(0)))
        self.assertEqual(valuation.state(HOUR), initialize_risk_state(risk_configuration(), valuation.book, candle().close, HOUR))
        self.assertEqual(self.store.get_checkpoint(), before_cp)
        self.assertEqual(self.store.list_actions(), ())
        self.assertEqual(self.store.list_risk_verdicts(), ())

    def test_long_activation_uses_retained_owned_fill_history(self):
        valuation = self.long_activation()
        self.assertEqual(valuation.book, RiskBook(D(900), D(1)))
        self.assertEqual(valuation.risk_equity, D("1005.25"))
        self.assertEqual(valuation.fill_evidence_count, 1)
        self.reopen()
        self.assertEqual(self.store.get_latest_risk_valuation(), valuation)

    def test_quote_fee_changes_only_cash(self):
        self.assertEqual(self.long_activation(fee="1.25", currency="USDT").book, RiskBook(D("898.75"), D(1)))

    def test_base_fee_changes_only_base(self):
        self.assertEqual(self.long_activation(fee="0.01", currency="BTC").book, RiskBook(D(900), D("0.99")))

    def test_quote_rebate_is_preserved(self):
        self.assertEqual(self.long_activation(fee="-1.25", currency="USDT").book, RiskBook(D("901.25"), D(1)))

    def test_base_rebate_is_preserved(self):
        self.assertEqual(self.long_activation(fee="-0.01", currency="BTC").book, RiskBook(D(900), D("1.01")))

    def test_exact_durable_close_is_the_only_mark(self):
        valuation = self.activate(close="123.4567890123456789012345678901")
        self.assertEqual(valuation.mark_price, self.store.get_candle(0).close)
        self.assertEqual(valuation.valued_at_ms, HOUR)

    def test_midnight_activation_anchors_current_equity(self):
        value = self.activate(23*HOUR)
        self.assertEqual(value.utc_day_start_ms, 24*HOUR)
        self.assertEqual(value.utc_day_start_risk_equity, D(1000))
        self.assertEqual(value.daily_pnl, 0)

    def test_identical_activation_is_error_not_noop(self):
        self.activate()
        before = self.risk_rows()
        with self.assertRaises(RuntimeStoreError):
            self.store.initialize_risk_journal(risk_configuration(), candle_open_ms=0)
        self.assertEqual(self.risk_rows(), before)

    def test_conflicting_activation_is_error(self):
        self.activate()
        before = self.risk_rows()
        with self.assertRaises(RuntimeStoreError):
            self.store.initialize_risk_journal(risk_configuration(risk_capital_quote=D(2000)), candle_open_ms=0)
        self.assertEqual(self.risk_rows(), before)

    def test_failure_after_configuration_insert_rolls_back_all_risk_rows(self):
        self.flat()
        self.commit_candle()
        before = self.risk_rows()
        insert = self.store._insert
        def failed(table, values):
            if table == "risk_epochs":
                raise RuntimeStoreError("Injected")
            insert(table, values)
        with patch.object(self.store, "_insert", side_effect=failed), self.assertRaises(RuntimeStoreError):
            self.store.initialize_risk_journal(risk_configuration(), candle_open_ms=0)
        self.assertEqual(self.risk_rows(), before)
        self.reopen()
        self.assertIsNone(self.store.get_risk_configuration())

    def test_activation_commit_failure_rolls_back(self):
        self.flat()
        self.commit_candle()
        with patch.object(self.store, "_commit", side_effect=sqlite3.OperationalError("Injected")), self.assertRaises(RuntimeStoreError):
            self.store.initialize_risk_journal(risk_configuration(), candle_open_ms=0)
        self.reopen()
        self.assertEqual(self.store.list_risk_valuations(), ())

    def test_unsafe_states_and_nonconfirmed_evidence_are_rejected(self):
        # Use each legitimate frozen state rather than constructing impossible
        # CONFIRMED/FLAT or LAST_KNOWN/operational combinations.
        snapshots = [RuntimeStateSnapshot(), RuntimeStateSnapshot(RuntimeState.SYNCHRONIZING),
            RuntimeStateSnapshot(RuntimeState.SYNCHRONIZING,D(0),PositionEvidence.LAST_KNOWN),
            RuntimeStateSnapshot(RuntimeState.UNCERTAIN,reason=RuntimeReason.EVIDENCE_MISSING),
            RuntimeStateSnapshot(RuntimeState.HALTED,reason=RuntimeReason.INVALID_CONFIGURATION),
            RuntimeStateSnapshot(RuntimeState.STOPPING,stopped_from=RuntimeState.STARTING)]
        self.commit_candle()
        for snapshot in snapshots:
            cp = self.next_checkpoint(snapshot=replace(snapshot,desired_position=0),
                halted_at_ms=1 if snapshot.state is RuntimeState.HALTED else None,
                shutdown_at_ms=1 if snapshot.state is RuntimeState.STOPPING else None)
            # Fresh isolated checkpoint fixtures avoid the public HALT latch.
            self.store._update("checkpoint", module._checkpoint_values(cp), "singleton", 1)
            before = self.risk_rows()
            with self.subTest(state=snapshot.state), self.assertRaises(RuntimeStoreError):
                self.store.initialize_risk_journal(risk_configuration(), candle_open_ms=0)
            self.assertEqual(self.risk_rows(), before)

    def test_pending_action_refuses_activation(self):
        self.prepare()
        with self.assertRaises(RuntimeStoreError):
            self.store.initialize_risk_journal(risk_configuration(), candle_open_ms=0)
        self.assertEqual(self.store.list_risk_valuations(), ())

    def test_missing_candle_refuses_without_writes(self):
        self.flat()
        with self.assertRaises(RuntimeStoreError):
            self.store.initialize_risk_journal(risk_configuration(), candle_open_ms=0)
        self.assertEqual(self.store.list_risk_valuations(), ())

    def test_wrong_budget_or_currencies_refuse_without_writes(self):
        self.flat()
        self.commit_candle()
        for changes in ({"buy_quote_budget":D(11)}, {"base_currency":"ETH"}, {"quote_currency":"USDC"}):
            with self.subTest(changes=changes), self.assertRaises(RuntimeStoreError):
                self.store.initialize_risk_journal(risk_configuration(**changes), candle_open_ms=0)
        self.assertEqual(self.store.list_risk_valuations(), ())

    def test_inventory_mismatch_is_not_adopted(self):
        self.flat()
        self.commit_candle()
        cp = self.next_checkpoint(snapshot=RuntimeStateSnapshot(RuntimeState.LONG,D(1),PositionEvidence.CONFIRMED,0))
        self.store.save_checkpoint(cp,expected_sequence=cp.sequence-1)
        with self.assertRaises(RuntimeStoreError):
            self.store.initialize_risk_journal(risk_configuration(), candle_open_ms=0)
        self.assertEqual(self.store.list_risk_valuations(), ())

    def test_future_execution_cannot_be_applied_at_historical_activation(self):
        action = self.acknowledge()
        self.settle(action,fill())
        with self.assertRaises(RuntimeStoreError):
            self.store.initialize_risk_journal(risk_configuration(), candle_open_ms=0)
        self.assertEqual(self.store.list_risk_valuations(), ())

    def test_unsupported_fee_currency_cannot_be_priced(self):
        action = self.acknowledge()
        execution = replace(fill(),execution_fee=D("0.01"),fee_currency="BNB")
        self.settle(action,execution)
        self.commit_candle(HOUR)
        with self.assertRaises(RuntimeStoreError):
            self.store.initialize_risk_journal(risk_configuration(),candle_open_ms=HOUR)
        self.assertEqual(self.store.list_risk_valuations(), ())

    def test_partial_existing_journal_is_not_repaired(self):
        self.flat()
        self.commit_candle()
        self.store._insert("risk_configurations",module._encode(module._risk_configuration_record(risk_configuration())))
        before = self.risk_rows()
        with self.assertRaises(RuntimeStoreError):
            self.store.initialize_risk_journal(risk_configuration(),candle_open_ms=0)
        self.assertEqual(self.risk_rows(),before)


class RiskReplayTests(RiskPersistenceCase):
    def replay(self, at, close="105.25"):
        self.commit_candle(at,close)
        return self.store.append_risk_replay_valuation(candle_open_ms=at)

    def pending_buy(self):
        current = self.store.get_checkpoint()
        action = replace(prepared(),candle_open_ms=HOUR,reconciliation_deadline_ms=2*HOUR+600000)
        pending = PendingAction(ACTION_ID,PendingActionKind.ENTRY)
        cp = self.next_checkpoint(last_processed_candle_ms=HOUR,
            snapshot=RuntimeStateSnapshot(RuntimeState.ORDER_PENDING,D(0),PositionEvidence.CONFIRMED,1,pending))
        self.store.commit_decision(candle(HOUR),decision(HOUR,action=True),cp,expected_sequence=current.sequence,action=action)
        self.store.start_attempt(ACTION_ID,self.next_checkpoint(),expected_sequence=cp.sequence)
        action = receipt(self.store.get_action(ACTION_ID))
        action = replace(action,acknowledgement_broker_ms=2*HOUR,acknowledgement_observed_ms=2*HOUR+1)
        cp=self.next_checkpoint()
        self.store.record_observation(action,cp,expected_sequence=cp.sequence-1)
        return action

    def observe_fill(self, action, *, at=2*HOUR, fee="0", currency=None, execution_id="risk-fill"):
        execution = replace(fill(execution_id), executed_at_ms=at,observed_at_ms=at+10,
            executed_quantity=D(1),execution_price=D(100),execution_fee=D(fee),fee_currency=currency)
        observed = replace(action,order_status="PARTIALLY_FILLED",observed_at_ms=at+10)
        cp = self.next_checkpoint(snapshot=replace(self.store.get_checkpoint().snapshot,
            owned_base_quantity=module._risk_book(risk_configuration(),(execution,)).owned_base_quantity))
        self.store.record_observation(observed,cp,expected_sequence=cp.sequence-1,fills=(execution,))
        return execution

    def test_exact_next_hour_uses_pure_advance(self):
        first=self.activate()
        cp=self.store.get_checkpoint()
        self.assertTrue(self.replay(HOUR,"101"))
        latest=self.store.get_latest_risk_valuation()
        self.assertEqual(latest.state(HOUR),advance_risk_state(risk_configuration(),first.state(HOUR),first.book,D(101),2*HOUR))
        self.assertEqual(self.store.get_checkpoint().sequence,cp.sequence+1)  # candle commit only
        self.assertIs(latest.mode,RiskValuationMode.REPLAY_ONLY)
        self.assertEqual(self.store.list_risk_verdicts(),())

    def test_many_hours_reopen_in_deterministic_order(self):
        self.activate()
        for hour in range(1,27):
            self.replay(hour*HOUR)
        self.reopen()
        rows=self.store.list_risk_valuations()
        self.assertEqual([row.valued_at_ms for row in rows],list(range(HOUR,28*HOUR,HOUR)))
        self.assertEqual(rows[-1].utc_day_start_ms,24*HOUR)
        self.assertEqual(rows[-1].entries_this_utc_day,0)

    def test_midnight_checks_outgoing_loss_before_reset(self):
        self.long_activation(at=22*HOUR,close="200")
        self.replay(23*HOUR,"100")
        row=self.store.get_latest_risk_valuation()
        self.assertIs(row.trip_reason,RiskReason.DAILY_LOSS_LIMIT)
        self.assertEqual(row.utc_day_start_risk_equity,D(1000))
        self.assertEqual(row.daily_pnl,0)
        self.assertEqual(row.tripped_at_ms,24*HOUR)

    def test_daily_loss_latch_and_notification_survive_recovery(self):
        self.long_activation(close="200")
        self.replay(2*HOUR,"100")
        row=self.store.get_latest_risk_valuation()
        self.assertIs(row.trip_reason,RiskReason.DAILY_LOSS_LIMIT)
        self.assertTrue(row.trip_pending_report)
        self.replay(3*HOUR,"250")
        self.reopen()
        latest=self.store.get_latest_risk_valuation()
        self.assertEqual((latest.trip_reason,latest.tripped_at_ms,latest.trip_pending_report),
                         (row.trip_reason,row.tripped_at_ms,True))
        self.assertEqual(latest.peak_risk_equity,D(1150))

    def test_drawdown_latch_uses_epoch_peak(self):
        cfg=risk_configuration(max_daily_loss_fraction=D(1),max_drawdown_fraction=D("0.05"))
        self.long_activation(cfg=cfg,close="200")
        self.replay(2*HOUR,"140")
        self.assertIs(self.store.get_latest_risk_valuation().trip_reason,RiskReason.MAX_DRAWDOWN)

    def test_quote_fill_at_exact_boundary_is_included_once(self):
        first=self.activate()
        action=self.pending_buy()
        execution=self.observe_fill(action,fee="1.25",currency="USDT")
        self.store.append_risk_replay_valuation(candle_open_ms=HOUR)
        row=self.store.get_latest_risk_valuation()
        self.assertEqual(row.book,RiskBook(D("898.75"),D(1)))
        self.assertEqual(row.fill_evidence_count,1)
        self.assertEqual(self.store.list_risk_valuations()[0],first)
        self.assertEqual(self.store.list_fills(),(execution,))

    def test_base_fee_between_boundaries_affects_owned_quantity(self):
        self.activate()
        action=self.pending_buy()
        self.observe_fill(action,at=2*HOUR+500,fee="0.01",currency="BTC")
        self.store.append_risk_replay_valuation(candle_open_ms=HOUR)
        self.replay(2*HOUR)
        self.assertEqual(self.store.get_latest_risk_valuation().book,RiskBook(D(900),D("0.99")))

    def test_future_fill_is_not_retroactively_selected(self):
        self.activate()
        action=self.pending_buy()
        self.observe_fill(action,at=2*HOUR+1)
        self.store.append_risk_replay_valuation(candle_open_ms=HOUR)
        self.assertEqual(self.store.get_latest_risk_valuation().book,RiskBook(D(1000),D(0)))
        self.replay(2*HOUR)
        self.assertEqual(self.store.get_latest_risk_valuation().book,RiskBook(D(900),D(1)))

    def test_identical_retry_is_noop_for_every_record(self):
        self.activate()
        self.replay(HOUR)
        before=self.risk_rows(),self.store.get_checkpoint(),self.lock.database_path.read_bytes()
        self.assertFalse(self.store.append_risk_replay_valuation(candle_open_ms=HOUR))
        self.assertEqual((self.risk_rows(),self.store.get_checkpoint(),self.lock.database_path.read_bytes()),before)

    def test_old_identical_replay_retry_is_safe(self):
        self.activate()
        self.replay(HOUR)
        self.replay(2*HOUR)
        self.assertFalse(self.store.append_risk_replay_valuation(candle_open_ms=HOUR))
        self.assertEqual(len(self.store.list_risk_valuations()),3)

    def test_gap_and_activation_backwards_are_errors(self):
        self.activate()
        self.commit_candle(2*HOUR)
        before=self.risk_rows()
        for at in (0,2*HOUR):
            with self.subTest(at=at),self.assertRaises(RuntimeStoreError):
                self.store.append_risk_replay_valuation(candle_open_ms=at)
        self.assertEqual(self.risk_rows(),before)

    def test_replay_requires_explicit_activation(self):
        self.flat()
        self.commit_candle()
        with self.assertRaises(RuntimeStoreError):
            self.store.append_risk_replay_valuation(candle_open_ms=0)
        self.assertEqual(self.store.list_risk_valuations(),())

    def test_missing_next_candle_cannot_be_fabricated(self):
        self.activate()
        with self.assertRaises(RuntimeStoreError):
            self.store.append_risk_replay_valuation(candle_open_ms=HOUR)
        self.assertEqual(len(self.store.list_risk_valuations()),1)

    def test_late_fill_blocks_successor_but_old_history_remains_readable(self):
        self.activate()
        action=self.pending_buy()
        self.store.append_risk_replay_valuation(candle_open_ms=HOUR)
        previous=self.store.get_latest_risk_valuation()
        # The original unresolved BUY legitimately reports a fill at the already
        # valued boundary later. No terminal action is illegally amended.
        self.observe_fill(action,at=2*HOUR)
        self.reopen()
        self.assertEqual(self.store.get_latest_risk_valuation(),previous)
        self.commit_candle(2*HOUR)
        before=self.risk_rows()
        with self.assertRaisesRegex(RuntimeStoreConflictError,"Predecessor"):
            self.store.append_risk_replay_valuation(candle_open_ms=2*HOUR)
        self.assertEqual(self.risk_rows(),before)
        self.assertEqual(self.store.get_latest_risk_valuation(),previous)

    def test_changed_evidence_conflicts_with_existing_retry(self):
        self.activate()
        action=self.pending_buy()
        self.store.append_risk_replay_valuation(candle_open_ms=HOUR)
        self.observe_fill(action)
        before=self.risk_rows()
        with self.assertRaisesRegex(RuntimeStoreConflictError,"Conflicting"):
            self.store.append_risk_replay_valuation(candle_open_ms=HOUR)
        self.assertEqual(self.risk_rows(),before)

    def test_replay_failure_rolls_back_without_frontier_mutation(self):
        self.activate()
        self.commit_candle(HOUR)
        cp=self.store.get_checkpoint()
        before=self.risk_rows()
        with patch.object(self.store,"_commit",side_effect=sqlite3.OperationalError("Injected")),self.assertRaises(RuntimeStoreError):
            self.store.append_risk_replay_valuation(candle_open_ms=HOUR)
        self.assertEqual(self.store.get_checkpoint(),cp)
        self.assertEqual(self.risk_rows(),before)


class RiskRecordAndDigestTests(unittest.TestCase):
    def test_configuration_fixed_digest_vector(self):
        record=module._risk_configuration_record(risk_configuration())
        self.assertEqual(record.risk_configuration_digest,"f22668a2947f845ca177a5d56094cc6d7aed5f14c92bd6a8c56290e592cbe880")
        self.assertEqual(record.configuration,risk_configuration())

    def test_epoch_fixed_digest_vector(self):
        record=module._initial_risk_epoch(module._risk_configuration_record(risk_configuration()),HOUR)
        self.assertEqual(record.epoch_id,"9aab0ab1f9594c5c60180df15483f2bbadda8f8313e913a9b38718131fd3f9bc")
        self.assertEqual((record.epoch_sequence,record.parent_epoch_id),(1,None))

    def test_empty_evidence_fixed_digest_vector(self):
        selected,evidence=module._fill_evidence((),HOUR)
        self.assertEqual(selected,())
        self.assertEqual(evidence,(0,"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945"))

    def test_nonempty_evidence_fixed_digest_vector(self):
        _,evidence=module._fill_evidence((fill(),),2*HOUR)
        self.assertEqual(evidence,(1,"9f3de7a0e21902667861bfbfdc05d6e4a5bbb5376eee0f567e0cff4b8dd49e36"))

    def test_equivalent_decimals_produce_same_configuration_digest(self):
        first=module._risk_configuration_record(risk_configuration())
        second=module._risk_configuration_record(risk_configuration(risk_capital_quote=D("1000.000"),max_daily_loss_fraction=D("0.10000")))
        self.assertEqual(first,second)

    def test_every_policy_field_changes_digest(self):
        first=module._risk_configuration_record(risk_configuration())
        changes={"risk_capital_quote":D(1001),"buy_quote_budget":D(11),"max_entry_notional_quote":D(201),
            "max_position_notional_quote":D(501),"max_daily_loss_fraction":D("0.11"),
            "max_drawdown_fraction":D("0.21"),"max_entries_per_utc_day":3,"base_currency":"ETH","quote_currency":"USDC"}
        for key,value in changes.items():
            with self.subTest(key=key):
                self.assertNotEqual(module._risk_configuration_record(risk_configuration(**{key:value})).risk_configuration_digest,first.risk_configuration_digest)

    def test_tampered_configuration_or_unknown_contract_fails(self):
        record=module._risk_configuration_record(risk_configuration())
        for changes in ({"risk_configuration_digest":"f"*64},{"risk_capital_quote":D(1001)},
                        {"risk_contract_version":2},{"risk_contract_version":True},{"max_entries_per_utc_day":2**63}):
            with self.subTest(changes=changes),self.assertRaises(RuntimeStoreError):
                replace(record,**changes)

    def test_epoch_digest_sequence_and_parent_are_validated(self):
        record=module._initial_risk_epoch(module._risk_configuration_record(risk_configuration()),HOUR)
        for changes in ({"epoch_id":"f"*64},{"epoch_sequence":True},{"epoch_sequence":0},
                        {"started_at_ms":1},{"parent_epoch_id":"e"*64},{"epoch_sequence":2}):
            with self.subTest(changes=changes),self.assertRaises(RuntimeStoreError):
                replace(record,**changes)

    def test_evidence_sort_cutoff_and_all_owned_fields(self):
        a=replace(fill("a"),executed_at_ms=HOUR)
        z=replace(fill("z"),executed_at_ms=HOUR)
        future=replace(fill("future"),executed_at_ms=HOUR+1)
        selected,evidence=module._fill_evidence((z,future,a),HOUR)
        self.assertEqual(selected,(a,z))
        self.assertEqual(evidence,module._fill_evidence((a,z),HOUR)[1])
        for field in fields(a):
            if field.name in ("executed_at_ms","observed_at_ms"):
                value=HOUR-1
            elif field.name in ("executed_quantity","execution_price","execution_fee"):
                value=D("1.25")
            elif field.name=="side":
                value="SELL"
            elif field.name=="action_id":
                value="e"*64
            elif field.name=="broker_id":
                continue  # Demo-only field cannot take another valid value.
            else:
                value="USDT" if field.name=="fee_currency" else "changed"
            changed=replace(a,**{field.name:value})
            with self.subTest(field=field.name):
                self.assertNotEqual(module._fill_evidence((changed,z),HOUR)[1][1],evidence[1])

    def test_unsafe_configuration_types_are_not_coerced(self):
        for value in (None,{},"policy",True):
            with self.subTest(value=value),self.assertRaises(RuntimeStoreError):
                module._risk_configuration_record(value)

    def test_verdict_shapes_are_explicit_and_strict(self):
        common=dict(symbol="BTCUSDT",timeframe="60",candle_open_ms=0,epoch_id="a"*64,
            valued_at_ms=HOUR,risk_configuration_digest="b"*64,evaluated_at_ms=HOUR)
        variants=[(None,None,RiskVerdict.ALLOW,None,None),
            (RiskActionKind.ENTRY,D(10),RiskVerdict.ALLOW,None,ACTION_ID),
            (RiskActionKind.EXIT,D(1),RiskVerdict.ALLOW,None,ACTION_ID),
            (RiskActionKind.ENTRY,D(10),RiskVerdict.BLOCK,RiskReason.ENTRY_COUNT_LIMIT,None),
            (RiskActionKind.ENTRY,D(10),RiskVerdict.TRIP,RiskReason.DAILY_LOSS_LIMIT,None),
            (None,None,RiskVerdict.TRIP,RiskReason.MAX_DRAWDOWN,None)]
        for kind,amount,verdict,reason,action in variants:
            row=RiskVerdictRecord(**common,proposal_kind=kind,authorized_amount=amount,verdict=verdict,reason=reason,action_id=action)
            self.assertEqual(row.proposal_kind,kind)
        row=RiskVerdictRecord(**common,proposal_kind=None,authorized_amount=None,verdict=RiskVerdict.ALLOW,reason=None,action_id=None)
        for changes in ({"action_id":ACTION_ID},{"proposal_kind":RiskActionKind.ENTRY},
                        {"verdict":"ALLOW"},{"reason":RiskReason.DAILY_LOSS_LIMIT},
                        {"evaluated_at_ms":HOUR-1},{"candle_open_ms":True}):
            with self.subTest(changes=changes),self.assertRaises(RuntimeStoreError):
                replace(row,**changes)

    def test_refused_exit_and_mixed_refusal_reason_are_invalid(self):
        base=RiskVerdictRecord("BTCUSDT","60",0,"a"*64,HOUR,"b"*64,RiskActionKind.ENTRY,D(10),RiskVerdict.BLOCK,RiskReason.ENTRY_COUNT_LIMIT,None,HOUR)
        for changes in ({"proposal_kind":RiskActionKind.EXIT},{"reason":RiskReason.DAILY_LOSS_LIMIT},
                        {"reason":None},{"action_id":ACTION_ID},{"authorized_amount":10.0}):
            with self.subTest(changes=changes),self.assertRaises(RuntimeStoreError):
                replace(base,**changes)


class RiskReadAndBoundaryTests(RiskPersistenceCase):
    def test_empty_read_contract_and_schema_versions(self):
        self.assertEqual((module.SCHEMA_VERSION,module.RUNTIME_CONTRACT_VERSION),(2,1))
        self.assertIsNone(self.store.get_risk_configuration())
        self.assertIsNone(self.store.get_current_risk_epoch())
        self.assertIsNone(self.store.get_latest_risk_valuation())
        self.assertIsNone(self.store.get_risk_verdict(0))
        self.assertEqual(self.store.list_risk_valuations(),())
        self.assertEqual(self.store.list_risk_verdicts(),())
        self.assertEqual(len(module._SCHEMA),10)

    def test_reads_are_immutable_and_do_not_write(self):
        valuation=self.activate()
        records=(valuation,self.store.get_current_risk_epoch(),self.store.get_risk_configuration(),
                 RiskVerdictRecord("BTCUSDT","60",0,"a"*64,HOUR,"b"*64,None,None,RiskVerdict.ALLOW,None,None,HOUR))
        before=self.lock.database_path.read_bytes(),self.store._connection.total_changes
        for record in records:
            self.assertFalse(hasattr(record,"__dict__"))
            with self.assertRaises(FrozenInstanceError):
                setattr(record,fields(record)[0].name,getattr(record,fields(record)[0].name))
        self.assertEqual(self.store.list_risk_valuations(),(valuation,))
        self.assertEqual((self.lock.database_path.read_bytes(),self.store._connection.total_changes),before)

    def test_filters_are_exact_and_empty_unknowns_stay_empty(self):
        row=self.activate()
        self.assertEqual(self.store.list_risk_valuations(row.epoch_id),(row,))
        self.assertEqual(self.store.list_risk_valuations("f"*64),())
        self.assertIsNone(self.store.get_risk_configuration("f"*64))
        for invalid in (True,1,"", "A"*64,"f"*63,{},[]):
            for method in (self.store.list_risk_valuations,self.store.list_risk_verdicts,self.store.get_risk_configuration):
                with self.subTest(method=method.__name__,invalid=invalid),self.assertRaises(RuntimeStoreError):
                    method(invalid)
        for invalid in (True,-1,1,0.0):
            with self.subTest(invalid=invalid),self.assertRaises(RuntimeStoreError):
                self.store.get_risk_verdict(invalid)

    def test_noncanonical_and_nonfinite_risk_money_fail_on_open(self):
        self.activate()
        self.corrupt("UPDATE risk_valuations SET virtual_quote_cash='1000.00'")
        self.reject_reopen()

    def test_configuration_digest_content_corruption_is_not_hidden(self):
        self.activate()
        self.store._connection.execute("UPDATE risk_configurations SET risk_capital_quote='1001'")
        with self.assertRaises(RuntimeStoreError):
            self.store.list_risk_valuations("f"*64)

    def test_mark_mismatch_fails_without_repair(self):
        self.activate()
        self.corrupt("UPDATE risk_valuations SET mark_price='100'")
        self.reject_reopen()

    def test_gap_or_wrong_mode_fails_on_full_load(self):
        self.activate()
        self.corrupt("UPDATE risk_valuations SET mode='REPLAY_ONLY'")
        self.reject_reopen()

    def test_partial_journal_is_invalid_on_open(self):
        self.store._insert("risk_configurations",module._encode(module._risk_configuration_record(risk_configuration())))
        self.store.close()
        self.reject_reopen()

    def test_epoch_or_configuration_binding_mismatch_is_rejected(self):
        self.activate()
        self.corrupt("UPDATE risk_valuations SET risk_configuration_digest=?",("f"*64,))
        self.reject_reopen()

    def test_trip_notification_and_pure_state_tampering_fails(self):
        self.activate()
        self.corrupt("UPDATE risk_valuations SET trip_pending_report=1")
        self.reject_reopen()

    def test_empty_evidence_hash_must_match_empty_vector(self):
        self.activate()
        self.corrupt("UPDATE risk_valuations SET fill_evidence_digest=?",("f"*64,))
        self.reject_reopen()

    def test_risk_tables_are_part_of_row_bounds(self):
        self.activate()
        self.commit_candle(HOUR)
        self.store.append_risk_replay_valuation(candle_open_ms=HOUR)
        # Lower only the risk-validation bound, so filtering cannot truncate.
        with patch.object(module,"_MAX_ROWS",1),self.assertRaises(RuntimeStoreError):
            self.store.list_risk_valuations("f"*64)

    def test_hostile_decimal_context_roundtrips_exactly(self):
        row=self.long_activation(fee="-0.0000000000000000000000000001",currency="USDT")
        with localcontext() as ctx:
            from decimal import Inexact,Rounded,ROUND_UP
            ctx.prec,ctx.Emax,ctx.Emin,ctx.rounding=1,9,-9,ROUND_UP
            ctx.traps[Inexact]=ctx.traps[Rounded]=True
            self.reopen()
            self.assertEqual(self.store.get_latest_risk_valuation(),row)
            self.assertEqual(self.store.get_risk_configuration().configuration,risk_configuration())

    def test_no_public_live_verdict_rearm_or_generic_transaction_writer(self):
        public={name for name in vars(RuntimeStore) if not name.startswith("_")}
        self.assertEqual(public,{"open","migrate_v1_to_v2","durability_settings","get_configuration","get_checkpoint",
            "get_candle","get_decision","get_action","get_fill","list_actions","list_fills","save_checkpoint",
            "commit_decision","prepare_cancellation","start_attempt","abandon_prepared","record_observation","close",
            "get_risk_configuration","get_current_risk_epoch","get_latest_risk_valuation","list_risk_valuations",
            "get_risk_verdict","list_risk_verdicts","initialize_risk_journal","append_risk_replay_valuation"})
        self.assertEqual({mode.value for mode in RiskValuationMode},{"ACTIVATION","REPLAY_ONLY","LIVE"})

    def test_no_broker_network_or_environment_dependency(self):
        tree=ast.parse(inspect.getsource(module))
        forbidden={"exchange","pybit","requests","socket","place_order","cancel_order","getenv","environ","session","create_demo_session"}
        names={node.id for node in ast.walk(tree) if isinstance(node,ast.Name)}
        names|={node.attr for node in ast.walk(tree) if isinstance(node,ast.Attribute)}
        imports=[node.module or "" for node in ast.walk(tree) if isinstance(node,ast.ImportFrom)]
        imports += [alias.name for node in ast.walk(tree) if isinstance(node,ast.Import) for alias in node.names]
        self.assertFalse(names & forbidden)
        self.assertFalse(any(set(name.split(".")) & forbidden for name in imports))
        self.assertEqual(module._SCHEMA_V1,LEGACY_V1_SCHEMA)

    def test_existing_checkpoint_and_decision_writes_leave_risk_rows_exact(self):
        self.activate()
        before=self.risk_rows()
        cp=self.next_checkpoint(observed_at_ms=1)
        self.store.save_checkpoint(cp,expected_sequence=cp.sequence-1)
        self.commit_candle(HOUR)
        self.assertEqual(self.risk_rows(),before)
        self.assertEqual(self.store.list_risk_verdicts(),())

    def test_placement_lifecycle_writes_do_not_update_risk_records(self):
        self.activate()
        before=self.risk_rows()
        action=RiskReplayTests.pending_buy(self)
        self.assertEqual(self.risk_rows(),before)
        RiskReplayTests.observe_fill(self,action)
        self.assertEqual(self.risk_rows(),before)
        self.assertEqual(self.store.list_risk_verdicts(),())



class RiskAdditionalBoundaryTests(RiskPersistenceCase):
    def test_valuation_record_rejects_coercion_and_inconsistent_fields(self):
        row=self.activate()
        variants=({"mode":"ACTIVATION"},{"mark_price":105.25},{"owned_base_quantity":-1},
            {"owned_base_quantity":D(-1)},{"virtual_quote_cash":1000},{"risk_equity":D(999)},
            {"peak_risk_equity":D(999)},{"daily_pnl":D(1)},{"entries_this_utc_day":True},
            {"entries_this_utc_day":2**63},{"fill_evidence_count":True},{"fill_evidence_count":-1},
            {"fill_evidence_digest":"F"*64},{"trip_pending_report":1},{"trip_reason":RiskReason.ENTRY_COUNT_LIMIT},
            {"tripped_at_ms":HOUR},{"valued_at_ms":2*HOUR},{"candle_open_ms":True},{"timeframe":"1"})
        for changes in variants:
            with self.subTest(changes=changes),self.assertRaises(RuntimeStoreError):
                replace(row,**changes)

    def test_sql_boolean_and_enum_corruption_is_rejected(self):
        self.activate()
        connection=self.store._connection
        for column,value in (("mode","UNKNOWN"),("trip_pending_report",2),("trip_reason","UNKNOWN")):
            with self.subTest(column=column):
                connection.execute("PRAGMA ignore_check_constraints=ON")
                connection.execute("BEGIN IMMEDIATE")
                try:
                    connection.execute("UPDATE risk_valuations SET "+column+"=?",(value,))
                    with self.assertRaises(RuntimeStoreError):
                        self.store.list_risk_valuations()
                finally:
                    connection.execute("ROLLBACK")
                    connection.execute("PRAGMA ignore_check_constraints=OFF")

    def test_nonfinite_risk_money_is_rejected(self):
        self.activate()
        self.corrupt("UPDATE risk_valuations SET daily_pnl='NaN'")
        self.reject_reopen()

    def test_unknown_risk_contract_version_is_rejected_on_load(self):
        self.activate()
        self.corrupt("UPDATE risk_configurations SET risk_contract_version=2")
        self.reject_reopen()

    def test_extra_risk_column_is_rejected_without_repair(self):
        self.activate()
        self.corrupt("ALTER TABLE risk_valuations ADD COLUMN alternative_mark TEXT")
        self.reject_reopen()

    def test_risk_fk_definition_is_checked_exactly(self):
        self.store.close()
        with sqlite3.connect(self.lock.database_path) as connection:
            connection.execute("DROP TABLE risk_verdicts")
            sql=module._RISK_SCHEMA["risk_verdicts"].replace("REFERENCES actions(logical_action_id)","REFERENCES actions(order_link_id)")
            connection.execute(sql)
        self.reject_reopen()

    def test_foreign_epoch_parent_and_duplicate_sequence_are_refused(self):
        self.activate()
        self.corrupt("UPDATE risk_epochs SET parent_epoch_id=?",("f"*64,))
        self.reject_reopen()

    def test_changed_evidence_hash_without_added_fill_is_invalid_history(self):
        self.activate()
        self.commit_candle(HOUR)
        self.store.append_risk_replay_valuation(candle_open_ms=HOUR)
        self.corrupt("UPDATE risk_valuations SET fill_evidence_count=1,fill_evidence_digest=? WHERE valued_at_ms=?",("f"*64,HOUR))
        self.reject_reopen()

    def test_risk_specific_row_bound_prevents_truncation(self):
        self.activate()
        self.commit_candle(HOUR)
        self.store.append_risk_replay_valuation(candle_open_ms=HOUR)
        with patch.object(module,"_MAX_ROWS",1),self.assertRaisesRegex(RuntimeStoreError,"Risk history"):
            self.store._validate_risk_history()

    def test_all_risk_reads_require_live_connection_and_durability(self):
        self.activate()
        reads=(self.store.get_risk_configuration,self.store.get_current_risk_epoch,
            self.store.get_latest_risk_valuation,self.store.list_risk_valuations,
            lambda:self.store.get_risk_verdict(0),self.store.list_risk_verdicts)
        self.store._connection.execute("PRAGMA foreign_keys=OFF")
        for read in reads:
            with self.assertRaises(RuntimeStoreError):
                read()
        self.store._configure()
        self.store.close()
        for read in reads:
            with self.assertRaises(RuntimeStoreError):
                read()

    def test_invalid_write_times_fail_without_mutation(self):
        self.activate()
        before=self.risk_rows()
        for value in (True,-1,1,0.0,"0",2**63):
            with self.subTest(value=value),self.assertRaises(RuntimeStoreError):
                self.store.append_risk_replay_valuation(candle_open_ms=value)
        self.assertEqual(self.risk_rows(),before)

    def test_future_live_record_decoding_and_read_only_verdict_support(self):
        first=self.activate()
        self.commit_candle(HOUR)
        c=self.store.get_candle(HOUR)
        epoch=self.store.get_current_risk_epoch()
        state=advance_risk_state(risk_configuration(),first.state(HOUR),first.book,c.close,2*HOUR)
        row=module._risk_valuation(epoch,RiskValuationMode.LIVE,c,first.book,state,(0,first.fill_evidence_digest))
        verdict=RiskVerdictRecord("BTCUSDT","60",HOUR,epoch.epoch_id,2*HOUR,epoch.risk_configuration_digest,
            None,None,RiskVerdict.ALLOW,None,None,2*HOUR)
        # TEST-ONLY future atomic fixture, not a production LIVE writer.
        with self.store._transaction():
            self.store._insert("risk_valuations",module._encode(row))
            self.store._insert("risk_verdicts",module._encode(verdict))
        self.reopen()
        self.assertEqual(self.store.get_risk_verdict(HOUR),verdict)
        self.assertEqual(self.store.list_risk_verdicts(epoch.epoch_id),(verdict,))
        self.assertEqual(self.store.get_latest_risk_valuation(),row)

    def test_live_valuation_without_verdict_is_rejected(self):
        self.activate()
        self.commit_candle(HOUR)
        self.store.append_risk_replay_valuation(candle_open_ms=HOUR)
        self.corrupt("UPDATE risk_valuations SET mode='LIVE' WHERE candle_open_ms=?",(HOUR,))
        self.reject_reopen()

    def test_legacy_cancellation_and_abandon_writes_leave_risk_rows_unchanged(self):
        self.activate()
        before=self.risk_rows()
        action=RiskReplayTests.pending_buy(self)
        cancel=ActionRecord("e"*64,JournalActionKind.CANCEL,"BTCUSDT",3*HOUR,5,3,
            control_id="risk-test-control",parent_action_id=ACTION_ID,target_broker_order_id="order-1")
        cp=self.next_checkpoint()
        self.store.prepare_cancellation(cancel,cp,expected_sequence=cp.sequence-1)
        cp=self.next_checkpoint()
        self.store.abandon_prepared(cancel.logical_action_id,cp,expected_sequence=cp.sequence-1,terminal_at_ms=2*HOUR+5)
        self.assertEqual(self.risk_rows(),before)
        self.assertEqual(self.store.get_action(ACTION_ID),action)

    def test_pure_risk_source_and_all_123_tests_are_byte_identical(self):
        root=Path(__file__).resolve().parents[1]
        for relative,expected in (
            ("src/trading_lab/risk/runtime_risk.py","6dfa26e4317d914184c676aae337a2c23e08314704a7e2f54f7e8014fc0f6737"),
            ("tests/test_runtime_risk.py","48f23ceb6415ace65f3f63e5429cb14d8d5ad587fc5d31419375c818599a70dc")):
            self.assertEqual(hashlib.sha256((root/relative).read_bytes()).hexdigest(),expected)


if __name__ == "__main__":
    unittest.main()
