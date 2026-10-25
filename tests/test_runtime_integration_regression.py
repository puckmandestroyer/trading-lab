"""Offline composition of frozen runtime layers; only external evidence is fake.

The fake broker publishes orders/executions, never runtime states. Fault patches
are explicitly labeled. No real session, credentials, sleep or HTTP is allowed.
"""

import ast
from collections import Counter
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal, localcontext
import hashlib
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import pandas as pd
import requests

import trading_lab.exchange as exchange
import trading_lab.exchange.bybit_demo as demo
import trading_lab.exchange.bybit_demo_orders as orders_module
import trading_lab.exchange.bybit_demo_read_only as reads_module
from trading_lab.exchange.bybit_demo_orders import BybitDemoOrderAdapter
from trading_lab.exchange.bybit_demo_read_only import BybitDemoReadOnlyAdapter
from trading_lab.exchange.bybit_public_market import BybitPublicMarketReader, SERVER_TIME_URL
from trading_lab.exchange.bybit_market_data import KLINE_URL
from trading_lab.runtime.cycle import CycleOutcome, run_single_cycle
from trading_lab.runtime.locking import RuntimeAccountLock, RuntimeLockError
from trading_lab.runtime.reconciliation import reconcile_startup
from trading_lab.runtime.recovery import prepare_process_restart
from trading_lab.runtime.scheduler import SchedulerExit, run_hourly_scheduler
from trading_lab.runtime.state import PositionEvidence, RuntimeReason, RuntimeState
from trading_lab.runtime.store import ActionPhase, DecisionDisposition, RuntimeStore, RuntimeStoreError
from trading_lab.strategies.ema_trend import generate_ema_signals
from tests.test_bybit_spot_rules import synthetic_response
from tests.test_runtime_store import configuration, initialize_permissive_risk


D = Decimal
HOUR = 3_600_000
PRIVATE = "private-offline-integration-secret-signature-header-body"
ENTRY_ID = "fc17adafb331e964da8e79112502274620b772ad52ee42c3cfec05f61a86a704"
EXIT_ID = "349b4d70a2a702ce3f311c1c43bf523b830c193ef9f4a9128d793f4f37dbbb90"
ROOT = Path(__file__).resolve().parents[1]


def utc(ms):
    return datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(milliseconds=ms)


class Clock:
    def __init__(self):
        self.ms, self.elapsed = 50 * HOUR + 1000, 0.0

    def advance(self, milliseconds):
        self.ms += milliseconds
        self.elapsed += milliseconds / 1000

    def now(self):
        return utc(self.ms)


class Stop:
    """Scripted external events advance clocks immediately; no wall-clock wait."""
    def __init__(self, case, events):
        self.case, self.events, self.waits, self.stopped = case, list(events), [], False

    def is_set(self):
        return self.stopped

    def wait(self, seconds):
        self.case.capture()
        self.waits.append(seconds)
        if not self.events:
            self.stopped = True
        else:
            self.events.pop(0)(seconds)
        return self.stopped


