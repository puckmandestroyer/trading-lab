"""One owner-invoked Demo process, independent of its terminal or chat session.

This module owns lifecycle and safety gates. The frozen runtime alone owns
signals, authorization, orders, reconciliation, accounting and shutdown writes.
"""

import argparse
from collections.abc import Mapping
from contextlib import closing, contextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
import json
import math
import os
from pathlib import Path
import re
import shlex
import signal
import sqlite3
import stat
import subprocess
import threading
import time

import requests

from ..data.closed_candles import ClosedCandlePrefix, MAX_CANDLES, validate_candle_freshness
from ..exchange.bybit_demo import create_bybit_demo_session, load_bybit_demo_credentials
from ..exchange.bybit_demo_orders import BybitDemoOrderAdapter
from ..exchange.bybit_demo_read_only import BybitDemoReadOnlyAdapter
from ..exchange.bybit_public_market import BybitPublicMarketReader
from ..observability.runtime_integration import run_observed_hourly_scheduler
from ..observability.storage import ObservabilityStorage
from ..observability.telegram import TelegramDeliveryStore, TelegramHttpTransport
from ..runtime.locking import RuntimeAccountLock
from ..runtime.reconciliation import reconcile_startup
from ..runtime.recovery import prepare_process_restart
from ..runtime.scheduler import SchedulerExit, SchedulerResult
from ..runtime.state import PositionEvidence, RuntimeState
from ..runtime.store import ActionPhase, RuntimeConfiguration, RuntimeStore

HOUR_MS = 3_600_000
MAX_DURATION_HOURS = 72
PROJECT_ROOT = Path(__file__).resolve().parents[3]
SECRET_NAMES = frozenset(("BYBIT_DEMO_API_KEY", "BYBIT_DEMO_API_SECRET",
                          "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"))
_PROCESS_ENV = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LC_ALL": "C"}
_RUNTIME_PROFILE = {
    "broker_id": "bybit-demo", "account_binding": "demo-main", "bot_id": "bot1",
    "strategy_id": "ema_trend",
    "strategy_parameters": (("fast_span", 20), ("slow_span", 50), ("warmup_candles", 50)),
    "symbol": "BTCUSDT", "base_currency": "BTC", "quote_currency": "USDT",
    "timeframe": "60", "interval_ms": HOUR_MS, "buy_quote_budget": Decimal("10"),
    "decision_max_age_ms": 60_000, "observation_max_age_ms": 60_000,
    "max_clock_skew_ms": 6000, "request_timeout_ms": 10_000,
    "reconciliation_timeout_ms": 600_000, "reconciliation_round_limit": 5,
    "read_attempt_limit": 3, "schema_version": 2, "runtime_contract_version": 1,
    "broker_account_id": None,
}
_RISK_PROFILE = {
    "risk_capital_quote": Decimal("100"), "buy_quote_budget": Decimal("10"),
    "max_entry_notional_quote": Decimal("10"), "max_position_notional_quote": Decimal("10"),
    "max_daily_loss_fraction": Decimal("0.05"), "max_drawdown_fraction": Decimal("0.10"),
    "max_entries_per_utc_day": 3, "base_currency": "BTC", "quote_currency": "USDT",
}


class OperatorError(ValueError):
    """Fixed diagnostics only: never retain supplied values or external errors."""


class StartBoundary(str, Enum):
    NEXT_HOUR = "NEXT_HOUR"


def _require(condition, code):
    if not condition:
        raise OperatorError(code)


def absolute_path(path):
    """Validate a caller-supplied path without touching its filesystem yet."""
    _require(isinstance(path, Path) and path.is_absolute() and ".." not in path.parts,
             "ABSOLUTE_PATH_REQUIRED")
    _require(not any(ord(c) < 32 for c in str(path)), "CONTROL_CHARACTER_PATH_REFUSED")
    return path


