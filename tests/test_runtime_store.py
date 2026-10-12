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
        self.corrupt("PRAGMA user_version=2")
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
        allowed = {"contextlib", "dataclasses", "decimal", "enum", "hashlib", "json", "os", "pathlib", "re", "sqlite3", "stat", "sys", "fcntl", "locking", "state"}
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


if __name__ == "__main__":
    unittest.main()