class PublicTransport:
    def __init__(self, case):
        self.case, self.auth, self.trust_env = case, None, True

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def get(self, url, *, params, timeout, allow_redirects):
        c = self.case
        c.external("public_time" if url == SERVER_TIME_URL else "public_klines", params)
        c.assertIsNone(self.auth)
        c.assertFalse(self.trust_env)
        c.assertFalse(allow_redirects)
        c.assertEqual(timeout, 10)
        now = c.clock.ms
        if url == SERVER_TIME_URL:
            c.clock.advance(c.time_latency)
            c.time_latency = 0
            payload = {"retCode": 0, "time": now, "result": {
                "timeSecond": str(now // 1000), "timeNano": str(now * 1_000_000)}}
        else:
            c.assertEqual(url, KLINE_URL)
            c.assertEqual((params["category"], params["symbol"], params["interval"]), ("spot", "BTCUSDT", "60"))
            c.clock.advance(c.page_latency)
            c.page_latency = 0
            rows = [[str(i * HOUR), p, p, p, p, "1.25", str(D(p) * D("1.25"))]
                    for i, p in enumerate(c.prices) if params["start"] <= i * HOUR <= params["end"]]
            payload = {"retCode": 0, "time": c.clock.ms, "result": {
                "category": "spot", "symbol": "BTCUSDT", "list": list(reversed(rows))[:params["limit"]]}}
        return Response(payload)


class Response:
    status_code = 200

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return deepcopy(self.payload)


class BrokerTransport:
    """Raw, synthetic pybit boundary. Orders and executions outlive a process."""
    testnet = False
    demo = True
    endpoint = "https://api-demo.bybit.com"
    force_retry = False
    max_retries = 1
    retry_delay = 0
    log_requests = False
    api_key = PRIVATE
    api_secret = PRIVATE

    def __init__(self, case):
        self.case = case

    def envelope(self, records, *, category=True):
        result = {"list": deepcopy(records), "nextPageCursor": ""}
        if category:
            result["category"] = "spot"
        # Private observations include the fixture's explicit 1 ms fill latency.
        return {"retCode": 0, "time": self.case.clock.ms + 1, "result": result, "private_raw": PRIVATE}

    def get_wallet_balance(self, **params):
        c = self.case
        c.external("account", params)
        if c.account_failures:
            c.account_failures -= 1
            raise TimeoutError(PRIVATE)
        return self.envelope([{"accountType": "UNIFIED", "totalAvailableBalance": "1000",
            "totalWalletBalance": "1000", "totalEquity": "1000", "coin": [
                {"coin": "BTC", "walletBalance": c.wallet_btc, "equity": c.wallet_btc, "locked": "0"},
                {"coin": "USDT", "walletBalance": "1000", "equity": "1000", "locked": "0"}]}], category=False)

    def get_open_orders(self, **params):
        c = self.case
        c.external("open" if "orderId" not in params else "exact", params)
        rows = [] if c.hidden else list(c.remote_orders.values())
        if "orderId" in params:
            rows = [r for r in rows if r["orderId"] == params["orderId"]]
            if c.history_only:
                rows = []
        else:
            rows = [r for r in rows if r["orderStatus"] in ("New", "PartiallyFilled", "FutureStatus")]
        return self.envelope(rows)

    def get_order_history(self, **params):
        c = self.case
        c.external("history", params)
        return self.envelope([] if c.hidden else [r for r in c.remote_orders.values() if r["orderId"] == params["orderId"]])

    def get_executions(self, **params):
        c = self.case
        c.external("executions", params)
        rows = [] if c.hidden else c.remote_fills
        if "orderId" in params:
            rows = [r for r in rows if r["orderId"] == params["orderId"]]
        return self.envelope(rows)

    def get_instruments_info(self, **params):
        c = self.case
        c.external("metadata", params)
        action = c.store.get_action(c.store.get_checkpoint().snapshot.pending_action.logical_action_id)
        c.assertIs(action.phase, ActionPhase.PREPARED)
        c.assertEqual(action.attempt_count, 0)
        verdict = c.store.get_risk_verdict(action.candle_open_ms)
        c.assertEqual((verdict.verdict.value, verdict.action_id), ("ALLOW", action.logical_action_id))
        c.audit("PREPARED")
        return synthetic_response()

    def place_order(self, **params):
        c = self.case
        c.external("place", params)
        action = c.store.get_action(c.store.get_checkpoint().snapshot.pending_action.logical_action_id)
        c.assertIs(action.phase, ActionPhase.ATTEMPT_STARTED)
        c.assertEqual(action.attempt_count, 1)
        c.assertIs(c.store.get_decision(action.candle_open_ms).disposition, DecisionDisposition.ACTION)
        c.assertEqual(params["orderLinkId"], action.order_link_id)
        c.assertEqual(params["category"], "spot")
        c.assertEqual(params["orderType"], "Market")
        c.assertEqual(params["isLeverage"], 0)
        c.assertEqual(params["marketUnit"], "quoteCoin" if params["side"] == "Buy" else "baseCoin")
        c.assertLessEqual(D(params["qty"]), action.authorized_amount)
        c.sends.append(deepcopy(params))
        c.assertEqual(Counter(p["orderLinkId"] for p in c.sends)[params["orderLinkId"]], 1)
        c.audit("ATTEMPT_STARTED")
        if c.send_mode == "reject":
            return {"retCode": 10001, "retMsg": PRIVATE, "result": {}}
        order_id = "order-" + str(len(c.sends))
        if c.send_mode != "ambiguous_missing":
            c.publish(params, order_id, c.status)
        if c.send_mode.startswith("ambiguous"):
            raise TimeoutError(PRIVATE)
        return {"retCode": 0, "time": c.clock.ms,
                "result": {} if c.send_mode == "malformed" else {"orderId": order_id, "orderLinkId": params["orderLinkId"]}}

    def cancel_order(self, **params):
        self.case.cancels.append(params)
        raise AssertionError("Automatic cancellation is forbidden")


class IntegrationCase(unittest.TestCase):
    def setUp(self):
        self.directory = self.enterContext(TemporaryDirectory())
        self.config = replace(configuration(), reconciliation_timeout_ms=3 * HOUR)
        self.clock = Clock()
        self.prices = ["100"] * 50
        self.remote_orders, self.remote_fills, self.sends, self.cancels = {}, [], [], []
        self.trace, self.snapshots, self.audits = [], [], []
        self.status, self.send_mode = "Filled", "normal"
        self.buy_quantity = D("0.05")
        self.hidden = self.history_only = False
        self.wallet_btc = "3"
        self.account_failures = self.page_latency = self.time_latency = 0
        self.lock = RuntimeAccountLock(Path(self.directory), "research").acquire()
        self.store = RuntimeStore.open(self.lock, self.config, initialize=True)
        self.addCleanup(self.close)
        # These guards remain on original transports even while the public
        # session factory is replaced with our finite external fixture.
        original_session = requests.Session
        self.guards = [self.enterContext(patch.object(original_session, method, side_effect=AssertionError("No HTTP")))
                       for method in ("send", "request")]
        for target in ("socket.create_connection", "socket.socket.connect", "os.getenv", "time.sleep",
                       "pybit._http_manager._V5HTTPManager._submit_request"):
            self.guards.append(self.enterContext(patch(target, side_effect=AssertionError("Offline only"))))
        for owner, name in ((demo, "HTTP"), (demo, "load_bybit_demo_credentials"),
                            (demo, "create_bybit_demo_session"), (exchange, "load_bybit_demo_credentials"),
                            (exchange, "create_bybit_demo_session")):
            self.guards.append(self.enterContext(patch.object(owner, name, side_effect=AssertionError("No credentials/session"))))
        self.enterContext(patch("requests.Session", side_effect=lambda: PublicTransport(self)))
        for module in (orders_module, reads_module):
            mocked = self.enterContext(patch.object(module, "datetime", wraps=datetime))
            mocked.now.side_effect = lambda tz=None: self.clock.now()
        self.clients()
        self.addCleanup(self.assert_guards)

    def assert_guards(self):
        for guard in self.guards:
            guard.assert_not_called()
        self.assertEqual(self.cancels, [])
        self.assertTrue(all(n == 1 for n in Counter(p["orderLinkId"] for p in self.sends).values()))

    def close(self):
        self.store.close()
        self.lock.release()

    def clients(self):
        self.session = BrokerTransport(self)
        self.broker = BybitDemoReadOnlyAdapter(self.session, account_id="research")
        self.adapter = BybitDemoOrderAdapter(self.session)
        self.market = BybitPublicMarketReader()

    def external(self, name, params):
        # Allowed observation-only instrumentation: never mutate connection.
        self.assertFalse(self.store._connection.in_transaction, name)
        cp = self.store.get_checkpoint()
        self.trace.append((name, deepcopy(params), cp.snapshot.state, self.store.list_actions()))
        phases = {a.phase for a in self.store.list_actions()}
        if ActionPhase.ACKNOWLEDGED in phases:
            self.audit("ACKNOWLEDGED")
        if ActionPhase.UNKNOWN_OUTCOME in phases:
            self.audit("UNKNOWN_OUTCOME")

    def audit(self, label):
        other = RuntimeStore.open(self.lock, self.config, initialize=False)
        try:
            self.assertEqual(other.get_checkpoint(), self.store.get_checkpoint())
            self.assertEqual(other.list_actions(), self.store.list_actions())
            self.assertEqual(other.list_fills(), self.store.list_fills())
        finally:
            other.close()
        self.audits.append(label)

    def capture(self):
        self.snapshots.append(self.store.get_checkpoint())

    def publish(self, params, order_id, status):
        self.remote_orders[order_id] = {
            "orderId": order_id, "orderLinkId": params["orderLinkId"], "symbol": "BTCUSDT", "side": params["side"],
            "orderType": "Market", "marketUnit": params["marketUnit"], "isLeverage": "0", "qty": params["qty"],
            "orderStatus": "New", "cumExecQty": "0", "cumExecValue": "0", "avgPrice": "", "price": "0", "triggerPrice": "0",
            "createdTime": str(self.clock.ms), "updatedTime": str(self.clock.ms), "private_raw": PRIVATE}
        if status != "New":
            quantity = self.buy_quantity if params["side"] == "Buy" else D(params["qty"])
            if status == "PartiallyFilled":
                quantity = D("0.02")
            self.add_execution(order_id, quantity, "exec-buy-1" if params["side"] == "Buy" else "exec-sell-1", status=status)

    def add_execution(self, order_id, quantity, execution_id, *, status="Filled", fee=None):
        order = self.remote_orders[order_id]
        buy = order["side"] == "Buy"
        self.remote_fills.append({"execId": execution_id, "orderId": order_id, "orderLinkId": order["orderLinkId"],
            "symbol": "BTCUSDT", "side": order["side"], "execType": "Trade", "execQty": str(quantity),
            "execPrice": "100.123456789" if buy else "111.123456789", "execFee": str(fee if fee is not None else (D("0.00005") if buy else D("0.01"))),
            "feeCurrency": "BTC" if buy else "USDT", "execTime": str(self.clock.ms + 1), "private_raw": PRIVATE})
        rows = [r for r in self.remote_fills if r["orderId"] == order_id]
        with localcontext() as context:
            context.prec = 60
            base = sum((D(r["execQty"]) for r in rows), D("0"))
            quote = sum((D(r["execQty"]) * D(r["execPrice"]) for r in rows), D("0"))
            order.update(orderStatus=status, cumExecQty=str(base), cumExecValue=str(quote),
                         avgPrice=str(quote / base), updatedTime=str(self.clock.ms + 1))

    def wake(self, price, *, hours=1, before=None):
        def event(seconds):
            target = (self.clock.ms // HOUR + hours) * HOUR
            self.clock.advance(target - self.clock.ms)
            self.prices.extend([price] * hours)
            if before:
                before()
        return event

    def scheduler(self, events=()):
        self.stop = Stop(self, events)
        # Wrap only fixture activation between real cycles; runtime never initializes risk.
        with patch("trading_lab.runtime.scheduler.run_single_cycle", side_effect=self.activated_cycle):
            result = run_hourly_scheduler(self.store, self.market, self.broker, self.adapter, self.stop,
                                          utc_now=self.clock.now, monotonic=lambda: self.clock.elapsed)
        self.capture()
        return result

    def activated_cycle(self, *args, **kwargs):
        result = run_single_cycle(*(args or (self.store, self.market, self.broker, self.adapter)),
            **(kwargs or dict(utc_now=self.clock.now, monotonic=lambda: self.clock.elapsed)))
        if result.outcome in (CycleOutcome.BOOTSTRAP, CycleOutcome.REPLAY_ONLY):
            initialize_permissive_risk(self.store)
        return result

    def cycle(self):
        result = self.activated_cycle()
        self.capture()
        return result

    def public_time_failure(self, payload_or_error):
        """Inject only the external public GET result; real parsing still runs."""
        original = PublicTransport.get

        def get(transport, url, **kwargs):
            if url == SERVER_TIME_URL:
                self.external("public_time", kwargs["params"])
                if isinstance(payload_or_error, Exception):
                    raise payload_or_error
                return Response(payload_or_error)
            return original(transport, url, **kwargs)

        return patch.object(PublicTransport, "get", get)

    def round(self):
        return reconcile_startup(self.store, self.broker, utc_now=self.clock.now, monotonic=lambda: self.clock.elapsed)

    def reopen(self):
        old = self.lock
        self.store.close()
        old.release()
        self.lock = RuntimeAccountLock(Path(self.directory), "research").acquire()
        self.assertIsNot(self.lock, old)
        self.store = RuntimeStore.open(self.lock, self.config, initialize=False)
        cp = prepare_process_restart(self.store)
        self.clients()
        self.audit("post-restart")
        return cp

    def enter(self, *, status="Filled"):
        self.assertIs(self.cycle().outcome, CycleOutcome.BOOTSTRAP)
        self.status = status
        self.wake("110")(0)
        return self.cycle()

    def assert_owned(self, state, quantity):
        cp = self.store.get_checkpoint()
        self.assertIs(cp.snapshot.state, state)
        self.assertEqual(cp.snapshot.owned_base_quantity, D(quantity))

    def logical_history(self):
        cp = self.store.get_checkpoint()
        return tuple((self.store.get_candle(ms), self.store.get_decision(ms))
                     for ms in range(0, cp.last_processed_candle_ms + HOUR, HOUR))

    def golden(self):
        self.assertIs(self.store.get_checkpoint().snapshot.state, RuntimeState.STARTING)
        result = self.scheduler([self.wake("110"), self.wake("110"), self.wake("110"), self.wake("60")])
        self.assertEqual((result.cycle_count, result.wake_count), (5, 4))
        self.assertIs(result.exit_reason, SchedulerExit.STOP_REQUESTED)
        cp = result.checkpoint
        self.assertIs(cp.snapshot.stopped_from, RuntimeState.FLAT)
        self.assertEqual(cp.snapshot.owned_base_quantity, D("0"))
        self.audit("STOPPING")
        history = self.logical_history()
        self.assertEqual(len(history), 54)
        self.assertEqual([d.signal for _, d in history[-5:]], ["HOLD", "LONG_ENTRY", "HOLD", "HOLD", "LONG_EXIT"])
        self.assertTrue(all(d.disposition == DecisionDisposition.BOOTSTRAP for _, d in history[:50]))
        self.assertEqual(cp.bootstrap_until_ms, 49 * HOUR)
        actions = tuple(sorted(self.store.list_actions(), key=lambda a: a.candle_open_ms))
        fills = tuple(sorted(self.store.list_fills(), key=lambda f: f.executed_at_ms))
        self.assertEqual([a.logical_action_id for a in actions], [ENTRY_ID, EXIT_ID])
        self.assertEqual([a.order_link_id for a in actions], ["bot1-" + ENTRY_ID[:23], "bot1-" + EXIT_ID[:23]])
        self.assertEqual([a.authorized_amount for a in actions], [D("10.123456789"), D("0.04995")])
        self.assertEqual([a.submitted_amount for a in actions], [D("10.1234567"), D("0.04995")])
        self.assertTrue(all(a.phase == ActionPhase.TERMINAL_CONFIRMED for a in actions))
        self.assertEqual([f.broker_execution_id for f in fills], ["exec-buy-1", "exec-sell-1"])
        self.assertEqual([f.executed_quantity for f in fills], [D("0.05"), D("0.04995")])
        self.assertEqual([f.execution_price for f in fills], [D("100.123456789"), D("111.123456789")])
        self.assertEqual([f.execution_fee for f in fills], [D("0.00005"), D("0.01")])
        self.assertEqual([f.fee_currency for f in fills], ["BTC", "USDT"])
        self.assertEqual([f.action_id for f in fills], [ENTRY_ID, EXIT_ID])
        self.assertEqual(len(self.sends), 2)
        valuations, verdicts = self.store.list_risk_valuations(), self.store.list_risk_verdicts()
        self.assertEqual([row.mode.value for row in valuations], ["ACTIVATION", "LIVE", "LIVE", "LIVE", "LIVE"])
        self.assertEqual([row.candle_open_ms for row in valuations], list(range(49 * HOUR, 54 * HOUR, HOUR)))
        self.assertEqual([row.verdict.value for row in verdicts], ["ALLOW"] * 4)
        self.assertEqual([row.action_id for row in verdicts], [ENTRY_ID, None, None, EXIT_ID])
        self.assertEqual([row.entries_this_utc_day for row in valuations], [0, 1, 1, 1, 1])
        self.assertEqual(valuations[-1].owned_base_quantity, D("0.04995"))  # EXIT fill is after this mark.
        self.assertEqual(self.cancels, [])
        self.assertTrue({"PREPARED", "ATTEMPT_STARTED", "ACKNOWLEDGED", "STOPPING"}.issubset(self.audits))
        self.assertTrue({RuntimeState.SYNCHRONIZING, RuntimeState.FLAT, RuntimeState.ORDER_PENDING, RuntimeState.LONG}.issubset(
            {t[2] for t in self.trace}))
        normalized = self.reopen()
        self.assertIs(normalized.snapshot.state, RuntimeState.STARTING)
        self.assertIs(normalized.snapshot.position_evidence, PositionEvidence.LAST_KNOWN)
        restart = self.scheduler()
        self.assertIs(restart.checkpoint.snapshot.stopped_from, RuntimeState.FLAT)
        self.assertEqual(self.logical_history(), history)
        self.assertEqual(set(self.store.list_actions()), set(actions))
        self.assertEqual(set(self.store.list_fills()), set(fills))
        return history, actions, fills, restart.checkpoint.snapshot


class GoldenIntegrationTests(IntegrationCase):
    def test_complete_golden_round_trip_shutdown_and_restart(self):
        self.golden()

    def test_frozen_ema_output_equals_every_durable_decision(self):
        history, _, _, _ = self.golden()
        frame = pd.DataFrame({"timestamp": pd.to_datetime([i * HOUR for i in range(54)], unit="ms", utc=True),
                              "close": [float(p) for p in self.prices]})
        signals = generate_ema_signals(frame, fast_span=20, slow_span=50, warmup_candles=50)
        self.assertEqual([d.signal for _, d in history], signals["signal"].tolist())
        self.assertEqual([d.desired_position for _, d in history], signals["desired_position"].tolist())

    def test_historical_long_desire_bootstraps_without_any_placement(self):
        self.prices.append("110")
        self.clock.advance(HOUR)
        result = self.scheduler()
        self.assertIs(result.checkpoint.snapshot.stopped_from, RuntimeState.FLAT)
        self.assertEqual(result.checkpoint.snapshot.desired_position, 1)
        self.assertEqual(result.checkpoint.bootstrap_until_ms, 50 * HOUR)
        self.assertEqual(self.store.get_decision(50 * HOUR).disposition, DecisionDisposition.BOOTSTRAP)
        self.assertEqual((self.sends, self.store.list_actions(), self.store.list_fills()), ([], (), ()))
        self.audit("post-bootstrap")

    def test_unrelated_wallet_btc_never_becomes_owned_or_sell_authorization(self):
        self.wallet_btc = "999.123456789"
        self.prices.append("110")
        self.clock.advance(HOUR)
        self.scheduler([self.wake("60")])
        self.assertEqual(self.store.get_checkpoint().snapshot.owned_base_quantity, D("0"))
        self.assertEqual(self.sends, [])

    def test_golden_repeatability_in_independent_registries(self):
        first = self.golden()
        # Same inputs, but entirely new locks, SQLite files and external world.
        second = IntegrationCase()
        second.setUp()
        try:
            self.assertNotEqual(self.directory, second.directory)
            self.assertEqual(first, second.golden())
        finally:
            self.assertTrue(second.doCleanups(), "The independent scenario must clean up without guard failures")

    def test_entire_journal_frontier_identity_and_no_historical_mutation(self):
        history, actions, _, _ = self.golden()
        self.assertEqual([c.candle_open_ms for c, _ in history], list(range(0, 54 * HOUR, HOUR)))
        self.assertTrue(all(c.input_fingerprint == d.input_fingerprint for c, d in history))
        authorized = [d for _, d in history if d.disposition == DecisionDisposition.ACTION]
        self.assertEqual(len(authorized), 2)
        self.assertEqual(len({d.candle_open_ms for d in authorized}), 2)
        self.assertEqual({d.action_id for d in authorized}, {a.logical_action_id for a in actions})

    def test_all_external_boundaries_are_outside_sqlite_writer_transaction(self):
        self.history_only = True
        self.golden()
        names = {item[0] for item in self.trace}
        self.assertTrue({"public_time", "public_klines", "account", "open", "exact", "history",
                         "executions", "metadata", "place"}.issubset(names))

    def test_synthetic_secrets_payloads_and_errors_never_persist(self):
        self.golden()
        self.assertNotIn(PRIVATE, repr((self.store.get_checkpoint(), self.store.list_actions(), self.store.list_fills())))
        for path in Path(self.directory).rglob("*"):
            if path.is_file():
                self.assertNotIn(PRIVATE.encode(), path.read_bytes())
                self.assertNotIn(b"private_raw", path.read_bytes())


class PendingIntegrationTests(IntegrationCase):
    def test_unknown_external_status_stays_uncertain_without_known_state_fabrication(self):
        self.enter(status="New")
        self.remote_orders["order-1"]["orderStatus"] = "FutureStatus"
        result = self.round()
        self.assertIs(result.checkpoint.snapshot.state, RuntimeState.UNCERTAIN)
        self.assertIs(result.checkpoint.snapshot.reason, RuntimeReason.ACTION_OUTCOME_UNKNOWN)
        self.assertEqual(self.store.get_action(ENTRY_ID).order_status, "UNKNOWN")
        self.assertEqual(self.store.get_action(ENTRY_ID).external_status, "FutureStatus")
        self.assertEqual(self.store.list_fills(), ())
        self.assertEqual(len(self.sends), 1)

    def test_metadata_failure_blocks_attempt_marker_and_placement(self):
        self.cycle()
        self.wake("110")(0)
        # Only external metadata evidence is malformed; frozen preflight runs.
        with patch.object(self.session, "get_instruments_info", return_value={"retCode": 10001}):
            result = self.cycle()
        self.assertIs(result.outcome, CycleOutcome.ABANDONED_UNSENT)
        action = self.store.get_action(ENTRY_ID)
        self.assertIs(action.phase, ActionPhase.ABANDONED_UNSENT)
        self.assertEqual(action.attempt_count, 0)
        self.assertEqual(self.sends, [])

    def test_open_order_survives_hourly_wake_without_queue_or_resend(self):
        self.status = "New"
        result = self.scheduler([self.wake("110"), self.wake("110")])
        self.assertEqual((result.cycle_count, result.wake_count), (3, 2))
        self.assertIs(result.checkpoint.snapshot.stopped_from, RuntimeState.ORDER_PENDING)
        self.assertEqual(result.checkpoint.snapshot.pending_action.logical_action_id, ENTRY_ID)
        self.assertEqual(len(self.sends), 1)
        self.assertEqual(self.store.list_fills(), ())
        self.assertEqual(len(self.stop.waits), 3)
        self.assertEqual(self.store.get_action(ENTRY_ID).broker_order_id, "order-1")

    def test_partial_then_final_fill_across_wakes_deduplicates_same_execution(self):
        self.status = "New"
        def partial():
            self.add_execution("order-1", D("0.02"), "exec-partial", status="PartiallyFilled", fee=D("0.00002"))
        def final():
            self.assert_owned(RuntimeState.ORDER_PENDING, "0.01998")
            self.assertEqual(len(self.store.list_fills()), 1)
            self.audit("partial")
            self.add_execution("order-1", D("0.03"), "exec-final", fee=D("0.00003"))
        result = self.scheduler([self.wake("110"), self.wake("110", before=partial), self.wake("110", before=final)])
        self.assertIs(result.checkpoint.snapshot.stopped_from, RuntimeState.LONG)
        self.assertEqual(result.checkpoint.snapshot.owned_base_quantity, D("0.04995"))
        self.assertEqual({f.broker_execution_id for f in self.store.list_fills()}, {"exec-partial", "exec-final"})
        self.assertEqual(len(self.sends), 1)
        self.audit("terminal")

    def test_acknowledgement_alone_does_not_prove_owned_position(self):
        self.enter(status="New")
        self.assert_owned(RuntimeState.ORDER_PENDING, "0")
        self.assertEqual(self.store.list_fills(), ())
        action = self.store.get_action(ENTRY_ID)
        self.assertEqual(action.submitted_amount, D("10.1234567"))
        self.assertEqual(action.order_status, "OPEN")

    def test_restart_long_reconciles_same_exact_fills_without_new_buy(self):
        self.scheduler([self.wake("110")])
        fills = self.store.list_fills()
        cp = self.reopen()
        self.assertIs(cp.snapshot.position_evidence, PositionEvidence.LAST_KNOWN)
        self.assertEqual(cp.snapshot.owned_base_quantity, D("0.04995"))
        result = self.scheduler()
        self.assertIs(result.checkpoint.snapshot.stopped_from, RuntimeState.LONG)
        self.assertEqual(self.store.list_fills(), fills)
        self.assertEqual(len(self.sends), 1)

    def test_restart_pending_preserves_id_then_terminal_fill_without_resend(self):
        self.status = "New"
        self.scheduler([self.wake("110")])
        before = self.store.get_action(ENTRY_ID)
        self.reopen()
        self.add_execution("order-1", D("0.05"), "exec-buy-1")
        self.scheduler()
        after = self.store.get_action(ENTRY_ID)
        self.assertEqual((after.logical_action_id, after.order_link_id, after.broker_order_id),
                         (before.logical_action_id, before.order_link_id, before.broker_order_id))
        self.assertIs(after.phase, ActionPhase.TERMINAL_CONFIRMED)
        self.assertEqual(len(self.sends), 1)

    def test_rejected_action_identity_is_consumed_and_hold_cannot_resend(self):
        self.send_mode = "reject"
        self.scheduler([self.wake("110")])
        action = self.store.get_action(ENTRY_ID)
        self.assertIs(action.phase, ActionPhase.REJECTED)
        self.assertEqual(action.rejection_code, 10001)
        self.reopen()
        self.send_mode = "normal"
        self.scheduler([self.wake("110")])
        self.assertEqual(self.store.get_action(ENTRY_ID), action)
        self.assertEqual(len(self.sends), 1)
        self.assertEqual(self.store.list_fills(), ())


class CrashIntegrationTests(IntegrationCase):
    def crash_entry(self, method, predicate, *, after=False):
        self.assertIs(self.cycle().outcome, CycleOutcome.BOOTSTRAP)
        self.wake("110")(0)
        original = getattr(self.store, method)
        def fault(*args, **kwargs):
            # TEST-ONLY synthetic process loss at a specified durable boundary.
            if predicate(*args, **kwargs):
                if after:
                    original(*args, **kwargs)
                raise RuntimeStoreError("Synthetic process loss")
            return original(*args, **kwargs)
        with patch.object(self.store, method, side_effect=fault):
            with self.assertRaises(RuntimeStoreError):
                self.scheduler()
        self.assertIsNot(self.store.get_checkpoint().snapshot.state, RuntimeState.STOPPING)

    def test_prepared_commit_crash_retires_unsent_and_consumes_candle(self):
        self.crash_entry("commit_live_risk_decision", lambda *args, **kw: kw.get("proposed_action") is not None, after=True)
        self.assertIs(self.store.get_action(ENTRY_ID).phase, ActionPhase.PREPARED)
        self.audit("PREPARED")
        self.reopen()
        self.scheduler([self.wake("110")])
        self.assertIs(self.store.get_action(ENTRY_ID).phase, ActionPhase.ABANDONED_UNSENT)
        self.assertEqual(self.store.get_decision(50 * HOUR).action_id, ENTRY_ID)
        self.assertEqual(self.sends, [])

    def test_durable_attempt_physically_unsent_remains_uncertain_never_abandoned(self):
        self.crash_entry("start_attempt", lambda *args, **kw: True, after=True)
        self.assertIs(self.store.get_action(ENTRY_ID).phase, ActionPhase.ATTEMPT_STARTED)
        self.assertEqual(self.sends, [])
        self.reopen()
        self.round()
        action = self.store.get_action(ENTRY_ID)
        self.assertIs(action.phase, ActionPhase.UNKNOWN_OUTCOME)
        self.assertIs(self.store.get_checkpoint().snapshot.state, RuntimeState.UNCERTAIN)
        self.assertEqual(self.sends, [])

    def test_lost_local_ack_recovers_by_exact_original_link_without_fabricating_receipt(self):
        self.crash_entry("record_observation", lambda action, *args, **kw: action.phase == ActionPhase.ACKNOWLEDGED)
        self.assertEqual(len(self.sends), 1)

        action = self.store.get_action(ENTRY_ID)
        self.assertIs(action.phase, ActionPhase.ATTEMPT_STARTED)
        self.assertIsNone(action.broker_order_id)
        self.reopen()
        self.scheduler()
        recovered = self.store.get_action(ENTRY_ID)
        self.assertIs(recovered.phase, ActionPhase.TERMINAL_CONFIRMED)
        self.assertEqual(recovered.broker_order_id, "order-1")
        self.assertIsNone(recovered.submitted_amount)
        self.assertIsNone(recovered.acknowledgement_broker_ms)
        self.assertEqual(len(self.sends), 1)

    def ack_crash(self, status):
        self.status = status
        self.crash_entry("record_observation", lambda action, *args, **kw: action.phase == ActionPhase.ACKNOWLEDGED, after=True)
        known = self.store.get_action(ENTRY_ID)
        self.assertIs(known.phase, ActionPhase.ACKNOWLEDGED)
        self.audit("ACKNOWLEDGED")
        self.reopen()
        result = self.round()
        self.assertEqual(self.store.get_action(ENTRY_ID).broker_order_id, "order-1")
        self.assertTrue(any(name == "exact" and params["orderId"] == "order-1" for name, params, *_ in self.trace))
        self.assertEqual(len(self.sends), 1)
        return result

    def test_ack_durable_crash_open_recovers_known_pending_lifecycle(self):
        self.ack_crash("New")
        self.assert_owned(RuntimeState.ORDER_PENDING, "0")

    def test_ack_durable_crash_filled_recovers_terminal_exposure(self):
        self.ack_crash("Filled")
        self.assert_owned(RuntimeState.LONG, "0.04995")

    def test_terminal_commit_return_loss_reopens_durable_truth_without_resurrection(self):
        self.crash_entry("record_observation", lambda action, *args, **kw: action.phase == ActionPhase.TERMINAL_CONFIRMED, after=True)
        before = self.store.get_action(ENTRY_ID), self.store.list_fills(), self.logical_history()
        self.assert_owned(RuntimeState.LONG, "0.04995")
        self.audit("terminal")
        self.reopen()
        self.scheduler()
        self.assertEqual((self.store.get_action(ENTRY_ID), self.store.list_fills(), self.logical_history()), before)
        self.assertEqual(len(self.sends), 1)

    def ambiguous_recovery(self, status):
        self.send_mode, self.hidden, self.status = "ambiguous_accept", True, status
        self.enter(status=status)
        self.assertIs(self.store.get_action(ENTRY_ID).phase, ActionPhase.UNKNOWN_OUTCOME)
        self.assertIs(self.store.get_checkpoint().snapshot.state, RuntimeState.UNCERTAIN)
        self.audit("UNKNOWN_OUTCOME")
        self.reopen()
        self.hidden = False
        self.round()
        self.assertEqual(self.store.get_action(ENTRY_ID).broker_order_id, "order-1")
        self.assertEqual(len(self.sends), 1)
        self.assertNotIn(PRIVATE, repr(self.store.list_actions()))

    def test_ambiguous_acceptance_restart_discovers_open_order(self):
        self.ambiguous_recovery("New")
        self.assert_owned(RuntimeState.ORDER_PENDING, "0")

    def test_ambiguous_acceptance_restart_discovers_partial_fill(self):
        self.ambiguous_recovery("PartiallyFilled")
        self.assert_owned(RuntimeState.ORDER_PENDING, "0.01995")

    def test_ambiguous_acceptance_restart_discovers_final_fill(self):
        self.ambiguous_recovery("Filled")
        self.assert_owned(RuntimeState.LONG, "0.04995")

    def test_ambiguous_missing_budget_decreases_across_restart_then_halt_latches(self):
        self.send_mode = "ambiguous_missing"
        self.enter()
        previous = self.store.get_action(ENTRY_ID)
        for _ in range(4):
            self.reopen()
            self.round()
            current = self.store.get_action(ENTRY_ID)
            self.assertLessEqual(current.remaining_read_attempts, previous.remaining_read_attempts)
            self.assertLessEqual(current.remaining_reconciliation_rounds, previous.remaining_reconciliation_rounds)
            self.assertEqual(current.reconciliation_deadline_ms, previous.reconciliation_deadline_ms)
            previous = current
        self.assertIs(self.store.get_checkpoint().snapshot.state, RuntimeState.HALTED)
        self.assertIs(self.store.get_checkpoint().snapshot.reason, RuntimeReason.RECOVERY_EXHAUSTED)
        before = self.store.get_checkpoint()
        calls = len(self.trace)
        self.assertEqual(self.reopen(), before)
        self.assertEqual(self.scheduler().checkpoint, before)
        self.assertEqual(len(self.trace), calls)
        self.assertEqual(len(self.sends), 1)

    def test_malformed_ack_preserves_uncertainty_and_recovers_broker_evidence(self):
        self.send_mode, self.hidden = "malformed", True
        self.enter()
        self.assertIs(self.store.get_action(ENTRY_ID).phase, ActionPhase.UNKNOWN_OUTCOME)
        self.reopen()
        self.hidden = False
        self.round()
        self.assert_owned(RuntimeState.LONG, "0.04995")
        self.assertEqual(len(self.sends), 1)

    def test_sqlite_commit_failure_propagates_without_retry_shutdown_or_cleanup_write(self):
        before = self.store.get_checkpoint()
        # TEST-ONLY SQLite commit fault, before broker I/O or any send.
        with patch.object(self.store, "_commit", side_effect=sqlite3.OperationalError(PRIVATE)) as commit:
            with self.assertRaises(RuntimeStoreError):
                self.scheduler()
        commit.assert_called_once()
        self.assertEqual(self.trace, [])
        self.assertEqual(self.store.get_checkpoint(), before)
        self.assertEqual(self.reopen(), before)
        self.scheduler()
        self.assertEqual(self.sends, [])


class SchedulerIntegrationTests(IntegrationCase):
    def test_absolute_hour_grid_serialized_and_no_drift(self):
        self.scheduler([self.wake("110"), self.wake("110"), self.wake("110"), self.wake("60")])
        self.assertEqual(self.stop.waits, [3599.0, 3600.0, 3600.0, 3600.0, 3600.0])
        times = [cp.last_processed_candle_ms for cp in self.snapshots]
        self.assertEqual(times, [49 * HOUR, 50 * HOUR, 51 * HOUR, 52 * HOUR, 53 * HOUR, 53 * HOUR])
        self.assertEqual(len(self.sends), 2)

    def test_boundary_crossed_during_startup_is_not_skipped(self):
        self.config = replace(self.config, decision_max_age_ms=4 * HOUR)
        # New test policy needs a fresh registry identity; no migration/repair.
        self.close()
        self.directory = self.enterContext(TemporaryDirectory())
        self.lock = RuntimeAccountLock(Path(self.directory), "research").acquire()
        self.store = RuntimeStore.open(self.lock, self.config, initialize=True)
        self.clock.ms = 51 * HOUR - 100
        self.prices.append("110")  # forming at the first authoritative sample
        self.time_latency = 1100
        result = self.scheduler()
        self.assertEqual((result.cycle_count, result.wake_count), (2, 1))
        self.assertEqual(self.store.get_checkpoint().bootstrap_until_ms, 49 * HOUR)
        self.assertIs(self.store.get_decision(50 * HOUR).disposition, DecisionDisposition.ACTION)
        self.assertEqual(len(self.sends), 1)
        self.assertEqual(self.stop.waits, [3599.0])

    def test_multi_hour_missed_wake_has_one_batch_and_replay_not_order_burst(self):
        result = self.scheduler([self.wake("110", hours=4)])
        self.assertEqual((result.cycle_count, result.wake_count), (2, 1))
        cp = self.store.get_checkpoint()
        self.assertEqual((cp.bootstrap_until_ms, cp.replay_until_ms), (49 * HOUR, 53 * HOUR))
        self.assertTrue(all(self.store.get_decision(i * HOUR).disposition == DecisionDisposition.REPLAY_ONLY
                            for i in range(50, 54)))
        self.assertEqual(self.sends, [])
        self.assertEqual(self.stop.waits, [3599.0, 3600.0])

    def test_transient_account_read_retries_one_then_two_seconds_only(self):
        self.account_failures = 2
        def retry(seconds):
            self.clock.advance(int(seconds * 1000))
        result = self.scheduler([retry, retry])
        self.assertEqual(result.cycle_count, 3)
        self.assertEqual(self.stop.waits[:2], [1.0, 2.0])
        self.assertEqual(sum(t[0] == "account" for t in self.trace), 3)
        self.assertIs(result.checkpoint.snapshot.stopped_from, RuntimeState.FLAT)
        self.assertEqual(self.sends, [])

    def test_transient_missing_evidence_stops_same_batch_after_three_attempts(self):
        self.account_failures = 100
        def retry(seconds):
            self.clock.advance(int(seconds * 1000))
        result = self.scheduler([retry, retry])
        self.assertEqual(result.cycle_count, 3)
        self.assertEqual(sum(t[0] == "account" for t in self.trace), 3)
        self.assertEqual(self.stop.waits[:2], [1.0, 2.0])
        self.assertEqual(self.sends, [])

    def stale(self, long):
        if long:
            self.enter()
        else:
            self.cycle()
        original = self.store.get_checkpoint().snapshot.owned_base_quantity
        self.wake("110")(0)
        self.page_latency = 61000
        stale = self.cycle()
        self.assertIs(stale.reason, RuntimeReason.EVIDENCE_MISSING)
        self.assertIs(stale.checkpoint.snapshot.state, RuntimeState.SYNCHRONIZING)
        self.assertEqual(stale.checkpoint.snapshot.owned_base_quantity, original)
        self.assertIs(stale.checkpoint.snapshot.position_evidence, PositionEvidence.LAST_KNOWN)
        boundary = len(self.trace)
        self.wake("110")(0)
        self.scheduler()
        operations = [t[0] for t in self.trace[boundary:]]
        self.assertLess(operations.index("account"), operations.index("public_time"))
        self.assertEqual(len(self.sends), int(long))

    def test_stale_flat_requires_synchronization_before_fresh_planning(self):
        self.stale(False)

    def test_stale_long_preserves_last_known_exposure_before_reconciliation(self):
        self.stale(True)


class ActivationIntegrationTests(IntegrationCase):
    def test_duplicate_account_lock_refuses_before_store_or_client_activation(self):
        before = self.store.get_checkpoint()
        second = RuntimeAccountLock(Path(self.directory), "research")
        with patch.object(RuntimeStore, "open") as opened, self.assertRaises(RuntimeLockError):
            second.acquire()
        opened.assert_not_called()
        self.assertEqual(self.trace, [])
        self.assertEqual(self.store.get_checkpoint(), before)
        self.close()
        self.lock = second.acquire()
        self.store = RuntimeStore.open(self.lock, self.config, initialize=False)
        self.scheduler()

    def mismatch(self, **change):
        self.scheduler([self.wake("110")])
        self.store.close()
        before = self.lock.database_path.read_bytes()
        count = len(self.trace)
        with self.assertRaises(RuntimeStoreError):
            RuntimeStore.open(self.lock, replace(self.config, **change), initialize=False)
        self.assertEqual(self.lock.database_path.read_bytes(), before)
        self.assertEqual(len(self.trace), count)
        self.store = RuntimeStore.open(self.lock, self.config, initialize=False)

    def test_changed_bot_identity_fails_activation_without_writes(self):
        self.mismatch(bot_id="other-bot")

    def test_changed_symbol_fails_activation_without_writes(self):
        self.mismatch(symbol="ETHUSDT", base_currency="ETH")

    def test_changed_account_binding_fails_activation_without_writes(self):
        self.mismatch(account_binding="other")

    def test_changed_strategy_digest_fails_activation_without_writes(self):
        self.mismatch(strategy_implementation_digest="f" * 64)

    def test_changed_configuration_digest_fails_activation_without_writes(self):
        self.mismatch(configuration_digest="f" * 64)

    def test_changed_buy_budget_fails_activation_without_writes(self):
        self.mismatch(buy_quote_budget=D("11"))

    def broken(self, kind):
        if kind == "relationship":
            self.enter(status="New")
        self.store.close()
        path = self.lock.database_path
        if kind == "missing":
            # Separate never-initialized canonical account, no deletion/reset.
            self.lock.release()
            self.lock = RuntimeAccountLock(Path(self.directory), "missing").acquire()
            config = replace(self.config, account_binding="missing")
            path = self.lock.database_path
            before = None
        else:
            config = self.config
            # TEST-ONLY explicit corruption of temporary isolated SQLite.
            if kind == "corrupt":
                path.write_bytes(b"synthetic-invalid-sqlite")
            else:
                with sqlite3.connect(path) as connection:
                    connection.execute("PRAGMA user_version=3" if kind == "schema" else
                                       "UPDATE checkpoint SET pending_action_kind='EXIT'")
            before = path.read_bytes()
        count = len(self.trace)
        with self.assertRaises(RuntimeStoreError):
            RuntimeStore.open(self.lock, config, initialize=False)
        self.assertEqual(path.read_bytes() if path.exists() else None, before)
        self.assertEqual(len(self.trace), count)

    def test_missing_db_does_not_initialize_or_contact_broker(self):
        self.broken("missing")

    def test_corrupt_db_has_no_repair_fallback_or_broker_access(self):
        self.broken("corrupt")

    def test_unsupported_schema_has_no_migration_or_broker_access(self):
        self.broken("schema")

    def test_broken_journal_relationship_fails_before_broker_access(self):
        self.broken("relationship")


class OwnershipIntegrationTests(IntegrationCase):
    def test_foreign_managed_open_order_halts_without_adoption_or_cancel(self):
        self.publish({"side": "Buy", "qty": "10", "marketUnit": "quoteCoin", "orderLinkId": "bot1-foreign"},
                     "foreign-order", "New")
        result = self.scheduler()
        self.assertIs(result.checkpoint.snapshot.reason, RuntimeReason.OWNERSHIP_CONFLICT)
        self.assertEqual((self.sends, self.store.list_actions(), self.store.list_fills()), ([], (), ()))

    def test_foreign_managed_execution_halts_without_ownership(self):
        self.publish({"side": "Buy", "qty": "10", "marketUnit": "quoteCoin", "orderLinkId": "bot1-foreign"},
                     "foreign-order", "Filled")
        result = self.scheduler()
        self.assertIs(result.checkpoint.snapshot.reason, RuntimeReason.OWNERSHIP_CONFLICT)
        self.assertEqual(self.store.list_fills(), ())
        self.assertEqual(self.sends, [])

    def conflict(self, field, value):
        self.enter()
        original = self.store.list_fills()
        self.remote_fills[0][field] = value
        result = self.round()
        self.assertIs(result.checkpoint.snapshot.state, RuntimeState.HALTED)
        self.assertIs(result.checkpoint.snapshot.reason, RuntimeReason.OWNERSHIP_CONFLICT)
        self.assertEqual(self.store.list_fills(), original)
        self.assertEqual(len(self.sends), 1)

    def test_execution_quantity_conflict_never_overwrites_durable_fill(self):
        self.conflict("execQty", "0.04")

    def test_execution_price_conflict_never_overwrites_durable_fill(self):
        self.conflict("execPrice", "101")

    def test_execution_fee_conflict_never_overwrites_durable_fill(self):
        self.conflict("execFee", "0.00004")

    def test_execution_fee_currency_conflict_never_overwrites_durable_fill(self):
        self.conflict("feeCurrency", "USDT")

    def test_execution_identity_conflict_never_overwrites_durable_fill(self):
        self.conflict("orderLinkId", "bot1-wrong-identity")

    def test_normalized_exit_rounds_down_and_actual_fill_leaves_exact_owned_remainder(self):
        self.buy_quantity = D("0.0500009")
        result = self.scheduler([self.wake("110"), self.wake("110"), self.wake("110"), self.wake("60")])
        # This modified fill quantity changes EXIT identity, by contract.
        exit_action = next(a for a in self.store.list_actions() if a.side == "SELL")
        self.assertEqual(exit_action.authorized_amount, D("0.0499509"))
        self.assertEqual(exit_action.submitted_amount, D("0.04995"))
        self.assertIs(result.checkpoint.snapshot.stopped_from, RuntimeState.LONG)
        self.assertEqual(result.checkpoint.snapshot.owned_base_quantity, D("0.0000009"))
        self.assertEqual(len(self.sends), 2)


class ReadFailureIntegrationTests(IntegrationCase):
    def assert_fatal_without_retry(self, result, reason):
        self.assertEqual(result.cycle_count, 1)
        self.assertIs(result.exit_reason, SchedulerExit.HALTED)
        self.assertIs(result.checkpoint.snapshot.state, RuntimeState.HALTED)
        self.assertIs(result.checkpoint.snapshot.reason, reason)
        self.assertEqual(self.stop.waits, [])
        self.assertEqual((self.sends, self.cancels), ([], []))
        self.assertEqual((self.store.list_actions(), self.store.list_fills()), ((), ()))
        self.assertNotIn(PRIVATE, repr(result))
        self.audit("fatal-read")

    def test_malformed_wallet_reproducer_is_one_cycle_halt_without_retry(self):
        def malformed(**params):
            self.external("account", params)
            return {"retCode": 0, "time": self.clock.ms, "result": {"list": []}}
        with patch.object(self.session, "get_wallet_balance", side_effect=malformed) as read:
            result = self.scheduler()
        self.assert_fatal_without_retry(result, RuntimeReason.INCONSISTENT_EVIDENCE)
        read.assert_called_once_with(accountType="UNIFIED")
        self.assertEqual([name for name, *_ in self.trace], ["account"])

    def test_unsafe_demo_reproducer_is_one_cycle_halt_before_sdk_io(self):
        self.session.demo = False
        self.assert_fatal_without_retry(self.scheduler(), RuntimeReason.INVALID_CONFIGURATION)
        self.assertEqual(self.trace, [])

    def test_arbitrary_sdk_failure_is_permanent_and_has_no_retry(self):
        def permanent(**params):
            self.external("account", params)
            raise RuntimeError(PRIVATE)
        with patch.object(self.session, "get_wallet_balance", side_effect=permanent) as read:
            result = self.scheduler()
        self.assert_fatal_without_retry(result, RuntimeReason.INCONSISTENT_EVIDENCE)
        read.assert_called_once()

    def test_unclassified_api_code_is_permanent_and_has_no_retry(self):
        def permanent(**params):
            self.external("account", params)
            return {"retCode": 987654, "retMsg": PRIVATE}
        with patch.object(self.session, "get_wallet_balance", side_effect=permanent) as read:
            result = self.scheduler()
        self.assert_fatal_without_retry(result, RuntimeReason.INCONSISTENT_EVIDENCE)
        read.assert_called_once()


class PublicMarketFailureIntegrationTests(IntegrationCase):
    def assert_fatal_public_read(self, result):
        self.assertEqual(result.cycle_count, 1)
        self.assertIs(result.exit_reason, SchedulerExit.HALTED)
        self.assertIs(result.last_cycle.outcome, CycleOutcome.HALTED)
        self.assertIs(result.checkpoint.snapshot.state, RuntimeState.HALTED)
        self.assertIs(result.checkpoint.snapshot.reason, RuntimeReason.INCONSISTENT_EVIDENCE)
        self.assertEqual(self.stop.waits, [])
        self.assertEqual([name for name, *_ in self.trace if name.startswith("public_")], ["public_time"])
        self.assertEqual((self.sends, self.cancels), ([], []))
        self.assertEqual((self.store.list_actions(), self.store.list_fills()), ((), ()))
        self.assertNotIn(PRIVATE, repr(result))
        self.audit("fatal-public-read")
        for path in Path(self.directory).rglob("*"):
            if path.is_file():
                self.assertNotIn(PRIVATE.encode(), path.read_bytes())

    def test_malformed_public_time_reproducer_halts_without_retry(self):
        payload = {"retCode": 0, "time": self.clock.ms,
                   "result": {"timeSecond": str(self.clock.ms // 1000), "timeNano": PRIVATE}}
        with self.public_time_failure(payload):
            result = self.scheduler()
        self.assert_fatal_public_read(result)

    def test_unknown_public_api_code_reproducer_halts_without_retry(self):
        with self.public_time_failure({"retCode": 987654, "retMsg": PRIVATE}):
            result = self.scheduler()
        self.assert_fatal_public_read(result)


class PreservationIntegrationTests(IntegrationCase):
    def test_terminal_return_loss_round_trip_matches_uninterrupted_economic_and_identity_truth(self):
        original = self.store.record_observation
        crashed = False
        def terminal_loss(action, *args, **kwargs):
            nonlocal crashed
            original(action, *args, **kwargs)
            if not crashed and action.phase == ActionPhase.TERMINAL_CONFIRMED:
                crashed = True
                raise RuntimeStoreError("Synthetic lost terminal return")
        # TEST-ONLY process loss after terminal entry commit.
        with patch.object(self.store, "record_observation", side_effect=terminal_loss):
            with self.assertRaises(RuntimeStoreError):
                self.scheduler([self.wake("110")])
        self.reopen()
        self.scheduler([self.wake("110"), self.wake("110"), self.wake("60")])
        own = self.logical_history(), self.store.list_actions(), self.store.list_fills(), self.store.get_checkpoint().snapshot
        normal = IntegrationCase()
        normal.setUp()
        try:
            history, actions, fills, snapshot = normal.golden()
            self.assertEqual(own[0], history)
            self.assertEqual(set(own[1]), set(actions))
            self.assertEqual(set(own[2]), set(fills))
            self.assertEqual(own[3], snapshot)
        finally:
            self.assertTrue(normal.doCleanups(), "The uninterrupted scenario must clean up without guard failures")
        self.assertEqual(len(self.sends), 2)

    def test_private_transport_error_is_absent_from_results_logs_and_database(self):
        self.send_mode = "ambiguous_missing"
        output = StringIO()
        with redirect_stdout(output), redirect_stderr(output):
            result = self.enter()
        self.assertNotIn(PRIVATE, output.getvalue())
        self.assertNotIn(PRIVATE, repr(result))
        self.assertNotIn(PRIVATE, repr((self.store.list_actions(), self.store.list_fills())))
        for path in Path(self.directory).rglob("*"):
            if path.is_file():
                self.assertNotIn(PRIVATE.encode(), path.read_bytes())

    def test_runtime_and_harness_have_no_historical_fill_engine_or_stage_seven_sizing(self):
        paths = list((ROOT / "src/trading_lab/runtime").glob("*.py")) + [Path(__file__)]
        for path in paths:
            tree = ast.parse(path.read_text())
            imports = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
            imports += [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
            # The frozen cycle shares the pure output validator; it imports no
            # historical execution/fill engine and uses no backtest fills.
            self.assertFalse(any(("backtest" in name and name != "backtest.strategy_validation")
                                 or "risk.sizing" in name for name in imports), path.name)
            identifiers = [node.id for node in ast.walk(tree) if isinstance(node, ast.Name)]
            attributes = [node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)]
            self.assertNotIn("position_fraction", identifiers + attributes)

    def test_frozen_production_hashes_match_owner_reviewed_fef6_baseline(self):
        # Preserve frozen sources with the approved account-read and public-
        # market/cycle corrections. Only their corresponding hashes are refreshed.
        # Owner-approved cycle/reconciliation/scheduler callback plumbing only.
        hashes = {
            "runtime/__init__.py": "8843b5105846f5386e9ac799f06b8446688043482618cbb8d3fc5a6655f40b60",
            "runtime/cycle.py": "75a03537819ce66cff38c871a800ee461d35bd1c2995ba599ae32bd2338a4fce",
            "runtime/locking.py": "b10c5a8ac5e4ed4b8a7616b656602319c4e238eb0d2404fc2d31e6d636048273",
            "runtime/planner.py": "e97b0f9c709e909c56f132cfd5a718a3fbb8a488debb0c71823415adb0605686",
            "runtime/reconciliation.py": "d67f816fbeb225b311546f1bf99a6176b77b7bf57042818fecad99fbbd70aa33",
            "runtime/recovery.py": "847a7634018925c9815f52e2f9ff7654ab422ea61fd877fdb418c1806d1b58f4",
            "runtime/scheduler.py": "3f65cb158118811c4994785b04f979cd93fc3a36e1119cca4dc98bd6d39d2c91",
            "runtime/state.py": "014b92aca145d61a57df230d3c3747025768090d2b96cdeaa97a96e5ad2675bc",
            "runtime/store.py": "5ec4e7ebcb7c31272a9dd25bd5a283faedee333c767b426317329dc36da132ed",
            "data/closed_candles.py": "1c2068060dd73729f8bd3468901fd9c34b3807509906801f8f03af1d83914af6",
            "exchange/bybit_public_market.py": "62183a274d7a04a0aaac5642a0801ca61221717e2ac344c5ab77aeabad504b1b",
            "exchange/bybit_demo.py": "322500c83ce6077c51b8d7ba966b421c661ced7888bde3052f8d4892900eb748",
            "exchange/bybit_spot_rules.py": "a604ece32539d575225c9a109c61f8b2d5a5f664d5a8fa580733b20326067fcc",
            "exchange/bybit_demo_read_only.py": "132310622c87e9a6542cbfe6a933db6b0c53132893c84667021d3c7395c8b38e",
            "exchange/bybit_demo_orders.py": "fce3ab3569d91180dbaa1b638e0ce091414d1619b656e4b87ba8e3ab9ec0e3c0",
            "strategies/ema_trend.py": "098a12ebdb3a3e30260b7b86a49ba5146ca7ff9d3ae035ee5adc272a69227fee",
        }
        for relative, expected in hashes.items():
            self.assertEqual(hashlib.sha256((ROOT / "src/trading_lab" / relative).read_bytes()).hexdigest(), expected, relative)
        self.assertEqual(hashlib.sha256((ROOT / "scripts/bybit_demo_smoke.py").read_bytes()).hexdigest(),
                         "c1ef1f3ccce87266d49b5e1f6b4735adb637a5e029808beec9abb7b1b4d89bb1")