@dataclass(frozen=True, slots=True)
class DemoRuntimeConfiguration:
    registry_root: Path
    observability_root: Path
    secret_file: Path
    duration_hours: int
    start_boundary: StartBoundary = StartBoundary.NEXT_HOUR
    broker_id: str = "bybit-demo"
    account_binding: str = "demo-main"
    bot_id: str = "bot1"
    strategy_id: str = "ema_trend"
    symbol: str = "BTCUSDT"

    def __post_init__(self):
        for path in (self.registry_root, self.observability_root, self.secret_file):
            absolute_path(path)
            _require(not path.is_relative_to(PROJECT_ROOT), "PRIVATE_PATH_OUTSIDE_REPOSITORY_REQUIRED")
        _require(type(self.duration_hours) is int and 1 <= self.duration_hours <= MAX_DURATION_HOURS,
                 "BOUNDED_WHOLE_HOUR_DURATION_REQUIRED")
        _require(self.start_boundary is StartBoundary.NEXT_HOUR, "NEXT_HOUR_POLICY_REQUIRED")
        for name in ("broker_id", "account_binding", "bot_id", "strategy_id", "symbol"):
            _require(type(getattr(self, name)) is str and getattr(self, name) == _RUNTIME_PROFILE[name],
                     "CANONICAL_DEMO_IDENTITY_REQUIRED")
        _require(self.registry_root != self.observability_root
                 and not self.registry_root.is_relative_to(self.observability_root)
                 and not self.observability_root.is_relative_to(self.registry_root)
                 and not self.secret_file.is_relative_to(self.registry_root)
                 and not self.secret_file.is_relative_to(self.observability_root),
                 "SEPARATE_PRIVATE_RESOURCES_REQUIRED")


@dataclass(frozen=True, slots=True)
class DemoRuntimeResult:
    code: str
    exit_code: int
    start_boundary_ms: int | None = None
    stop_deadline_ms: int | None = None
    scheduler_exit: str | None = None
    checkpoint_sequence: int | None = None
    cycle_count: int = 0
    wake_count: int = 0
    cleanup_ok: bool = True


@dataclass(frozen=True, slots=True, repr=False)
class _Secrets(Mapping):
    _values: dict = field(repr=False)

    def __getitem__(self, key):
        return self._values[key]

    def __iter__(self):
        return iter(self._values)

    def __len__(self):
        return len(self._values)

    def __repr__(self):
        return "<DemoSecrets>"


def _no_symlinks(path):
    for part in (*reversed(path.parents), path):
        _require(not part.is_symlink(), "SYMLINK_PATH_REFUSED")


def private_directory(path, *, create=False):
    """Create one explicit private child, or reject unsafe existing storage."""
    absolute_path(path)
    _no_symlinks(path)
    if create and not path.exists():
        parent = path.parent.lstat()
        _require(stat.S_ISDIR(parent.st_mode) and parent.st_uid == os.getuid()
                 and stat.S_IMODE(parent.st_mode) == 0o700, "PRIVATE_PARENT_REQUIRED")
        path.mkdir(mode=0o700)
    info = path.lstat()
    _require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
             and stat.S_IMODE(info.st_mode) == 0o700, "PRIVATE_DIRECTORY_REQUIRED")


def private_file(path, *, maximum):
    _no_symlinks(path)
    info = path.lstat()
    _require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
             and stat.S_IMODE(info.st_mode) == 0o600 and info.st_nlink == 1
             and 0 <= info.st_size <= maximum, "PRIVATE_REGULAR_FILE_REQUIRED")
    return info


