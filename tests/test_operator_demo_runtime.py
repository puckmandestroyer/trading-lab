"""Offline operator gates: temporary custody fixtures and fully injected I/O."""

from contextlib import ExitStack
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import ast
import inspect
import io
import itertools
import json
import os
from pathlib import Path
import signal
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

from trading_lab.operator import demo_runtime as m
from trading_lab.runtime.locking import RuntimeAccountLock, RuntimeLockError
from trading_lab.runtime.store import RuntimeStore
from trading_lab.runtime.scheduler import SchedulerExit, SchedulerResult
from trading_lab.runtime.state import PositionEvidence, RuntimeState
from trading_lab.data.closed_candles import MarketCandle, ClosedCandlePrefix
from tests.test_runtime_store import configuration

D = Decimal
H = m.HOUR_MS
BOUNDARY = 10 * H


def utc(ms):
    return datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(milliseconds=ms)


def durable():
    return replace(configuration(), account_binding="demo-main", buy_quote_budget=D("10"),
                   max_clock_skew_ms=6000)


class PrivateCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.root.chmod(0o700)
        self.config = m.DemoRuntimeConfiguration(self.root / "registry", self.root / "observability",
                                                self.root / "secrets/demo.env", 24)


class ConfigurationTests(PrivateCase):
    def test_immutable_and_nonsecret(self):
        with self.assertRaises(FrozenInstanceError):
            self.config.duration_hours = 1
        self.assertNotIn("api_key", repr(self.config))

    def test_invalid_durations(self):
        for value in (0, -1, 73, True, 1.0, float("inf"), "forever", None):
            with self.subTest(value=type(value).__name__), self.assertRaises(m.OperatorError):
                replace(self.config, duration_hours=value)

    def test_valid_bounded_durations(self):
        for value in (1, 24, 72):
            self.assertEqual(replace(self.config, duration_hours=value).duration_hours, value)

    def test_only_canonical_identity(self):
        for name in ("broker_id", "account_binding", "bot_id", "strategy_id", "symbol"):
            with self.subTest(name=name), self.assertRaises(m.OperatorError):
                replace(self.config, **{name: "other"})

    def test_boundary_policy_is_explicit_enum(self):
        with self.assertRaises(m.OperatorError):
            replace(self.config, start_boundary="NEXT_HOUR")

    def test_relative_paths_refused(self):
        for value in ("/tmp/example", Path("relative"), Path("/tmp/../example")):
            with self.subTest(value=value), self.assertRaises(m.OperatorError):
                replace(self.config, registry_root=value)

    def test_repository_paths_refused(self):
        with self.assertRaises(m.OperatorError):
            replace(self.config, secret_file=m.PROJECT_ROOT / "demo.env")

    def test_overlapping_private_roots_refused(self):
        for changes in ({"observability_root": self.config.registry_root / "nested"},
                        {"secret_file": self.config.observability_root / "secret"}):
            with self.assertRaises(m.OperatorError):
                replace(self.config, **changes)

    def test_explicit_utc_clock(self):
        self.assertEqual(m.milliseconds(utc(123)), 123)
        for value in (datetime.now(), datetime.now(timezone(timedelta(hours=1))), None):
            with self.assertRaises(m.OperatorError):
                m.milliseconds(value)


