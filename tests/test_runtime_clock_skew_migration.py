"""Decision 026: temporary synthetic journals only, never operator state."""

import ast
from contextlib import closing
from dataclasses import fields, replace
from decimal import Decimal
import hashlib
import inspect
import os
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from trading_lab.risk.runtime_risk import RuntimeRiskConfiguration
from trading_lab.runtime.locking import RuntimeAccountLock, RuntimeLockError
from trading_lab.runtime.planner import CanonicalDecision, DecisionMode, plan_action
from trading_lab.runtime.state import (
    PositionEvidence, RuntimeReason, RuntimeState, RuntimeStateSnapshot,
)
from trading_lab.runtime.store import (
    ActionPhase, ActionRecord, CandleRecord, DecisionDisposition, DecisionRecord,
    JournalActionKind, OwnedFillRecord, RuntimeConfiguration, RuntimeStore,
    RuntimeStoreConflictError, RuntimeStoreError, RuntimeStoreIntegrityError,
    migrate_demo_clock_skew_1000_to_6000,
)
import trading_lab.runtime.store as module


D = Decimal
HOUR = 3_600_000
ANCHOR = 1792713600000
CANCEL_ID = "c" * 64
SOURCE_HASH = "5ec4e7ebcb7c31272a9dd25bd5a283faedee333c767b426317329dc36da132ed"


def reviewed_configuration():
    # Synthetic opaque identities, deliberately unrelated to content hashing.
    return RuntimeConfiguration(
        "bybit-demo", "demo-main", "bot1", "ema_trend", "a" * 64,
        (("fast_span", 20), ("slow_span", 50), ("warmup_candles", 50)),
        "BTCUSDT", "BTC", "USDT", "60", HOUR, "b" * 64, D("10"),
        ANCHOR, 60000, 60000, 600000, 5, 3, 10000, 1000,
    )


class ClockSkewMigrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = self.enterContext(TemporaryDirectory())
        self.root = Path(self.directory)
        self.lock = self.enterContext(RuntimeAccountLock(self.root, "demo-main"))
        self.config = reviewed_configuration()
        self.target = replace(self.config, max_clock_skew_ms=6000)
        # Every test fails if the boundary tries external access or discovery.
        self.enterContext(patch("socket.create_connection", side_effect=AssertionError("No network")))
        self.enterContext(patch("os.getenv", side_effect=AssertionError("No credentials")))

    def fixture(self, *, rich=True, target=False):
        config = self.target if target else self.config
        anchor = config.history_anchor_ms
        with RuntimeStore.open(self.lock, config, initialize=True) as store:
            checkpoint = store.get_checkpoint()
            checkpoint = replace(checkpoint, sequence=1, snapshot=RuntimeStateSnapshot(
                RuntimeState.FLAT, D(0), PositionEvidence.CONFIRMED, 0),
                observed_at_ms=anchor+HOUR+10, last_reconciled_at_ms=anchor+HOUR+10,
                coverage_start_ms=anchor, coverage_end_ms=anchor+HOUR,
                bootstrap_until_ms=anchor, replay_until_ms=anchor)
            store.save_checkpoint(checkpoint, expected_sequence=0)
            candle = CandleRecord("BTCUSDT", "60", anchor, "d"*64,
                                  D(100), D(110), D(90), D(100), D("1.23456789"))
            decision = DecisionRecord("BTCUSDT", "60", anchor, "d"*64, "HOLD", 0,
                                      DecisionDisposition.BOOTSTRAP, anchor+HOUR)
            store.commit_decision(candle, decision, replace(checkpoint, sequence=2,
                last_processed_candle_ms=anchor), expected_sequence=1)
            store.initialize_risk_journal(RuntimeRiskConfiguration(
                D(100), D(10), D(10), D(10), D("0.05"), D("0.10"), 3, "BTC", "USDT"),
                candle_open_ms=anchor)
            if rich:
                self.populate_owned_history(store, config, candle)
            checkpoint = store.get_checkpoint()
            store.save_checkpoint(replace(checkpoint, sequence=checkpoint.sequence+1,
                snapshot=replace(checkpoint.snapshot, state=RuntimeState.STARTING,
                                 position_evidence=PositionEvidence.LAST_KNOWN, reason=None)),
                expected_sequence=checkpoint.sequence)

    def populate_owned_history(self, store, config, candle):
        anchor = config.history_anchor_ms
        checkpoint = store.get_checkpoint()
        now = anchor+2*HOUR+10
        checkpoint = replace(checkpoint, sequence=checkpoint.sequence+1,
                             observed_at_ms=now, last_reconciled_at_ms=now)
        store.save_checkpoint(checkpoint, expected_sequence=checkpoint.sequence-1)
        canonical = CanonicalDecision("BTCUSDT", "60", anchor+HOUR, "e"*64,
                                      "LONG_ENTRY", 1, anchor+2*HOUR)
        plan = plan_action(config, checkpoint, canonical, evaluated_at_ms=now,
                           mode=DecisionMode.LIVE, action_history=())
        from trading_lab.runtime.state import transition_runtime_state
        pending = transition_runtime_state(checkpoint.snapshot, plan.events[0])
        store.commit_live_risk_decision(replace(candle, candle_open_ms=anchor+HOUR,
            input_fingerprint="e"*64), plan.decision, replace(checkpoint,
            sequence=checkpoint.sequence+1, snapshot=pending,
            last_processed_candle_ms=anchor+HOUR), expected_sequence=checkpoint.sequence,
            evaluated_at_ms=now, proposed_action=plan.action)
        checkpoint = store.get_checkpoint()
        store.start_attempt(plan.action.logical_action_id, replace(checkpoint,
            sequence=checkpoint.sequence+1), expected_sequence=checkpoint.sequence)
        checkpoint = store.get_checkpoint()
        acknowledged = replace(store.get_action(plan.action.logical_action_id),
            phase=ActionPhase.ACKNOWLEDGED, broker_order_id="synthetic-order",
            submitted_amount=D("9.999"), acknowledgement_broker_ms=now,
            acknowledgement_observed_ms=now+1, order_status="PARTIALLY_FILLED",
            external_status="PartiallyFilled", observed_at_ms=now+2)
        execution = OwnedFillRecord("bybit-demo", "demo-main", "synthetic-fill",
            plan.action.logical_action_id, "synthetic-order", plan.action.order_link_id,
            "BTCUSDT", "BUY", D("0.090000000000000001"), D("100.123456789"),
            D("-0.000000123456789"), "USDT", now+1, now+2)
        store.record_observation(acknowledged, replace(checkpoint,
            sequence=checkpoint.sequence+1, snapshot=replace(checkpoint.snapshot,
                owned_base_quantity=execution.executed_quantity)),
            expected_sequence=checkpoint.sequence, fills=(execution,))
        checkpoint = store.get_checkpoint()
        cancel = ActionRecord(CANCEL_ID, JournalActionKind.CANCEL, "BTCUSDT",
            now+600000, 2, 1, control_id="synthetic-cancel", parent_action_id=plan.action.logical_action_id,
            target_broker_order_id="synthetic-order")
        store.prepare_cancellation(cancel, replace(checkpoint, sequence=checkpoint.sequence+1),
                                   expected_sequence=checkpoint.sequence)
        checkpoint = store.get_checkpoint()
        store.start_attempt(CANCEL_ID, replace(checkpoint, sequence=checkpoint.sequence+1),
                            expected_sequence=checkpoint.sequence)
        checkpoint = store.get_checkpoint()
        cancel = replace(store.get_action(CANCEL_ID), phase=ActionPhase.UNKNOWN_OUTCOME,
                         safe_reason=RuntimeReason.ACTION_OUTCOME_UNKNOWN)
        store.record_observation(cancel, replace(checkpoint, sequence=checkpoint.sequence+1,
            snapshot=replace(checkpoint.snapshot, state=RuntimeState.UNCERTAIN,
                position_evidence=PositionEvidence.LAST_KNOWN,
                reason=RuntimeReason.ACTION_OUTCOME_UNKNOWN)), expected_sequence=checkpoint.sequence)
        checkpoint = store.get_checkpoint()
        next_candle = replace(candle, candle_open_ms=anchor+2*HOUR)
        next_decision = replace(plan.decision, candle_open_ms=next_candle.candle_open_ms,
            input_fingerprint=next_candle.input_fingerprint, signal="HOLD", action_id=None,
            disposition=DecisionDisposition.REPLAY_ONLY, available_at_ms=anchor+3*HOUR)
        store.commit_decision(next_candle, next_decision, replace(checkpoint,
            sequence=checkpoint.sequence+1, last_processed_candle_ms=next_candle.candle_open_ms,
            replay_until_ms=next_candle.candle_open_ms), expected_sequence=checkpoint.sequence)
        store.append_risk_replay_valuation(candle_open_ms=next_candle.candle_open_ms)

    def snapshot(self):
        # Only this test's temporary path; mode=ro never creates a missing DB.
        with closing(sqlite3.Connection(self.lock.database_path.as_uri()+"?mode=ro", uri=True)) as connection:
            schema = tuple(connection.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name"))
            rows = {table: tuple(connection.execute("SELECT rowid,* FROM " + table + " ORDER BY rowid"))
                    for table in module._SCHEMA}
            return schema, connection.execute("PRAGMA user_version").fetchone()[0], rows

    def corrupt(self, sql, args=()):
        with closing(sqlite3.connect(self.lock.database_path)) as connection, connection:
            connection.execute(sql, args)

    def migrate(self, configuration=None, lock=None):
        return migrate_demo_clock_skew_1000_to_6000(
            self.lock if lock is None else lock, self.config if configuration is None else configuration)

    def assert_only_skew_changed(self, before):
        after = self.snapshot()
        expected = (before[0], before[1], dict(before[2]))
        identity = list(expected[2]["identity"][0])
        columns = ["rowid", "singleton", *(field.name for field in fields(RuntimeConfiguration))]
        # SQLite identity column order is the frozen dataclass order.
        skew = columns.index("max_clock_skew_ms")
        self.assertEqual(identity[skew], 1000)
        identity[skew] = 6000
        expected[2]["identity"] = (tuple(identity),)
        self.assertEqual(after, expected)
        return after

    def assert_refused_unchanged(self, configuration=None, lock=None):
        before = self.lock.database_path.read_bytes()
        with self.assertRaises((RuntimeStoreError, RuntimeLockError)):
            self.migrate(configuration, lock)
        self.assertEqual(self.lock.database_path.read_bytes(), before)
        self.assertEqual(self.lock._stores, 0)
        self.assertNotIn(self.lock.database_path, module._OPEN_DATABASES)

    def capture_connections(self, *, fault=None):
        connect = sqlite3.connect
        connections, statements = [], []
        class ObservedConnection(sqlite3.Connection):
            def execute(inner, sql, *args):
                statements.append(sql)
                if fault is not None:
                    fault(inner, sql)
                return super().execute(sql, *args)
        def wrapped(*args, **kwargs):
            self.assertIn("?mode=rw", args[0])
            self.assertNotIn("factory", kwargs)
            connection = connect(*args, factory=ObservedConnection, **kwargs)
            connections.append(connection)
            return connection
        self.enterContext(patch.object(module.sqlite3, "connect", side_effect=wrapped))
        return connections, statements

    def test_success_preserves_every_row_except_the_one_skew_field(self):
        self.fixture()
        before = self.snapshot()
        self.assertTrue(all(before[2][table] for table in module._SCHEMA))
        self.assertIs(self.migrate(), True)
        self.assert_only_skew_changed(before)
        with RuntimeStore.open(self.lock, self.target) as store:
            self.assertEqual(store.get_configuration(), self.target)
            self.assertEqual(store.get_checkpoint().snapshot.state, RuntimeState.STARTING)
            self.assertEqual(store.get_checkpoint().snapshot.position_evidence, PositionEvidence.LAST_KNOWN)
            self.assertEqual(len(store.list_actions()), 2)
            self.assertEqual(len(store.list_fills()), 1)
            self.assertEqual(len(store.list_risk_valuations()), 3)
            self.assertEqual(len(store.list_risk_verdicts()), 1)

    def test_all_other_configuration_fields_and_opaque_digests_are_preserved(self):
        self.fixture()
        self.migrate()
        with RuntimeStore.open(self.lock, self.target) as store:
            saved = store.get_configuration()
            for field in fields(self.config):
                if field.name != "max_clock_skew_ms":
                    self.assertEqual(getattr(saved, field.name), getattr(self.config, field.name), field.name)
            self.assertEqual((saved.decision_max_age_ms, saved.observation_max_age_ms), (60000, 60000))

    def test_matching_nondefault_history_anchor_is_preserved_with_full_history(self):
        self.config = replace(self.config, history_anchor_ms=ANCHOR+24*HOUR)
        self.target = replace(self.config, max_clock_skew_ms=6000)
        self.fixture()
        before = self.snapshot()
        self.assertTrue(all(before[2][table] for table in module._SCHEMA))
        self.assertIs(self.migrate(), True)
        self.assert_only_skew_changed(before)
        with RuntimeStore.open(self.lock, self.target) as store:
            self.assertEqual(store.get_configuration().history_anchor_ms, self.config.history_anchor_ms)
            self.assertEqual(store.get_checkpoint().last_processed_candle_ms, self.config.history_anchor_ms+2*HOUR)
        after = self.snapshot()
        self.assertIs(self.migrate(), False)
        self.assertEqual(self.snapshot(), after)

    def test_matching_non_none_broker_account_id_is_preserved_with_full_history(self):
        self.config = replace(self.config, broker_account_id="synthetic-account")
        self.target = replace(self.config, max_clock_skew_ms=6000)
        self.fixture()
        before = self.snapshot()
        self.assertTrue(all(before[2][table] for table in module._SCHEMA))
        self.assertIs(self.migrate(), True)
        self.assert_only_skew_changed(before)
        with RuntimeStore.open(self.lock, self.target) as store:
            self.assertEqual(store.get_configuration().broker_account_id, "synthetic-account")
        after = self.snapshot()
        self.assertIs(self.migrate(), False)
        self.assertEqual(self.snapshot(), after)

    def test_caller_history_anchor_mismatch_is_refused_without_write(self):
        self.fixture()
        mismatched = replace(self.config, history_anchor_ms=ANCHOR+HOUR)
        self.assert_refused_unchanged(mismatched)
        self.assertIs(self.migrate(), True)
        self.assert_refused_unchanged(mismatched)

    def test_caller_broker_account_id_mismatch_is_refused_without_write(self):
        self.config = replace(self.config, broker_account_id="synthetic-account")
        self.target = replace(self.config, max_clock_skew_ms=6000)
        self.fixture()
        for value in (None, "different-account"):
            with self.subTest(broker_account_id=value):
                self.assert_refused_unchanged(replace(self.config, broker_account_id=value))
        self.assertIs(self.migrate(), True)
        for value in (None, "different-account"):
            with self.subTest(target_broker_account_id=value):
                self.assert_refused_unchanged(replace(self.config, broker_account_id=value))

    def test_old_configuration_open_is_rejected_after_success(self):
        self.fixture()
        self.migrate()
        before = self.lock.database_path.read_bytes()
        with self.assertRaises(RuntimeStoreError):
            RuntimeStore.open(self.lock, self.config, initialize=False)
        self.assertEqual(self.lock.database_path.read_bytes(), before)

    def test_exact_already_completed_target_is_false_with_no_transaction_or_write(self):
        self.fixture(target=True)
        before = self.lock.database_path.read_bytes()
        connections, statements = self.capture_connections()
        self.assertIs(self.migrate(), False)
        self.assertEqual(self.lock.database_path.read_bytes(), before)
        self.assertFalse(any(sql.startswith(("BEGIN", "UPDATE", "COMMIT")) for sql in statements))
        self.assertEqual(len(connections), 2)

    def test_second_explicit_invocation_is_verification_only(self):
        self.fixture()
        self.assertIs(self.migrate(), True)
        before = self.snapshot()
        self.assertIs(self.migrate(), False)
        self.assertEqual(self.snapshot(), before)

    def test_single_update_one_commit_and_full_durability(self):
        self.fixture()
        connections, statements = self.capture_connections()
        bindings = []
        validate = RuntimeStore._validate_relations
        def checked(store):
            if store._connection.in_transaction:
                bindings.append(store._configuration.max_clock_skew_ms)
                settings = store.durability_settings()
                self.assertEqual((settings["journal_mode"], settings["synchronous"], settings["foreign_keys"]),
                                 ("delete", 3, 1))
                if sys.platform == "darwin":
                    self.assertEqual(settings["fullfsync"], 1)
            return validate(store)
        with patch.object(RuntimeStore, "_validate_relations", checked):
            self.assertTrue(self.migrate())
        writes = [sql for sql in statements if sql.split()[0] in
                  {"UPDATE", "INSERT", "DELETE", "REPLACE", "CREATE", "ALTER", "DROP"}]
        self.assertEqual(writes, ["UPDATE identity SET max_clock_skew_ms=6000 WHERE singleton=1 AND max_clock_skew_ms=1000"])
        self.assertEqual(statements.count("BEGIN IMMEDIATE"), 1)
        self.assertEqual(statements.count("COMMIT"), 1)
        self.assertEqual(bindings[0], 1000)
        self.assertEqual(bindings[-1], 6000)
        self.assertEqual(len(connections), 2)
        for connection in connections:
            with self.assertRaises(sqlite3.ProgrammingError):
                connection.execute("SELECT 1")

    def test_reviewed_zero_last_known_exposure_is_not_promoted_or_restarted(self):
        self.fixture(rich=False)
        before = self.snapshot()
        with patch.object(RuntimeStore, "save_checkpoint", side_effect=AssertionError("No checkpoint write")), \
             patch.object(RuntimeStore, "initialize_risk_journal", side_effect=AssertionError("No activation")):
            self.migrate()
        self.assert_only_skew_changed(before)
        with RuntimeStore.open(self.lock, self.target) as store:
            snapshot = store.get_checkpoint().snapshot
            self.assertEqual((snapshot.state, snapshot.position_evidence, snapshot.owned_base_quantity),
                             (RuntimeState.STARTING, PositionEvidence.LAST_KNOWN, D(0)))

    def test_runtime_halt_and_shutdown_latch_remain_unchanged(self):
        self.fixture()
        with RuntimeStore.open(self.lock, self.config) as store:
            cp = store.get_checkpoint()
            halted = replace(cp, sequence=cp.sequence+1, halted_at_ms=ANCHOR+4*HOUR,
                snapshot=replace(cp.snapshot, state=RuntimeState.HALTED,
                                 reason=RuntimeReason.RECOVERY_EXHAUSTED))
            store.save_checkpoint(halted, expected_sequence=cp.sequence)
            stopped = replace(halted, sequence=halted.sequence+1, shutdown_at_ms=ANCHOR+4*HOUR+1,
                snapshot=replace(halted.snapshot, state=RuntimeState.STOPPING,
                                 stopped_from=RuntimeState.HALTED))
            store.save_checkpoint(stopped, expected_sequence=halted.sequence)
        before = self.snapshot()
        self.migrate()
        self.assert_only_skew_changed(before)

    def test_risk_trip_history_and_epoch_are_not_rearmed(self):
        self.fixture()
        with RuntimeStore.open(self.lock, self.config) as store:
            cp = store.get_checkpoint()
            at = ANCHOR+3*HOUR
            candle = CandleRecord("BTCUSDT", "60", at, "f"*64, D(1), D(1), D(1), D(1), D(0))
            decision = DecisionRecord("BTCUSDT", "60", at, "f"*64, "HOLD", 1,
                                      DecisionDisposition.REPLAY_ONLY, at+HOUR)
            store.commit_decision(candle, decision, replace(cp, sequence=cp.sequence+1,
                last_processed_candle_ms=at, replay_until_ms=at), expected_sequence=cp.sequence)
            # Exact owned exposure loses more than the fixed five-USDT daily
            # bound at this synthetic close, without changing any risk policy.
            store.append_risk_replay_valuation(candle_open_ms=at)
            latest = store.get_latest_risk_valuation()
            self.assertIsNotNone(latest.trip_reason)
            self.assertTrue(latest.trip_pending_report)
        before = self.snapshot()
        self.migrate()
        self.assert_only_skew_changed(before)

    def test_unexpected_durable_skews_are_refused_without_write(self):
        self.fixture()
        for value in (500, 2000, 5000, 7000, 0, -1, "invalid"):
            with self.subTest(value=value):
                self.corrupt("UPDATE identity SET max_clock_skew_ms=?", (value,))
                self.assert_refused_unchanged()

    def test_caller_must_supply_old_1000_not_target_or_arbitrary_skew(self):
        self.fixture()
        for value in (500, 2000, 5000, 6000, 7000):
            with self.subTest(value=value):
                self.assert_refused_unchanged(replace(self.config, max_clock_skew_ms=value))

    def test_other_durable_configuration_mismatches_are_not_repaired(self):
        self.fixture()
        for name, value in (("configuration_digest", "f"*64), ("strategy_implementation_digest", "e"*64),
                            ("broker_account_id", "different"), ("decision_max_age_ms", 60001),
                            ("observation_max_age_ms", 60001), ("buy_quote_budget", "11")):
            with self.subTest(field=name):
                original = module._encode(self.config)[name]
                self.corrupt("UPDATE identity SET " + name + "=?", (value,))
                self.assert_refused_unchanged()
                self.corrupt("UPDATE identity SET " + name + "=?", (original,))

    def test_unreviewed_caller_profile_cannot_widen_deployment_scope(self):
        self.fixture()
        cases = ({"account_binding": "other"}, {"bot_id": "bot2"},
                 {"symbol": "ETHUSDT", "base_currency": "ETH"}, {"buy_quote_budget": D(11)},
                 {"decision_max_age_ms": 60001},
                 {"observation_max_age_ms": 60001}, {"reconciliation_timeout_ms": 600001},
                 {"reconciliation_round_limit": 6}, {"read_attempt_limit": 2},
                 {"request_timeout_ms": 10001},
                 {"configuration_digest": "e"*64}, {"strategy_implementation_digest": "f"*64})
        for changes in cases:
            with self.subTest(fields=tuple(changes)):
                self.assert_refused_unchanged(replace(self.config, **changes))

    def test_wrong_durable_broker_account_and_bot_are_refused(self):
        self.fixture(rich=False)
        for name, value in (("broker_id", "bybit-live"), ("account_binding", "other"), ("bot_id", "bot2")):
            with self.subTest(field=name):
                self.corrupt("UPDATE identity SET " + name + "=?", (value,))
                self.assert_refused_unchanged()
                self.corrupt("UPDATE identity SET " + name + "=?", (getattr(self.config, name),))

    def test_missing_identity_is_refused(self):
        self.fixture(rich=False)
        self.corrupt("DELETE FROM identity")
        self.assert_refused_unchanged()

    def test_malformed_identity_is_refused(self):
        self.fixture()
        self.corrupt("UPDATE identity SET strategy_parameters='invalid'")
        self.assert_refused_unchanged()

    def test_target_skew_does_not_hide_other_identity_or_history_corruption(self):
        self.fixture(target=True)
        self.corrupt("UPDATE checkpoint SET last_processed_candle_ms=?", (ANCHOR+10*HOUR,))
        self.assert_refused_unchanged()

    def test_unheld_lock_blocks_before_sqlite_access(self):
        self.fixture()
        unheld = RuntimeAccountLock(self.root, "demo-main")
        with patch.object(module.sqlite3, "connect", side_effect=AssertionError("No SQL without lock")):
            self.assert_refused_unchanged(lock=unheld)

    def test_missing_lock_and_nonexact_configuration_types_are_refused(self):
        self.fixture()
        before = self.lock.database_path.read_bytes()
        for lock, config in ((None, self.config), (self.lock, None), (self.lock, {})):
            with self.subTest(types=(type(lock), type(config))), self.assertRaises(RuntimeStoreError):
                migrate_demo_clock_skew_1000_to_6000(lock, config)
        self.assertEqual(self.lock.database_path.read_bytes(), before)

    def test_wrong_account_lock_cannot_select_another_store(self):
        self.fixture()
        with RuntimeAccountLock(self.root, "other") as other:
            self.assert_refused_unchanged(lock=other)
            self.assertFalse(other.database_path.exists())

    def test_open_store_blocks_migration(self):
        self.fixture()
        with RuntimeStore.open(self.lock, self.config):
            before = self.snapshot()
            with self.assertRaises(RuntimeStoreConflictError):
                self.migrate()
            self.assertEqual(self.snapshot(), before)

    def test_missing_store_is_not_initialized(self):
        with self.assertRaises(RuntimeStoreError):
            self.migrate()
        self.assertFalse(self.lock.database_path.exists())
        self.assertFalse(self.lock.database_path.parent.exists())

    def test_missing_file_in_existing_registry_is_not_created(self):
        self.lock.database_path.parent.mkdir(parents=True)
        with self.assertRaises(RuntimeStoreError):
            self.migrate()
        self.assertEqual(list(self.lock.database_path.parent.iterdir()), [])

    def test_canonical_database_path_cannot_be_overridden(self):
        self.fixture()
        original = self.lock.database_path
        try:
            self.lock.database_path = self.root / "alternate.sqlite3"
            with self.assertRaises(RuntimeStoreConflictError):
                self.migrate()
            self.assertFalse(self.lock.database_path.exists())
        finally:
            self.lock.database_path = original
        with RuntimeStore.open(self.lock, self.config) as store:
            self.assertEqual(store.get_configuration(), self.config)

    def test_symlink_and_hardlink_database_are_refused(self):
        self.fixture()
        path = self.lock.database_path
        original = path.with_name("saved.sqlite3")
        path.rename(original)
        path.symlink_to(original)
        self.assert_refused_unchanged()
        path.unlink()
        os.link(original, path)
        self.assert_refused_unchanged()

    def test_symlink_account_directory_is_refused(self):
        self.fixture()
        directory = self.lock.database_path.parent
        moved = directory.with_name("moved")
        directory.rename(moved)
        directory.symlink_to(moved, target_is_directory=True)
        self.assert_refused_unchanged()

    def test_unsafe_sidecar_is_not_followed_or_modified(self):
        self.fixture()
        target = self.root / "unrelated"
        target.write_bytes(b"preserve")
        self.lock.database_path.with_name("runtime.sqlite3-journal").symlink_to(target)
        self.assert_refused_unchanged()
        self.assertEqual(target.read_bytes(), b"preserve")

    def test_wal_is_refused_without_changing_mode(self):
        self.fixture()
        self.corrupt("PRAGMA journal_mode=WAL")
        self.assert_refused_unchanged()

    def test_unsupported_schema_version_and_contract_are_refused(self):
        self.fixture()
        for sql in ("PRAGMA user_version=1", "PRAGMA user_version=3",
                    "UPDATE identity SET schema_version=1", "UPDATE identity SET runtime_contract_version=2"):
            with self.subTest(sql=sql):
                self.corrupt(sql)
                self.assert_refused_unchanged()
                self.corrupt("PRAGMA user_version=2")
                self.corrupt("UPDATE identity SET schema_version=2,runtime_contract_version=1")

    def test_changed_schema_is_not_repaired(self):
        self.fixture()
        self.corrupt("ALTER TABLE candles ADD COLUMN unexpected TEXT")
        self.assert_refused_unchanged()

    def test_integrity_conflict_blocks_before_identity_update(self):
        self.fixture()
        self.corrupt("UPDATE checkpoint SET pending_action_id=?", ("f"*64,))
        self.assert_refused_unchanged()

    def test_risk_digest_corruption_blocks_before_identity_update(self):
        self.fixture()
        self.corrupt("UPDATE risk_configurations SET risk_capital_quote='101'")
        self.assert_refused_unchanged()

    def test_complete_read_and_size_bounds_are_preserved(self):
        self.fixture()
        for name in ("_MAX_ROWS", "_MAX_DATABASE_BYTES"):
            with self.subTest(bound=name), patch.object(module, name, 1):
                self.assert_refused_unchanged()

    def test_source_is_fully_revalidated_inside_transaction(self):
        self.fixture()
        before = self.snapshot()
        validate = RuntimeStore._validate_all
        def changed(store):
            if store._connection.in_transaction:
                raise RuntimeStoreIntegrityError("Synthetic source conflict")
            return validate(store)
        with patch.object(RuntimeStore, "_validate_all", changed), self.assertRaises(RuntimeStoreError):
            self.migrate()
        self.assertEqual(self.snapshot(), before)

    def test_valid_but_changed_source_evidence_is_refused_and_rolled_back(self):
        self.fixture()
        before = self.snapshot()
        validate = RuntimeStore._validate_all
        def changed(store):
            if store._connection.in_transaction and store._configuration == self.config:
                store._connection.execute("UPDATE checkpoint SET sequence=sequence+1")
            return validate(store)
        with patch.object(RuntimeStore, "_validate_all", changed), self.assertRaisesRegex(RuntimeStoreError, "source evidence"):
            self.migrate()
        self.assertEqual(self.snapshot(), before)

    def test_empty_risk_journal_remains_empty_without_activation(self):
        with RuntimeStore.open(self.lock, self.config, initialize=True):
            pass
        before = self.snapshot()
        self.assertTrue(self.migrate())
        self.assert_only_skew_changed(before)
        with RuntimeStore.open(self.lock, self.target) as store:
            self.assertIsNone(store.get_current_risk_epoch())
            self.assertEqual(store.get_checkpoint().sequence, 0)
            self.assertEqual(store.get_checkpoint().snapshot.position_evidence, PositionEvidence.UNKNOWN)

    def test_forged_or_unsupported_caller_configuration_never_opens_sqlite(self):
        self.fixture()
        for name, value in (("broker_id", "bybit-live"), ("strategy_id", "other"),
                            ("schema_version", 1), ("runtime_contract_version", 2),
                            ("timeframe", "15"), ("max_clock_skew_ms", True)):
            forged = replace(self.config)
            object.__setattr__(forged, name, value)
            with self.subTest(field=name), patch.object(module.sqlite3, "connect",
                    side_effect=AssertionError("No SQL for invalid configuration")):
                self.assert_refused_unchanged(forged)

    def test_nonregular_database_is_refused_without_replacement(self):
        self.lock.database_path.mkdir(parents=True)
        with self.assertRaises(RuntimeStoreError):
            self.migrate()
        self.assertTrue(self.lock.database_path.is_dir())

    def test_corrupt_database_is_refused_without_replacement(self):
        self.lock.database_path.parent.mkdir(parents=True)
        self.lock.database_path.write_bytes(b"synthetic invalid SQLite content")
        self.assert_refused_unchanged()

    def test_update_failure_rolls_back_without_reopen_or_retry(self):
        self.fixture()
        before = self.snapshot()
        def fail(connection, sql):
            if sql.startswith("UPDATE identity"):
                raise sqlite3.OperationalError("Private update failure")
        connections, statements = self.capture_connections(fault=fail)
        with patch.object(RuntimeStore, "open", side_effect=AssertionError("No failed reopen")), \
             self.assertRaisesRegex(RuntimeStoreError, "no successful commit"):
            self.migrate()
        self.assertEqual(len(connections), 1)
        self.assertEqual(statements.count("ROLLBACK"), 1)
        self.assertNotIn("COMMIT", statements)
        self.assertEqual(self.snapshot(), before)

    def test_failure_after_update_rolls_back_all_rows(self):
        self.fixture()
        before = self.snapshot()
        validate = RuntimeStore._validate_all
        def failed(store):
            if store._connection.in_transaction and store._configuration == self.target:
                raise RuntimeStoreIntegrityError("Synthetic target validation failure")
            return validate(store)
        with patch.object(RuntimeStore, "_validate_all", failed), self.assertRaises(RuntimeStoreError):
            self.migrate()
        self.assertEqual(self.snapshot(), before)

    def test_failure_before_commit_rolls_back_and_does_not_reopen(self):
        self.fixture()
        before = self.snapshot()
        with patch.object(RuntimeStore, "_commit", side_effect=sqlite3.OperationalError("Private failure")), \
             patch.object(RuntimeStore, "open", side_effect=AssertionError("No automatic reopen")), \
             self.assertRaises(RuntimeStoreError) as caught:
            self.migrate()
        self.assertNotIn("Private", str(caught.exception))
        self.assertEqual(self.snapshot(), before)

    def test_lost_commit_return_closes_and_stops_without_retry_or_reopen(self):
        self.fixture()
        before = self.snapshot()
        commit = RuntimeStore._commit
        attempts = []
        def lost(store):
            attempts.append(1)
            commit(store)
            raise sqlite3.OperationalError("Private lost return")
        with patch.object(RuntimeStore, "_commit", lost), \
             patch.object(RuntimeStore, "open", side_effect=AssertionError("No uncertain reopen")), \
             self.assertRaisesRegex(RuntimeStoreError, "reopening"):
            self.migrate()
        self.assertEqual(attempts, [1])
        self.assertEqual(self.lock._stores, 0)
        self.assertNotIn(self.lock.database_path, module._OPEN_DATABASES)
        # Independent later test inspection, not automatic API continuation.
        self.assert_only_skew_changed(before)

    def test_ended_transaction_error_does_not_assume_commit_or_rollback(self):
        self.fixture()
        before = self.snapshot()
        attempts = []
        def ended(store):
            attempts.append(1)
            store._connection.execute("ROLLBACK")
            raise sqlite3.OperationalError("Private ended transaction error")
        with patch.object(RuntimeStore, "_commit", ended), \
             patch.object(RuntimeStore, "open", side_effect=AssertionError("No uncertain reopen")), \
             self.assertRaisesRegex(RuntimeStoreError, "reopening"):
            self.migrate()
        self.assertEqual(attempts, [1])
        self.assertEqual(self.snapshot(), before)

    def test_failed_rollback_closes_and_requires_independent_inspection(self):
        self.fixture()
        before = self.snapshot()
        def fail(connection, sql):
            if sql.startswith("UPDATE identity") or sql == "ROLLBACK":
                raise sqlite3.OperationalError("Private rollback failure")
        connections, statements = self.capture_connections(fault=fail)
        with patch.object(RuntimeStore, "open", side_effect=AssertionError("No uncertain reopen")), \
             self.assertRaisesRegex(RuntimeStoreError, "reopening"):
            self.migrate()
        self.assertEqual(len(connections), 1)
        self.assertEqual(sum(sql.startswith("UPDATE identity") for sql in statements), 1)
        self.assertNotIn("COMMIT", statements)
        with self.assertRaises(sqlite3.ProgrammingError):
            connections[0].execute("SELECT 1")
        self.assertEqual(self.snapshot(), before)

    def test_post_commit_verification_failure_reports_target_may_be_durable(self):
        self.fixture()
        before = self.snapshot()
        with patch.object(RuntimeStore, "open", side_effect=RuntimeStoreIntegrityError("Private reopen error")), \
             self.assertRaisesRegex(RuntimeStoreIntegrityError, "Post-completion"):
            self.migrate()
        self.assert_only_skew_changed(before)

    def test_post_commit_evidence_mismatch_is_not_repaired_or_retried(self):
        self.fixture()
        before = self.snapshot()
        evidence = module._clock_migration_evidence
        def changed(store):
            result = evidence(store)
            if not store._connection.in_transaction and store._configuration == self.target:
                result["checkpoint"] = ()
            return result
        with patch.object(module, "_clock_migration_evidence", changed), \
             self.assertRaisesRegex(RuntimeStoreIntegrityError, "Post-completion"):
            self.migrate()
        self.assert_only_skew_changed(before)

    def test_protected_row_change_is_detected_before_commit(self):
        self.fixture()
        before = self.snapshot()
        validate = RuntimeStore._validate_all
        def unexpected(store):
            if store._connection.in_transaction and store._configuration == self.target:
                store._connection.execute("UPDATE checkpoint SET sequence=sequence+1")
            return validate(store)
        with patch.object(RuntimeStore, "_validate_all", unexpected), self.assertRaisesRegex(RuntimeStoreError, "protected"):
            self.migrate()
        self.assertEqual(self.snapshot(), before)

    def test_existing_store_class_models_and_schema_are_byte_identical(self):
        source = Path(module.__file__).read_bytes()
        frozen = source.split(b"\n\ndef _clock_migration_evidence", 1)[0].rstrip(b"\n") + b"\n"
        self.assertEqual(hashlib.sha256(frozen).hexdigest(), SOURCE_HASH)

    def test_api_has_no_generic_editor_or_external_capability(self):
        signature = inspect.signature(migrate_demo_clock_skew_1000_to_6000)
        self.assertEqual(tuple(signature.parameters), ("lock", "configuration"))
        tree = ast.parse(inspect.getsource(migrate_demo_clock_skew_1000_to_6000))
        self.assertFalse(any(isinstance(node, (ast.While, ast.AsyncFunctionDef, ast.Await)) for node in ast.walk(tree)))
        names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        names |= {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
        self.assertFalse(names & {"getenv", "environ", "socket", "requests", "exchange", "broker",
            "place_order", "cancel_order", "prepare_process_restart", "reconcile_startup",
            "run_single_cycle", "run_hourly_scheduler", "rearm_risk_epoch"})


if __name__ == "__main__":
    unittest.main()