def load_demo_secret_file(path):
    """Read exactly four assignment names; no shell evaluation or discovery."""
    try:
        absolute_path(path)
        _require(not path.is_relative_to(PROJECT_ROOT), "SECRET_OUTSIDE_REPOSITORY_REQUIRED")
        private_directory(path.parent)
        before = private_file(path, maximum=65_536)
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "rb") as handle:
            opened = os.fstat(handle.fileno())
            _require((opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
                     == (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns),
                     "SECRET_SOURCE_CHANGED")
            raw = handle.read(65_537)
            after = os.fstat(handle.fileno())
            _require((after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
                     == (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
                     and len(raw) <= 65_536, "SECRET_SOURCE_CHANGED")
        values = {}
        for line in raw.decode("utf-8").splitlines():
            if not line or line.startswith("#"):
                continue
            _require(line == line.strip() and "=" in line, "INVALID_SECRET_ASSIGNMENT")
            name, value = line.split("=", 1)
            _require(name in SECRET_NAMES and name not in values
                     and value == value.strip() and bool(value), "INVALID_SECRET_ASSIGNMENT")
            # Quoting is assignment data. No expansion, export, comments or eval.
            tokens = shlex.split(value, comments=False, posix=True)
            _require(len(tokens) == 1 and tokens[0] and tokens[0] == tokens[0].strip()
                     and not any(c.isspace() for c in tokens[0])
                     and not any(c in tokens[0] for c in ("$", "`", "\x00")),
                     "INVALID_SECRET_ASSIGNMENT")
            values[name] = tokens[0]
        _require(set(values) == SECRET_NAMES, "REQUIRED_SECRET_NAMES_MISSING")
        return _Secrets(values)
    except Exception:
        raise OperatorError("SECRET_FILE_REFUSED") from None


def _utc_now():
    return datetime.now(timezone.utc)


def milliseconds(value):
    _require(isinstance(value, datetime) and value.tzinfo is not None
             and value.utcoffset() == timedelta(0), "AWARE_UTC_CLOCK_REQUIRED")
    delta = value - datetime(1970, 1, 1, tzinfo=timezone.utc)
    result = (delta.days * 86400 + delta.seconds) * 1000 + delta.microseconds // 1000
    _require(0 <= result <= 2**63 - 1, "UTC_CLOCK_OUT_OF_RANGE")
    return result


@contextmanager
def _stop_handlers(stop_event):
    def request_stop(signum, frame):
        stop_event.set()
    previous = {}
    try:
        for kind in (signal.SIGTERM, signal.SIGINT):
            previous[kind] = signal.signal(kind, request_stop)
        yield
    finally:
        for kind, handler in previous.items():
            signal.signal(kind, handler)


def _deadline_worker(deadline_ms, stop_event, cancelled, utc_now):
    try:
        while not cancelled.is_set() and not stop_event.is_set():
            remaining = (deadline_ms - milliseconds(utc_now())) / 1000
            if remaining <= 0:
                stop_event.set()
                return
            cancelled.wait(min(1.0, remaining))
    except BaseException:
        # An invalid control clock cannot leave an unbounded trading process.
        stop_event.set()


def _deadline_thread(deadline_ms, stop_event, cancelled, utc_now):
    worker = threading.Thread(target=_deadline_worker, name="trading-lab-operator-deadline",
                              args=(deadline_ms, stop_event, cancelled, utc_now), daemon=False)
    worker.start()
    return worker


def _caffeinate():
    child = subprocess.Popen(["/usr/bin/caffeinate", "-i", "-w", str(os.getpid())],
                             shell=False, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, env=_PROCESS_ENV)
    time.sleep(0.25)  # One bounded assertion-registration wait, not a retry loop.
    return child


def _host_ready(child):
    _require(child.poll() is None, "SLEEP_PREVENTION_UNAVAILABLE")
    def output(*arguments):
        return subprocess.run(arguments, shell=False, capture_output=True, text=True,
                              timeout=5, check=True, env=_PROCESS_ENV).stdout
    lid = output("/usr/sbin/ioreg", "-r", "-n", "IOPMrootDomain", "-d", "1")
    power = output("/usr/bin/pmset", "-g", "batt")
    assertions = output("/usr/bin/pmset", "-g", "assertions")
    _require(re.search(r'"AppleClamshellState"\s*=\s*No', lid) is not None
             and "'AC Power'" in power and Path("/dev/console").stat().st_uid == os.getuid(),
             "LID_POWER_OR_CONSOLE_GATE_FAILED")
    _require(re.search(r"^\s*pid\s+" + str(child.pid)
                       + r"\(caffeinate\):[^\n]*\bPreventUserIdleSystemSleep\b",
                       assertions, re.MULTILINE) is not None, "SLEEP_ASSERTION_NOT_CONFIRMED")


def _read_existing_configuration(lock):
    """Bootstrap identity only, read-only, while the canonical lock is held.

    RuntimeStore.open requires its caller's configuration. Reuse the frozen
    decoder, then normal open/full validation; never derive either opaque digest.
    """
    from ..runtime.store import _decode, _MAX_DATABASE_BYTES
    lock._assert_held()
    path = lock.database_path
    for suffix in ("-journal", "-wal", "-shm"):
        sidecar = path.with_name(path.name + suffix)
        _require(not sidecar.exists() and not sidecar.is_symlink(), "OWNER_REVIEW_OF_SQLITE_SIDECAR_REQUIRED")
    before = private_file(path, maximum=_MAX_DATABASE_BYTES)
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True,
                                isolation_level=None, timeout=0)) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute("SELECT * FROM identity LIMIT 2").fetchall()
        _require(len(rows) == 1 and rows[0]["singleton"] == 1, "SINGLETON_IDENTITY_REQUIRED")
        configuration = _decode("identity", rows[0])
    after = private_file(path, maximum=_MAX_DATABASE_BYTES)
    _require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
             == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns), "IDENTITY_FILE_CHANGED")
    _require(type(configuration) is RuntimeConfiguration
             and all(getattr(configuration, name) == value for name, value in _RUNTIME_PROFILE.items()),
             "DURABLE_DEMO_PROFILE_MISMATCH")
    return configuration