class HostGateTests(unittest.TestCase):
    def check_host(self, *, lid=True, ac=True, console=True, alive=True, assertion=True):
        child = NS(pid=123, poll=lambda: None if alive else 1)
        outputs = [NS(stdout='"AppleClamshellState" = ' + ("No" if lid else "Yes")),
                   NS(stdout="Now drawing from '" + ("AC Power" if ac else "Battery Power") + "'"),
                   NS(stdout="   pid " + ("123" if assertion else "124")
                      + "(caffeinate): [TEST_ONLY] PreventUserIdleSystemSleep")]
        self.commands = Mock(side_effect=outputs)
        with patch.object(m.subprocess,"run",self.commands), \
             patch.object(m.Path,"stat",return_value=NS(st_uid=os.getuid() if console else os.getuid()+1)):
            m._host_ready(child)

    def test_lid_failure_has_specific_static_code(self):
        with self.assertRaisesRegex(m.OperatorError,"^LID_GATE_FAILED$"):
            self.check_host(lid=False)

    def test_ac_failure_has_specific_static_code(self):
        with self.assertRaisesRegex(m.OperatorError,"^AC_POWER_GATE_FAILED$"):
            self.check_host(ac=False)
        self.assertEqual(self.commands.call_count,3)  # No retry or additional sleep.

    def test_console_failure_has_specific_static_code(self):
        with self.assertRaisesRegex(m.OperatorError,"^CONSOLE_USER_GATE_FAILED$"):
            self.check_host(console=False)

    def test_dead_child_refuses_before_host_commands(self):
        with self.assertRaisesRegex(m.OperatorError,"^SLEEP_PREVENTION_UNAVAILABLE$"):
            self.check_host(alive=False)
        self.commands.assert_not_called()

    def test_assertion_failure_has_unchanged_static_code(self):
        with self.assertRaisesRegex(m.OperatorError,"^SLEEP_ASSERTION_NOT_CONFIRMED$"):
            self.check_host(assertion=False)

    def test_observed_caffeinate_line_shape_passes(self):
        self.check_host()
        self.assertEqual(self.commands.call_count,3)

    def test_host_acceptance_truth_table_is_unchanged(self):
        for lid,ac,console in itertools.product((False,True),repeat=3):
            with self.subTest(lid=lid,ac=ac,console=console):
                if lid and ac and console:
                    self.check_host(lid=lid,ac=ac,console=console)
                else:
                    with self.assertRaises(m.OperatorError):
                        self.check_host(lid=lid,ac=ac,console=console)


class SecretTests(PrivateCase):
    def setUp(self):
        super().setUp()
        self.config.secret_file.parent.mkdir(mode=0o700)
        self.text = "\n".join(name + "=<TEST_ONLY>" for name in sorted(m.SECRET_NAMES)) + "\n"
        self.write(self.text)

    def write(self, text):
        self.config.secret_file.write_text(text)
        self.config.secret_file.chmod(0o600)

    def test_exact_four_names_explicit_mapping_and_redacted_repr(self):
        values = m.load_demo_secret_file(self.config.secret_file)
        self.assertEqual(set(values), m.SECRET_NAMES)
        self.assertEqual(values["BYBIT_DEMO_API_KEY"], "<TEST_ONLY>")
        self.assertNotIn("<TEST_ONLY>", repr(values))
        credentials = m.load_bybit_demo_credentials(values)
        self.assertNotIn("<TEST_ONLY>", repr(credentials))

    def test_quoted_data_comments_and_empty_lines(self):
        self.write("# non-secret comment\n\n" + self.text.replace("<TEST_ONLY>", "'<TEST_ONLY>'"))
        self.assertEqual(len(m.load_demo_secret_file(self.config.secret_file)), 4)

    def test_unknown_duplicate_missing_and_malformed(self):
        cases = (self.text + "UNKNOWN=<TEST_ONLY>\n", self.text + self.text,
                 self.text.splitlines()[0], "malformed", self.text.replace("=", "= ", 1),
                 self.text.replace("<TEST_ONLY>", ""), self.text.replace("<TEST_ONLY>", "a b"),
                 self.text.replace("<TEST_ONLY>", "$(no-evaluation)"),
                 self.text.replace("<TEST_ONLY>", "`no-evaluation`"), " " + self.text)
        for text in cases:
            self.write(text)
            with self.subTest(case=cases.index(text)), self.assertRaises(m.OperatorError) as error:
                m.load_demo_secret_file(self.config.secret_file)
            self.assertEqual(str(error.exception), "SECRET_FILE_REFUSED")
            self.assertNotIn("<TEST_ONLY>", str(error.exception))

    def test_unsafe_file_permissions(self):
        self.config.secret_file.chmod(0o644)
        with self.assertRaises(m.OperatorError):
            m.load_demo_secret_file(self.config.secret_file)

    def test_unsafe_parent_permissions(self):
        self.config.secret_file.parent.chmod(0o755)
        with self.assertRaises(m.OperatorError):
            m.load_demo_secret_file(self.config.secret_file)

    def test_symlink_file(self):
        other = self.config.secret_file.with_name("original")
        self.config.secret_file.rename(other)
        self.config.secret_file.symlink_to(other)
        with self.assertRaises(m.OperatorError):
            m.load_demo_secret_file(self.config.secret_file)

    def test_symlink_ancestor(self):
        alias = self.root / "alias"
        alias.symlink_to(self.config.secret_file.parent, target_is_directory=True)
        with self.assertRaises(m.OperatorError):
            m.load_demo_secret_file(alias / "demo.env")

    def test_hardlink(self):
        os.link(self.config.secret_file, self.root / "second-name")
        with self.assertRaises(m.OperatorError):
            m.load_demo_secret_file(self.config.secret_file)

    def test_wrong_owner(self):
        with patch.object(m.os, "getuid", return_value=os.getuid() + 1):
            with self.assertRaises(m.OperatorError):
                m.load_demo_secret_file(self.config.secret_file)

    def test_missing_file_no_discovery(self):
        self.config.secret_file.unlink()
        with patch.dict(os.environ, {name: "<TEST_ONLY>" for name in m.SECRET_NAMES}):
            with self.assertRaises(m.OperatorError):
                m.load_demo_secret_file(self.config.secret_file)

    def test_invalid_utf8_redacted(self):
        self.config.secret_file.write_bytes(b"\xff")
        with self.assertRaisesRegex(m.OperatorError, "^SECRET_FILE_REFUSED$"):
            m.load_demo_secret_file(self.config.secret_file)


class IdentityTests(PrivateCase):
    def setUp(self):
        super().setUp()
        self.config.registry_root.mkdir(mode=0o700)
        self.lock = self.enterContext(RuntimeAccountLock(self.config.registry_root, "demo-main"))
        store = RuntimeStore.open(self.lock, durable(), initialize=True)  # Temporary fixture only.
        store.close()

    def test_readonly_identity_preserves_opaque_digests_and_bytes(self):
        before = self.lock.database_path.read_bytes()
        recovered = m._read_existing_configuration(self.lock)
        self.assertEqual(recovered, durable())
        self.assertEqual(self.lock.database_path.read_bytes(), before)
        self.assertEqual(recovered.configuration_digest, "b" * 64)
        self.assertEqual(recovered.strategy_implementation_digest, "a" * 64)

    def test_identity_requires_held_lock(self):
        other = RuntimeAccountLock(self.config.registry_root, "demo-main")
        with self.assertRaises(RuntimeLockError):
            m._read_existing_configuration(other)

    def test_duplicate_canonical_lock_fails(self):
        other = RuntimeAccountLock(self.config.registry_root, "demo-main")
        with self.assertRaises(RuntimeLockError):
            other.acquire()

    def test_profile_mismatch_refused_without_write(self):
        with patch.dict(m._RUNTIME_PROFILE, {"max_clock_skew_ms": 1000}):
            with self.assertRaises(m.OperatorError):
                m._read_existing_configuration(self.lock)

    def test_sidecar_requires_owner_review(self):
        self.lock.database_path.with_name("runtime.sqlite3-journal").touch()
        with self.assertRaises(m.OperatorError):
            m._read_existing_configuration(self.lock)

    def test_missing_database_never_initialized(self):
        self.lock.database_path.unlink()
        with self.assertRaises(FileNotFoundError):
            m._read_existing_configuration(self.lock)
        self.assertFalse(self.lock.database_path.exists())