def _startup_state(store):
    checkpoint = store.get_checkpoint()
    state = checkpoint.snapshot
    terminal = (ActionPhase.TERMINAL_CONFIRMED, ActionPhase.REJECTED, ActionPhase.ABANDONED_UNSENT)
    _require(state.state not in (RuntimeState.HALTED, RuntimeState.UNCERTAIN, RuntimeState.ORDER_PENDING)
             and state.stopped_from not in (RuntimeState.HALTED, RuntimeState.UNCERTAIN, RuntimeState.ORDER_PENDING)
             and checkpoint.halted_at_ms is None and state.pending_action is None
             and state.owned_base_quantity is not None
             and all(action.phase in terminal for action in store.list_actions()),
             "OWNER_REVIEW_OF_RUNTIME_STATE_REQUIRED")
    risk, epoch, valuation = (store.get_risk_configuration(), store.get_current_risk_epoch(),
                              store.get_latest_risk_valuation())
    _require(risk is not None and epoch is not None and valuation is not None
             and all(getattr(risk, name) == value for name, value in _RISK_PROFILE.items())
             and epoch.risk_configuration_digest == risk.risk_configuration_digest
             and valuation.epoch_id == epoch.epoch_id, "EXISTING_FROZEN_RISK_REQUIRED")
    # Decision 024's activation gate is distinct from a trip during a running
    # scheduler. During a run, Decisions 018/020 remain entirely unchanged.
    _require(valuation.trip_reason is None and not valuation.trip_pending_report,
             "OWNER_REVIEW_OF_RISK_TRIP_REQUIRED")
    return checkpoint


def _clock_gate(reader, configuration, utc_now, monotonic):
    before = milliseconds(utc_now())
    start = monotonic()
    server = reader.get_server_time()
    end = monotonic()
    _require(all(type(value) in (int, float) and math.isfinite(value) for value in (start, end)),
             "PUBLIC_CLOCK_INVALID")
    elapsed = end - start
    after = milliseconds(utc_now())
    _require(type(server) is int and server >= 0 and type(elapsed) in (int, float)
             and math.isfinite(elapsed) and elapsed >= 0 and after >= before,
             "PUBLIC_CLOCK_INVALID")
    maximum = configuration.max_clock_skew_ms
    _require(abs(server - (before + after) / 2) <= maximum
             and before - maximum <= server <= after + maximum
             and abs((after - before) - elapsed * 1000) <= maximum, "PUBLIC_CLOCK_GATE_FAILED")


def _history_gate(reader, store, configuration, boundary_ms, duration_hours, utc_now):
    before = milliseconds(utc_now())
    prefix = reader.get_closed_candles(symbol=configuration.symbol, timeframe=configuration.timeframe,
        history_anchor_ms=configuration.history_anchor_ms, max_data_age_ms=configuration.decision_max_age_ms)
    after = milliseconds(utc_now())
    _require(type(prefix) is ClosedCandlePrefix, "COMPLETE_CLOSED_HISTORY_REQUIRED")
    replace(prefix)
    for candle in prefix.candles:
        replace(candle)
    _require(prefix.symbol == configuration.symbol and prefix.timeframe == configuration.timeframe
             and prefix.history_anchor_ms == configuration.history_anchor_ms
             and prefix.end_ms == boundary_ms
             and prefix.end_ms == prefix.server_time_ms // HOUR_MS * HOUR_MS
             and len(prefix.candles) + duration_hours <= MAX_CANDLES
             and all(before - configuration.max_clock_skew_ms <= at <= after + configuration.max_clock_skew_ms
                     for at in (prefix.server_time_ms, prefix.observed_at_ms)), "HISTORY_CONTEXT_GATE_FAILED")
    _require(bool(prefix.candles), "CLOSED_HISTORY_REQUIRED")
    validate_candle_freshness(newest_closed_candle_open_ms=prefix.candles[-1].candle_open_ms,
        server_time_ms=prefix.observed_at_ms, max_data_age_ms=configuration.decision_max_age_ms)
    current = store.get_checkpoint()
    _require(current.last_processed_candle_ms is not None
             and current.last_processed_candle_ms < prefix.end_ms, "DURABLE_HISTORY_FRONTIER_REQUIRED")
    fields = ("symbol", "timeframe", "candle_open_ms", "open", "high", "low", "close", "volume")
    unseen = []
    for candle in prefix.candles:
        if candle.candle_open_ms <= current.last_processed_candle_ms:
            saved = store.get_candle(candle.candle_open_ms)
            _require(saved is not None and all(getattr(saved, name) == getattr(candle, name) for name in fields),
                     "DURABLE_PUBLIC_HISTORY_CONFLICT")
        else:
            unseen.append(candle)
    if len(unseen) == 1:
        cutoff = max(current.bootstrap_until_ms or -1, current.replay_until_ms or -1)
        _require(unseen[0].candle_open_ms <= cutoff, "SINGLE_CANDLE_STARTUP_REQUIRES_OWNER_REVIEW")
    now = milliseconds(utc_now())
    _require(boundary_ms <= now <= boundary_ms + 60_000
             and current.last_reconciled_at_ms is not None
             and 0 <= now - current.last_reconciled_at_ms <= configuration.observation_max_age_ms
             and 0 <= now - prefix.candles[-1].candle_close_ms <= configuration.decision_max_age_ms,
             "ACTIVATION_EVIDENCE_EXPIRED")


def _join_observability_workers(previous):
    # The frozen wrapper owns a two-second drain. Its timed-out daemon can still
    # use the sinks: keep the sessions/store/lock alive until it actually exits.
    for worker in threading.enumerate():
        if worker not in previous and worker.name == "trading-lab-observability":
            while worker.is_alive():
                worker.join(timeout=1.0)