class ClockHistoryTests(unittest.TestCase):
    def setUp(self):
        self.config = durable()
        self.now = lambda: utc(BOUNDARY + 8000)
        self.candles = tuple(MarketCandle("BTCUSDT", "60", i * H,
            D("100"), D("110"), D("90"), D("105"), D("1")) for i in range(10))
        self.prefix = ClosedCandlePrefix("BTCUSDT", "60", 0, BOUNDARY,
                                        BOUNDARY + 8000, BOUNDARY + 8000, self.candles)
        self.checkpoint = NS(last_processed_candle_ms=7 * H, last_reconciled_at_ms=BOUNDARY + 8000,
                             bootstrap_until_ms=2 * H, replay_until_ms=7 * H)
        self.store = NS(get_checkpoint=lambda: self.checkpoint,
                        get_candle=lambda at: self.candles[at // H])
        self.reader = Mock()
        self.reader.get_closed_candles.return_value = self.prefix

    def history(self):
        m._history_gate(self.reader, self.store, self.config, BOUNDARY, 24, self.now)

    def test_clock_accepts_inclusive_6000_boundary(self):
        self.reader.get_server_time.return_value = BOUNDARY + 14_000
        m._clock_gate(self.reader, self.config, self.now, lambda: 1.0)
        self.reader.get_server_time.assert_called_once_with()

    def test_clock_skew_failure_no_retry(self):
        self.reader.get_server_time.return_value = BOUNDARY + 14_001
        with self.assertRaises(m.OperatorError):
            m._clock_gate(self.reader, self.config, self.now, lambda: 1.0)
        self.reader.get_server_time.assert_called_once_with()

    def test_clock_malformed_and_monotonic_invalid(self):
        for value in (True, None, -1):
            self.reader.get_server_time.return_value = value
            with self.assertRaises(m.OperatorError):
                m._clock_gate(self.reader, self.config, self.now, lambda: 1.0)
        with self.assertRaises(m.OperatorError):
            m._clock_gate(self.reader, self.config, self.now, lambda: float("nan"))

    def test_clock_discontinuity_refused(self):
        self.reader.get_server_time.return_value = BOUNDARY + 8000
        with self.assertRaises(m.OperatorError):
            m._clock_gate(self.reader, self.config, self.now, Mock(side_effect=[1.0, 9.0]))

    def test_complete_fresh_overlap_passes(self):
        self.history()
        self.reader.get_closed_candles.assert_called_once()

    def test_conflicting_overlap_refused(self):
        self.store.get_candle = lambda at: replace(self.candles[at // H], close=D("101"))
        with self.assertRaises(m.OperatorError):
            self.history()

    def test_missing_overlap_refused(self):
        self.store.get_candle = lambda at: None
        with self.assertRaises(m.OperatorError):
            self.history()

    def test_stale_local_history_refused(self):
        self.now = lambda: utc(BOUNDARY + 60_001)
        with self.assertRaises(m.OperatorError):
            self.history()

    def test_stale_reconciliation_refused(self):
        self.checkpoint.last_reconciled_at_ms = BOUNDARY - 60_000
        with self.assertRaises(m.OperatorError):
            self.history()

    def test_single_unprotected_startup_candle_refused(self):
        self.checkpoint.last_processed_candle_ms = 8 * H
        with self.assertRaises(m.OperatorError):
            self.history()

    def test_single_preclassified_replay_candle_accepted(self):
        self.checkpoint.last_processed_candle_ms = 8 * H
        self.checkpoint.replay_until_ms = 9 * H
        self.history()

    def test_no_backlog_accepted(self):
        self.checkpoint.last_processed_candle_ms = 9 * H
        self.history()

    def test_wrong_history_boundary_refused(self):
        self.reader.get_closed_candles.return_value = replace(self.prefix, symbol="ETHUSDT",
            candles=tuple(replace(c, symbol="ETHUSDT") for c in self.candles))
        with self.assertRaises(m.OperatorError):
            self.history()


class FakeStop:
    def __init__(self, clock):
        self.clock, self.requested, self.set_count = clock, False, 0

    def is_set(self):
        return self.requested

    def set(self):
        self.requested = True
        self.set_count += 1

    def wait(self, seconds):
        self.clock[0] += int(seconds * 1000)
        return self.requested


class OrchestrationTests(PrivateCase):
    def setUp(self):
        super().setUp()
        self.calls = []
        self.clock = [BOUNDARY - 20_000]
        self.stop = FakeStop(self.clock)
        self.stack = self.enterContext(ExitStack())
        # Accidental requests are a hard test failure, not a connection attempt.
        self.stack.enter_context(patch("requests.sessions.Session.request", side_effect=AssertionError("NETWORK")))
        self.mocks = {}
        def fake(name, returned=None, side_effect=None):
            def call(*args, **kwargs):
                self.calls.append(name)
                return side_effect(*args, **kwargs) if side_effect else returned
            mock = self.stack.enter_context(patch.object(m, name, side_effect=call))
            self.mocks[name] = mock
            return mock
        self.child = NS(pid=123, poll=lambda: None,
            terminate=lambda: self.calls.append("child.terminate"), wait=lambda **k: self.calls.append("child.wait"))
        self.lock = NS(lock_path=self.root / "locks/fixture.lock",
            database_path=self.root / "accounts/fixture/runtime.sqlite3",
            acquire=lambda: self.calls.append("lock.acquire"), release=lambda: self.calls.append("lock.release"))
        self.snapshot = NS(state=RuntimeState.FLAT, stopped_from=None, pending_action=None,
                           owned_base_quantity=D("0"), position_evidence=PositionEvidence.CONFIRMED, reason=None)
        self.checkpoint = NS(snapshot=self.snapshot, halted_at_ms=None, sequence=7)
        self.risk = NS(**m._RISK_PROFILE, risk_configuration_digest="r")
        self.epoch = NS(risk_configuration_digest="r", epoch_id="e")
        self.valuation = NS(epoch_id="e", trip_reason=None, trip_pending_report=False)
        self.store = NS(get_configuration=lambda: durable(), get_checkpoint=lambda: self.checkpoint,
            list_actions=lambda: (), get_risk_configuration=lambda: self.risk,
            get_current_risk_epoch=lambda: self.epoch, get_latest_risk_valuation=lambda: self.valuation,
            close=lambda: self.calls.append("store.close"))
        self.client = NS(trust_env=True, verify=True, auth=None, proxies={},
                         close=lambda: self.calls.append("client.close"))
        self.session = NS(client=self.client, logger=NS(disabled=True))
        self.telegram = NS(close=lambda: self.calls.append("telegram.close"))
        fake("_caffeinate", self.child)
        fake("_host_ready")
        fake("private_directory")
        fake("RuntimeAccountLock", self.lock)
        fake("_read_existing_configuration", durable())
        self.open = self.stack.enter_context(patch.object(m.RuntimeStore, "open", side_effect=lambda *a, **k:
            (self.calls.append("store.open"), self.store)[1]))
        fake("prepare_process_restart")
        fake("load_demo_secret_file", m._Secrets({name: "<TEST_ONLY>" for name in m.SECRET_NAMES}))
        fake("create_bybit_demo_session", self.session)
        fake("BybitDemoReadOnlyAdapter", object())
        fake("BybitDemoOrderAdapter", object())
        fake("BybitPublicMarketReader", object())
        fake("ObservabilityStorage", object())
        fake("TelegramHttpTransport", NS())
        fake("TelegramDeliveryStore", object())
        self.stack.enter_context(patch.object(m.requests, "Session", return_value=self.telegram))
        fake("reconcile_startup", NS(checkpoint=self.checkpoint))
        fake("_clock_gate")
        fake("_history_gate")
        fake("run_observed_hourly_scheduler", SchedulerResult(self.checkpoint, SchedulerExit.STOP_REQUESTED, 2, 1))
        fake("_deadline_thread", NS(join=lambda: self.calls.append("controller.join")))

    def run_operator(self):
        return m.run_demo_runtime(self.config, utc_now=lambda: utc(self.clock[0]), stop_event=self.stop)

    def test_ordering_and_one_canonical_scheduler(self):
        result = self.run_operator()
        self.assertEqual(result.exit_code, 0)
        order = ["lock.acquire", "_read_existing_configuration", "store.open", "prepare_process_restart",
                 "load_demo_secret_file", "create_bybit_demo_session", "reconcile_startup",
                 "_clock_gate", "_history_gate", "run_observed_hourly_scheduler"]
        self.assertEqual(sorted(order, key=self.calls.index), order)
        self.open.assert_called_once_with(self.lock, durable(), initialize=False)
        self.mocks["prepare_process_restart"].assert_called_once_with(self.store)
        self.mocks["run_observed_hourly_scheduler"].assert_called_once()
        self.assertEqual(result.stop_deadline_ms, BOUNDARY + 24 * H + 90_000)
        self.assertLess(self.calls.index("store.close"), self.calls.index("lock.release"))
        self.assertLess(self.calls.index("telegram.close"), self.calls.index("store.close"))
        self.assertLess(self.calls.index("client.close"), self.calls.index("store.close"))
        self.assertLess(self.calls.index("lock.release"), self.calls.index("child.wait"))

    def test_nothing_operational_before_boundary(self):
        def lock(*args, **kwargs):
            self.assertGreaterEqual(self.clock[0], BOUNDARY)
            self.calls.append("lock.acquire")
        self.lock.acquire = lock
        self.run_operator()

    def test_pre_activation_stop_no_lock_store_or_credentials(self):
        self.stop.set()
        result = self.run_operator()
        self.assertEqual(result.code, "STOPPED_BEFORE_ACTIVATION")
        self.mocks["RuntimeAccountLock"].assert_not_called()
        self.open.assert_not_called()
        self.mocks["load_demo_secret_file"].assert_not_called()

    def test_lock_failure_no_external_resources(self):
        self.lock.acquire = Mock(side_effect=RuntimeLockError("<TEST_ONLY>"))
        result = self.run_operator()
        self.assertEqual(result.code, "FAILED_LOCK")
        self.open.assert_not_called()
        self.mocks["load_demo_secret_file"].assert_not_called()
        self.mocks["create_bybit_demo_session"].assert_not_called()
        self.assertNotIn("lock.release", self.calls)

    def test_missing_store_refuses_without_resources(self):
        self.open.side_effect = RuntimeError("<TEST_ONLY>")
        result = self.run_operator()
        self.assertEqual(result.code, "FAILED_STORE")
        self.mocks["prepare_process_restart"].assert_not_called()
        self.mocks["load_demo_secret_file"].assert_not_called()

    def test_halted_refuses_and_preserves(self):
        self.snapshot.state = RuntimeState.HALTED
        self.assertEqual(self.run_operator().code, "REFUSED_RISK_AND_STATE")
        self.mocks["prepare_process_restart"].assert_not_called()
        self.mocks["run_observed_hourly_scheduler"].assert_not_called()
        self.assertIs(self.snapshot.state, RuntimeState.HALTED)

    def test_uncertain_refuses(self):
        self.snapshot.state = RuntimeState.UNCERTAIN
        self.run_operator()
        self.mocks["run_observed_hourly_scheduler"].assert_not_called()

    def test_pending_refuses(self):
        self.snapshot.pending_action = object()
        self.run_operator()
        self.mocks["prepare_process_restart"].assert_not_called()

    def test_nonterminal_journal_refuses(self):
        self.store.list_actions = lambda: (NS(phase=m.ActionPhase.ATTEMPT_STARTED),)
        self.run_operator()
        self.mocks["prepare_process_restart"].assert_not_called()

    def test_risk_mismatch_refuses(self):
        self.risk.risk_capital_quote = D("101")
        self.run_operator()
        self.mocks["prepare_process_restart"].assert_not_called()

    def test_risk_trip_preserved_without_rearm(self):
        self.valuation.trip_reason = "LATCHED"
        self.run_operator()
        self.assertEqual(self.valuation.trip_reason, "LATCHED")
        self.mocks["prepare_process_restart"].assert_not_called()

    def test_restart_uncertainty_no_followup(self):
        self.mocks["prepare_process_restart"].side_effect = RuntimeError("<TEST_ONLY>")
        result = self.run_operator()
        self.assertEqual(result.code, "UNCERTAIN")
        self.mocks["load_demo_secret_file"].assert_not_called()
        self.mocks["reconcile_startup"].assert_not_called()

    def test_reconciled_long_accepted(self):
        self.snapshot.state = RuntimeState.LONG
        self.assertEqual(self.run_operator().exit_code, 0)

    def test_reconciliation_refusals_prevent_scheduler(self):
        for state in (RuntimeState.HALTED, RuntimeState.UNCERTAIN):
            self.mocks["reconcile_startup"].side_effect = lambda *a, **k: NS(checkpoint=NS(snapshot=
                NS(state=state, position_evidence=PositionEvidence.CONFIRMED, pending_action=None, reason=None)))
            self.run_operator()
            self.mocks["run_observed_hourly_scheduler"].assert_not_called()

    def test_clock_failure_no_retry_or_scheduler(self):
        self.mocks["_clock_gate"].side_effect = m.OperatorError("<TEST_ONLY>")
        result = self.run_operator()
        self.assertEqual(result.code, "REFUSED_CLOCK")
        self.mocks["_clock_gate"].assert_called_once()
        self.mocks["_history_gate"].assert_not_called()
        self.mocks["run_observed_hourly_scheduler"].assert_not_called()

    def test_history_failure_prevents_scheduler(self):
        self.mocks["_history_gate"].side_effect = RuntimeError("<TEST_ONLY>")
        self.run_operator()
        self.mocks["run_observed_hourly_scheduler"].assert_not_called()

    def test_scheduler_exception_no_reopen_or_restart_or_resend(self):
        self.mocks["run_observed_hourly_scheduler"].side_effect = RuntimeError("<TEST_ONLY>")
        result = self.run_operator()
        self.assertEqual(result.code, "UNCERTAIN")
        self.assertNotIn("<TEST_ONLY>", repr(result))
        self.open.assert_called_once()
        self.mocks["prepare_process_restart"].assert_called_once()
        self.mocks["reconcile_startup"].assert_called_once()
        self.mocks["run_observed_hourly_scheduler"].assert_called_once()

    def test_sink_workers_finish_before_clients_store_and_lock_close(self):
        worker = Mock(name="worker")
        worker.name = "trading-lab-observability"
        worker.is_alive.side_effect = [True, False]
        worker.join.side_effect = lambda **kw: self.calls.append("sink.join")
        with patch.object(m.threading, "enumerate", side_effect=[[], [worker]]):
            self.run_operator()
        self.assertLess(self.calls.index("sink.join"), self.calls.index("telegram.close"))

    def test_cleanup_failure_returns_failure_and_attempts_remaining_closes(self):
        self.client.close = Mock(side_effect=RuntimeError("<TEST_ONLY>"))
        result = self.run_operator()
        self.assertFalse(result.cleanup_ok)
        self.assertEqual(result.exit_code, 1)
        self.assertIn("store.close", self.calls)
        self.assertIn("child.wait", self.calls)

    def test_parent_identity_is_never_consulted(self):
        with patch.object(m.os, "getppid", side_effect=AssertionError("PARENT")):
            self.assertEqual(self.run_operator().exit_code, 0)

    def test_all_allowlisted_preparation_details_are_preserved(self):
        self.assertIs(type(m._PREPARATION_FAILURE_CODES),frozenset)
        for code in m._PREPARATION_FAILURE_CODES:
            with self.subTest(code=code):
                self.mocks["_host_ready"].side_effect = m.OperatorError(code)
                result = self.run_operator()
                self.assertEqual(result.code,"REFUSED_PREPARATION")
                self.assertEqual(result.failure_code,code)
        self.mocks["load_demo_secret_file"].assert_not_called()
        self.mocks["RuntimeAccountLock"].assert_not_called()

    def test_utc_validation_detail_uses_same_safe_surface(self):
        result = m.run_demo_runtime(self.config,utc_now=lambda: None,stop_event=self.stop)
        self.assertEqual(result.failure_code,"AWARE_UTC_CLOCK_REQUIRED")
        self.mocks["_caffeinate"].assert_not_called()

    def test_non_allowlisted_operator_error_stays_generic(self):
        self.mocks["_host_ready"].side_effect = m.OperatorError("<SYNTHETIC_SECRET_DO_NOT_EMIT>")
        result = self.run_operator()
        self.assertEqual(result.code,"REFUSED_PREPARATION")
        self.assertIsNone(result.failure_code)
        self.assertNotIn("<SYNTHETIC_SECRET_DO_NOT_EMIT>",repr(result))

    def test_other_exception_with_allowlisted_text_stays_generic(self):
        self.mocks["_host_ready"].side_effect = RuntimeError("AC_POWER_GATE_FAILED")
        result = self.run_operator()
        self.assertEqual(result.code,"FAILED_PREPARATION")
        self.assertIsNone(result.failure_code)

    def test_detail_not_propagated_from_later_stages(self):
        self.mocks["_history_gate"].side_effect = m.OperatorError("AC_POWER_GATE_FAILED")
        result = self.run_operator()
        self.assertEqual(result.code,"REFUSED_HISTORY")
        self.assertIsNone(result.failure_code)

    def test_failure_field_rejects_arbitrary_or_wrong_scope_data(self):
        for value in ("<SYNTHETIC_SECRET_DO_NOT_EMIT>",True,[],"",1):
            with self.assertRaisesRegex(m.OperatorError,"^INVALID_PREPARATION_FAILURE_CODE$"):
                m.DemoRuntimeResult("REFUSED_PREPARATION",1,failure_code=value)
        with self.assertRaises(m.OperatorError):
            m.DemoRuntimeResult("FAILED_STORE",1,failure_code="AC_POWER_GATE_FAILED")

    def test_cli_emits_only_allowlisted_failure_detail(self):
        args = ["--registry-root",str(self.config.registry_root),"--observability-root",
                str(self.config.observability_root),"--secret-file",str(self.config.secret_file),
                "--duration-hours","24","--start-next-hour","--confirm-demo-runtime"]
        for error,expected in ((m.OperatorError("AC_POWER_GATE_FAILED"),"AC_POWER_GATE_FAILED"),
                               (m.OperatorError("<SYNTHETIC_SECRET_DO_NOT_EMIT>"),None),
                               (RuntimeError("<SYNTHETIC_SECRET_DO_NOT_EMIT>"),None)):
            self.mocks["_host_ready"].side_effect = error
            output,errors = io.StringIO(),io.StringIO()
            with patch("sys.stdout",output),patch("sys.stderr",errors):
                self.assertEqual(m.runtime_main(args),1)
            self.assertEqual(json.loads(output.getvalue())["failure_code"],expected)
            self.assertNotIn("<SYNTHETIC_SECRET_DO_NOT_EMIT>",output.getvalue()+errors.getvalue())


class ControlTests(unittest.TestCase):
    def test_sigterm_handler_only_sets_event(self):
        self.check_signal(signal.SIGTERM)

    def test_sigint_handler_only_sets_event(self):
        self.check_signal(signal.SIGINT)

    def check_signal(self, kind):
        handlers, stop = {}, Mock()
        def install(key, handler):
            old = handlers.get(key, signal.SIG_DFL)
            handlers[key] = handler
            return old
        with patch.object(m.signal, "signal", side_effect=install):
            with m._stop_handlers(stop):
                handlers[kind](kind, None)
                stop.set.assert_called_once_with()
            self.assertIs(handlers[kind], signal.SIG_DFL)

    def test_deadline_sets_stop_once(self):
        stop, cancel = Mock(), Mock()
        stop.is_set.return_value = cancel.is_set.return_value = False
        m._deadline_worker(1000, stop, cancel, lambda: utc(1000))
        stop.set.assert_called_once_with()

    def test_controller_non_daemon(self):
        with patch.object(m.threading, "Thread") as thread:
            m._deadline_thread(1000, Mock(), Mock(), lambda: utc(0))
        self.assertFalse(thread.call_args.kwargs["daemon"])
        thread.return_value.start.assert_called_once()

    def test_clock_failure_stops_instead_of_losing_controller(self):
        stop, cancel = Mock(), Mock()
        stop.is_set.return_value = cancel.is_set.return_value = False
        m._deadline_worker(1000, stop, cancel, lambda: None)
        stop.set.assert_called_once_with()

    def test_cancelled_controller_does_not_set_stop(self):
        stop, cancel = Mock(), Mock()
        cancel.is_set.return_value = True
        m._deadline_worker(1000, stop, cancel, lambda: utc(1000))
        stop.set.assert_not_called()

    def test_no_business_mutation_calls_in_operator(self):
        tree = ast.parse(inspect.getsource(m))
        names = {node.func.attr for node in ast.walk(tree)
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
        forbidden = {"place_order", "cancel_order", "start_attempt", "commit_decision",
            "save_checkpoint", "rearm_risk_epoch", "rearm_runtime_halt", "initialize_risk_journal",
            "migrate_v1_to_v2", "run_single_cycle", "generate_signals"}
        self.assertFalse(names & forbidden)

    def test_cli_error_does_not_echo_rejected_arguments(self):
        output = io.StringIO()
        with patch("sys.stderr", output), self.assertRaises(SystemExit):
            m.runtime_main(["--unknown=<TEST_ONLY>"])
        self.assertNotIn("<TEST_ONLY>", output.getvalue())


if __name__ == "__main__":
    unittest.main()