def run_demo_runtime(configuration, *, utc_now=_utc_now, monotonic=time.monotonic, stop_event=None):
    """Run exactly one bounded observed scheduler; never install or self-restart."""
    _require(type(configuration) is DemoRuntimeConfiguration, "OPERATOR_CONFIGURATION_REQUIRED")
    replace(configuration)
    stop = threading.Event() if stop_event is None else stop_event
    _require(all(callable(getattr(stop, name, None)) for name in ("set", "is_set", "wait")),
             "STOP_EVENT_REQUIRED")
    cancelled = threading.Event()
    child = lock = store = session = telegram_session = controller = None
    secrets = transport = None
    previous_workers = set()
    entered_scheduler = persistence_begun = lock_acquired = False
    boundary = deadline = None
    result = DemoRuntimeResult("ACTIVATION_REFUSED", 1)
    cleanup_ok = True
    stage = "PREPARATION"
    handlers = _stop_handlers(stop)
    handlers_entered = False
    try:
        handlers.__enter__()
        handlers_entered = True
        boundary = (milliseconds(utc_now()) // HOUR_MS + 1) * HOUR_MS
        deadline = boundary + configuration.duration_hours * HOUR_MS + 90_000
        _require(deadline <= 2**63 - 1, "BOUNDED_DEADLINE_REQUIRED")
        child = _caffeinate()
        _host_ready(child)
        stage = "BOUNDARY_WAIT"
        while not stop.is_set():
            remaining = boundary + 8000 - milliseconds(utc_now())
            if remaining <= 0:
                break
            stop.wait(min(30.0, remaining / 1000))
        if stop.is_set():
            result = DemoRuntimeResult("STOPPED_BEFORE_ACTIVATION", 0, boundary, deadline)
        else:
            _host_ready(child)
            _require(boundary <= milliseconds(utc_now()) <= boundary + 60_000,
                     "ACTIVATION_WINDOW_MISSED")
            controller = _deadline_thread(deadline, stop, cancelled, utc_now)
            stage = "LOCK"
            private_directory(configuration.registry_root)
            private_directory(configuration.registry_root.parent)
            lock = RuntimeAccountLock(configuration.registry_root, configuration.account_binding,
                                      broker_id=configuration.broker_id)
            private_directory(lock.lock_path.parent, create=True)
            if lock.lock_path.exists() or lock.lock_path.is_symlink():
                private_file(lock.lock_path, maximum=4096)
            lock.acquire()
            lock_acquired = True
            private_directory(lock.database_path.parent.parent)
            private_directory(lock.database_path.parent)
            stage = "IDENTITY"
            durable = _read_existing_configuration(lock)
            stage = "STORE"
            store = RuntimeStore.open(lock, durable, initialize=False)
            _require(store.get_configuration() == durable, "DURABLE_CONFIGURATION_CHANGED")
            stage = "RISK_AND_STATE"
            _startup_state(store)
            stage = "RESTART"
            persistence_begun = True
            prepare_process_restart(store)
            _require(not stop.is_set(), "STOPPED_DURING_ACTIVATION")
            stage = "SECRETS"
            secrets = load_demo_secret_file(configuration.secret_file)
            stage = "RESOURCES"
            session = create_bybit_demo_session(load_bybit_demo_credentials(secrets))
            session.client.trust_env = False
            _require(session.client.verify is True and session.client.auth is None
                     and not session.client.proxies and session.logger.disabled,
                     "UNSAFE_DEMO_TRANSPORT")
            broker = BybitDemoReadOnlyAdapter(session)
            orders = BybitDemoOrderAdapter(session)
            market = BybitPublicMarketReader(timeout_seconds=durable.request_timeout_ms / 1000)
            private_directory(configuration.observability_root, create=True)
            storage = ObservabilityStorage(configuration.observability_root, durable)
            telegram_session = requests.Session()
            transport = TelegramHttpTransport(secrets["TELEGRAM_BOT_TOKEN"], secrets["TELEGRAM_CHAT_ID"],
                                              session=telegram_session)
            receipts = TelegramDeliveryStore(storage, secrets["TELEGRAM_CHAT_ID"])
            secrets = None
            stage = "RECONCILIATION"
            reconciled = reconcile_startup(store, broker, utc_now=utc_now, monotonic=monotonic)
            snapshot = reconciled.checkpoint.snapshot
            _require(snapshot.state in (RuntimeState.FLAT, RuntimeState.LONG)
                     and snapshot.position_evidence is PositionEvidence.CONFIRMED
                     and snapshot.pending_action is None and snapshot.reason is None,
                     "STARTUP_RECONCILIATION_REFUSED")
            _require(not stop.is_set(), "STOPPED_DURING_ACTIVATION")
            stage = "CLOCK"
            _clock_gate(market, durable, utc_now, monotonic)
            stage = "HISTORY"
            _history_gate(market, store, durable, boundary, configuration.duration_hours, utc_now)
            _require(not stop.is_set(), "STOPPED_DURING_ACTIVATION")
            previous_workers = set(threading.enumerate())
            stage = "SCHEDULER"
            entered_scheduler = True
            observed = run_observed_hourly_scheduler(store, market, broker, orders, stop,
                storage=storage, utc_now=utc_now, monotonic=monotonic,
                observability_now_ms=lambda: milliseconds(utc_now()),
                telegram_transport=transport, telegram_receipts=receipts)
            _require(type(observed) is SchedulerResult, "SCHEDULER_RESULT_INVALID")
            result = DemoRuntimeResult("SCHEDULER_RETURNED",
                0 if observed.exit_reason is SchedulerExit.STOP_REQUESTED else 1,
                boundary, deadline, observed.exit_reason.value, observed.checkpoint.sequence,
                observed.cycle_count, observed.wake_count)
    except OperatorError:
        result = DemoRuntimeResult("UNCERTAIN" if entered_scheduler or stage == "RESTART"
                                   else "REFUSED_" + stage, 1, boundary, deadline)
    except BaseException:
        result = DemoRuntimeResult("UNCERTAIN" if entered_scheduler or persistence_begun
                                   else "FAILED_" + stage, 1, boundary, deadline)
    finally:
        cancelled.set()
        if controller is not None:
            try:
                controller.join()
            except BaseException:
                cleanup_ok = False
        if entered_scheduler:
            _join_observability_workers(previous_workers)
        # Exception paths perform no further trading reads/writes or reopening.
        resources = (telegram_session, None if session is None else getattr(session, "client", None),
                     store, lock if lock_acquired else None)
        for resource in resources:
            if resource is not None:
                try:
                    resource.release() if resource is lock else resource.close()
                except BaseException:
                    cleanup_ok = False
        secrets = None
        if transport is not None:
            transport._token = transport._chat_id = None
        if session is not None:
            session.api_key = session.api_secret = None
        if child is not None:
            try:
                if child.poll() is None:
                    child.terminate()
                child.wait(timeout=5)
            except BaseException:
                cleanup_ok = False
        if handlers_entered:
            try:
                handlers.__exit__(None, None, None)
            except BaseException:
                cleanup_ok = False
    return replace(result, cleanup_ok=cleanup_ok, exit_code=result.exit_code if cleanup_ok else 1)


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, "Invalid operator arguments. Run --help for usage.\n")


def add_runtime_arguments(parser):
    for name in ("registry-root", "observability-root", "secret-file"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--duration-hours", required=True, type=int)
    parser.add_argument("--start-next-hour", required=True, action="store_true")


def configuration_from_arguments(args):
    return DemoRuntimeConfiguration(args.registry_root, args.observability_root,
                                    args.secret_file, args.duration_hours)


def runtime_main(argv=None):
    parser = SafeArgumentParser(description="Explicit bounded Demo runtime; no implicit activation.")
    add_runtime_arguments(parser)
    parser.add_argument("--confirm-demo-runtime", required=True, action="store_true")
    args = parser.parse_args(argv)
    try:
        result = run_demo_runtime(configuration_from_arguments(args))
        print(json.dumps({"code": result.code, "scheduler_exit": result.scheduler_exit,
                          "checkpoint_sequence": result.checkpoint_sequence,
                          "cycle_count": result.cycle_count, "wake_count": result.wake_count,
                          "start_boundary_ms": result.start_boundary_ms,
                          "stop_deadline_ms": result.stop_deadline_ms, "cleanup_ok": result.cleanup_ok}))
        return result.exit_code
    except BaseException:
        print("Operator invocation refused.")
        return 1
