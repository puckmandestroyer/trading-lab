"""Offline single-cycle integration, real durable journal and crash boundaries."""

import ast
from copy import deepcopy
from dataclasses import FrozenInstanceError, fields, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal, localcontext
import inspect
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

import pandas as pd
import requests

from trading_lab.data.closed_candles import (
    ClosedCandlePrefix, MarketCandle, MarketDataInputError, MarketDataIntegrityError,
    MarketDataReadFailureKind, MarketDataResponseError, MarketDataTransportError,
    StaleMarketDataError, validate_closed_prefix,
)
from trading_lab.exchange.account_state import (
    AccountState, BrokerOrderNotFoundError, BrokerReadError, BrokerReadFailureKind,
    CurrencyBalance, ExecutionState, OrderState, OrderStatus,
)
from trading_lab.exchange.bybit_demo_orders import BybitDemoOrderAdapter
import trading_lab.exchange.bybit_demo_orders as adapter_module
from trading_lab.exchange.order_actions import SpotMarketOrderAcknowledgement
from trading_lab.runtime.cycle import CycleError, CycleOutcome, SingleCycleResult, run_single_cycle
import trading_lab.runtime.cycle as module
from trading_lab.runtime.planner import DecisionMode, PlanKind
from trading_lab.runtime.locking import RuntimeAccountLock
from trading_lab.runtime.reconciliation import reconcile_startup
from trading_lab.runtime.state import PositionEvidence, RuntimeEvent, RuntimeEventType, RuntimeReason, RuntimeState, transition_runtime_state
from trading_lab.runtime.store import ActionPhase, DecisionDisposition, RuntimeStore, RuntimeStoreError
from trading_lab.strategies.ema_trend import generate_ema_signals
from tests.test_bybit_demo_orders import FakeActionSession, ack_response
from tests.test_runtime_store import HOUR, StoreCase, configuration
from tests.test_runtime_planner import canonical, checkpoint
from tests import test_runtime_integration_regression as integration_fixtures


D = Decimal
PRIVATE = "private-offline-cycle-marker"
DEFAULT = object()


def utc(ms):
    return datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(milliseconds=ms)


def candles(prices):
    return tuple(MarketCandle("BTCUSDT", "60", i * HOUR, D(price), D(price), D(price), D(price), D("1.25"))
                 for i, price in enumerate(prices))


class FakeMarketReader:
    def __init__(self, case):
        self.case, self.calls, self.error, self.override = case, [], None, None

    def get_closed_candles(self, **kwargs):
        case = self.case
        case.assertFalse(case.store._connection.in_transaction)
        case.trace.append("market")
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.override if self.override is not None else case.prefix()


class FakeBroker:
    """Normalized reads, with explicit synthetic observations after fake sends."""

    def __init__(self, case):
        self.case, self.calls, self.errors = case, [], {}
        self.orders, self.fills = {}, []
        self.status, self.buy_quantity, self.fee, self.fee_currency = OrderStatus.FILLED, D("0.05"), D("0"), "BTC"

    def observe(self, name):
        case = self.case
        case.assertFalse(case.store._connection.in_transaction)
        case.trace.append("broker:" + name)
        self.calls.append(name)
        if name in self.errors:
            raise self.errors[name]
        return utc(case.now_ms)

    def get_account_state(self):
        stamp = self.observe("account")
        # Extra BTC is coverage, never ownership or an order sizing input.
        return AccountState("bybit-demo", "research", "USD", D("1000"), D("1000"), D("1000"),
                            (CurrencyBalance("BTC", D("3"), D("3"), D("0")),), stamp, stamp)

    def get_open_orders(self, symbol=None):
        stamp = self.observe("open")
        return tuple(replace(order, broker_timestamp=stamp, fetched_at=stamp) for order in self.orders.values()
                     if order.status not in (OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED, OrderStatus.EXPIRED))

    def get_order(self, order_id):
        stamp = self.observe("order")
        if order_id not in self.orders:
            raise BrokerOrderNotFoundError("Synthetic absence")
        return replace(self.orders[order_id], broker_timestamp=stamp, fetched_at=stamp)

    def get_executions(self, order_id=None, symbol=None):
        stamp = self.observe("executions")
        return tuple(replace(fill, broker_timestamp=stamp, fetched_at=stamp) for fill in self.fills
                     if order_id is None or fill.broker_order_id == order_id)

    def publish(self, params, order_id):
        case = self.case
        stamp, requested = utc(case.now_ms), D(params["qty"])
        side = "BUY" if params["side"] == "Buy" else "SELL"
        unit = "QUOTE" if side == "BUY" else "BASE"
        quantity = (self.buy_quantity if side == "BUY" else requested) if self.status == OrderStatus.FILLED else (
            D("0.02") if self.status == OrderStatus.PARTIALLY_FILLED else D("0"))
        quote = quantity * D("100")
        filled = quote if unit == "QUOTE" else quantity
        self.orders[order_id] = OrderState(
            "bybit-demo", "research", order_id, "BTCUSDT", side, "MARKET", self.status,
            {OrderStatus.OPEN: "New", OrderStatus.PARTIALLY_FILLED: "PartiallyFilled",
             OrderStatus.FILLED: "Filled", OrderStatus.UNKNOWN: "FutureStatus"}[self.status],
            unit, requested, filled, requested - filled, quantity, quote,
            D("100") if quantity else None, None, None, stamp, stamp, stamp, stamp, params["orderLinkId"],
        )
        if quantity:
            self.fills.append(ExecutionState("bybit-demo", "research", "exec-" + order_id, order_id,
                                             params["orderLinkId"], "BTCUSDT", side, quantity, D("100"),
                                             self.fee, self.fee_currency, stamp, stamp, stamp))


class TransactionCheckedSession(FakeActionSession):
    def __init__(self, case):
        super().__init__()
        self.case, self.raw_ack, self.publish_on_error = case, DEFAULT, False

    def get_instruments_info(self, **params):
        self.case.assertFalse(self.case.store._connection.in_transaction)
        self.case.trace.append("metadata")
        self.case.assertIs(self.case.store.get_action(self.case.pending_id()).phase, ActionPhase.PREPARED)
        return super().get_instruments_info(**params)

    def place_order(self, **params):
        case = self.case
        case.assertFalse(case.store._connection.in_transaction)
        action = case.store.get_action(case.pending_id())
        case.assertIs(action.phase, ActionPhase.ATTEMPT_STARTED)
        case.assertEqual(action.attempt_count, 1)
        case.assertIs(case.store.get_decision(action.candle_open_ms).disposition, DecisionDisposition.ACTION)
        case.assertEqual(params["orderLinkId"], action.order_link_id)
        case.assertLessEqual(D(params["qty"]), action.authorized_amount)
        case.trace.append("send")
        order_id = "order-" + str(len(case.order_adapter.calls))
        self.placement = ack_response(order_id, params["orderLinkId"]) if self.raw_ack is DEFAULT else self.raw_ack
        if isinstance(self.placement, dict):
            self.placement["time"] = case.now_ms
        if self.publish_on_error or ("place_order" not in self.errors and self.raw_ack is DEFAULT):
            case.broker.publish(params, order_id)
        return super().place_order(**params)


class FakeOrderAdapter:
    """Compose the real frozen Stage 9.5 adapter with an entirely fake session."""

    def __init__(self, case):
        self.case, self.calls, self.change_guard, self.receipt_change = case, [], False, None
        self.adapter = BybitDemoOrderAdapter(case.session)

    def place_market_order(self, request, *, before_submit):
        case = self.case
        case.assertFalse(case.store._connection.in_transaction)
        case.assertIs(case.store.get_action(case.pending_id()).phase, ActionPhase.PREPARED)
        self.calls.append(request)

        def callback():
            before_submit()
            if self.change_guard:
                case.session.demo = False
                case.broker.errors["account"] = BrokerReadError(BrokerReadFailureKind.INVALID_CONFIGURATION)

        receipt = self.adapter.place_market_order(request, before_submit=callback)
        return self.receipt_change(receipt) if self.receipt_change else receipt


class CycleCase(StoreCase):
    def runtime_configuration(self):
        # Explicit test policy: permit a pending order across an hourly close.
        return replace(configuration(), reconciliation_timeout_ms=3 * HOUR)

    def setUp(self):
        self.directory = self.enterContext(TemporaryDirectory())
        self.lock = self.enterContext(RuntimeAccountLock(Path(self.directory), "research"))
        self.config = self.runtime_configuration()
        self.store = RuntimeStore.open(self.lock, self.config, initialize=True)
        self.addCleanup(self.store.close)
        self.enterContext(patch.object(requests.Session, "send", side_effect=AssertionError("No broker network")))
        self.enterContext(patch.object(requests.Session, "request", side_effect=AssertionError("No broker network")))
        self.enterContext(patch("socket.create_connection", side_effect=AssertionError("No broker network")))
        self.trace, self.prices, self.now_ms = [], ["100"] * 50, 50 * HOUR + 1000
        self.market, self.broker = FakeMarketReader(self), FakeBroker(self)
        self.session = TransactionCheckedSession(self)
        self.order_adapter = FakeOrderAdapter(self)
        mocked_datetime = self.enterContext(patch.object(adapter_module, "datetime", wraps=datetime))
        mocked_datetime.now.side_effect = lambda tz=None: utc(self.now_ms)

    def prefix(self):
        return ClosedCandlePrefix("BTCUSDT", "60", 0, len(self.prices) * HOUR,
                                  self.now_ms, self.now_ms, candles(self.prices))

    def pending_id(self):
        return self.store.get_checkpoint().snapshot.pending_action.logical_action_id

    def advance(self, *prices):
        self.prices.extend(prices)
        self.now_ms = len(self.prices) * HOUR + 1000

    def run_cycle(self):
        return run_single_cycle(self.store, self.market, self.broker, self.order_adapter,
                                utc_now=lambda: utc(self.now_ms), monotonic=lambda: 1.0)

    def bootstrap(self):
        result = self.run_cycle()
        self.assertIs(result.outcome, CycleOutcome.BOOTSTRAP)
        self.assertEqual(self.order_adapter.calls, [])
        self.trace.clear()
        return result

    def entry(self, *, status=OrderStatus.FILLED):
        self.bootstrap()
        self.broker.status = status
        self.advance("110")
        return self.run_cycle()

    def action(self, result):
        return self.store.get_action(result.logical_action_id)

    def assert_no_send(self):
        self.assertFalse(any(name in ("place_order", "cancel_order") for name, _ in self.session.calls))


class HistoryAndProgressTests(CycleCase):
    def test_interrupted_bootstrap_last_candle_remains_historical_on_restart(self):
        self.advance("110")
        original = self.store.commit_decision

        def interrupt(record, *args, **kwargs):
            if record.candle_open_ms == 50 * HOUR:
                raise RuntimeStoreError("Synthetic interruption")
            return original(record, *args, **kwargs)

        with patch.object(self.store, "commit_decision", side_effect=interrupt), self.assertRaises(RuntimeStoreError):
            self.run_cycle()
        self.reopen()
        self.assertEqual(self.store.get_checkpoint().bootstrap_until_ms, 50 * HOUR)
        self.assertEqual(self.store.get_checkpoint().last_processed_candle_ms, 49 * HOUR)
        result = self.run_cycle()
        self.assertIs(result.outcome, CycleOutcome.BOOTSTRAP)
        self.assertIs(self.store.get_decision(50 * HOUR).disposition, DecisionDisposition.BOOTSTRAP)
        self.assertEqual(result.checkpoint.snapshot.desired_position, 1)
        self.assert_no_send()

    def test_interrupted_backlog_last_candle_remains_replay_on_restart(self):
        self.bootstrap()
        self.advance("100", "110")
        original = self.store.commit_decision

        def interrupt(record, *args, **kwargs):
            if record.candle_open_ms == 51 * HOUR:
                raise RuntimeStoreError("Synthetic interruption")
            return original(record, *args, **kwargs)

        with patch.object(self.store, "commit_decision", side_effect=interrupt), self.assertRaises(RuntimeStoreError):
            self.run_cycle()
        self.reopen()
        self.assertEqual(self.store.get_checkpoint().replay_until_ms, 51 * HOUR)
        result = self.run_cycle()
        self.assertIs(result.outcome, CycleOutcome.REPLAY_ONLY)
        self.assertIs(self.store.get_decision(51 * HOUR).disposition, DecisionDisposition.REPLAY_ONLY)
        self.assert_no_send()

    def test_initial_bootstrap_commits_complete_prefix_without_order(self):
        result = self.bootstrap()
        self.assertEqual(result.processed_candle_count, 50)
        self.assertEqual(result.processed_candle_open_ms, tuple(i * HOUR for i in range(50)))
        self.assertEqual(result.checkpoint.last_processed_candle_ms, 49 * HOUR)
        self.assertEqual(result.checkpoint.bootstrap_until_ms, 49 * HOUR)
        self.assertEqual(self.store.list_actions(), ())
        self.assertTrue(all(self.store.get_decision(i * HOUR).disposition == DecisionDisposition.BOOTSTRAP for i in range(50)))
        self.assert_no_send()

    def test_historical_long_desire_never_buys_at_startup(self):
        self.advance("110")
        result = self.bootstrap()
        self.assertEqual(result.checkpoint.snapshot.desired_position, 1)
        self.assertEqual(result.checkpoint.snapshot.owned_base_quantity, D("0"))
        self.assertIs(result.checkpoint.snapshot.state, RuntimeState.FLAT)
        self.assertEqual(self.store.list_actions(), ())
        self.assert_no_send()

    def test_restart_backlog_including_entry_is_replay_only(self):
        self.bootstrap()
        self.reopen()
        self.advance("110", "120")
        result = self.run_cycle()
        self.assertIs(result.outcome, CycleOutcome.REPLAY_ONLY)
        self.assertEqual(result.processed_candle_count, 2)
        self.assertEqual(result.checkpoint.replay_until_ms, 51 * HOUR)
        self.assertTrue(all(self.store.get_decision(i * HOUR).disposition == DecisionDisposition.REPLAY_ONLY for i in (50, 51)))
        self.assertEqual(result.checkpoint.snapshot.desired_position, 1)
        self.assert_no_send()

    def test_next_future_candle_uses_live_after_replay_cutoff(self):
        self.bootstrap()
        self.advance("100", "100")
        self.run_cycle()
        self.advance("110")
        result = self.run_cycle()
        self.assertIs(result.planner_kind, PlanKind.PLACE_BUY)
        self.assertEqual(len(self.order_adapter.calls), 1)
        self.assertEqual(result.checkpoint.replay_until_ms, 51 * HOUR)

    def test_single_satisfied_hold_commits_noop_and_frontier(self):
        self.bootstrap()
        self.advance("100")
        result = self.run_cycle()
        self.assertIs(result.outcome, CycleOutcome.NOOP)
        self.assertIs(self.store.get_decision(50 * HOUR).disposition, DecisionDisposition.NOOP)
        self.assertEqual(result.processed_candle_count, 1)
        self.assertEqual(result.checkpoint.last_processed_candle_ms, 50 * HOUR)
        self.assert_no_send()

    def test_already_processed_prefix_verifies_history_without_second_decision(self):
        result = self.entry()
        decisions = tuple(self.store.get_decision(i * HOUR) for i in range(51))
        again = self.run_cycle()
        self.assertIs(again.outcome, CycleOutcome.NO_NEW_DATA)
        self.assertEqual(again.processed_candle_count, 0)
        self.assertEqual(len(self.order_adapter.calls), 1)
        self.assertEqual(tuple(self.store.get_decision(i * HOUR) for i in range(51)), decisions)
        self.assertEqual(self.store.get_action(result.logical_action_id).logical_action_id, result.logical_action_id)

    def test_changed_historical_candle_halts_without_rewrite(self):
        self.bootstrap()
        original = self.store.get_candle(0)
        self.prices[0] = "99"
        result = self.run_cycle()
        self.assertIs(result.outcome, CycleOutcome.HALTED)
        self.assertEqual(self.store.get_candle(0), original)
        self.assert_no_send()

    def test_changed_reconstructed_decision_halts_without_rewrite(self):
        self.bootstrap()
        original = self.store.get_decision(49 * HOUR)
        generate = module.generate_ema_signals

        def changed(frame, **kwargs):
            output = generate(frame, **kwargs)
            output.loc[49, ["signal", "desired_position"]] = ["LONG_ENTRY", 1]
            return output

        with patch.object(module, "generate_ema_signals", side_effect=changed):
            result = self.run_cycle()
        self.assertIs(result.outcome, CycleOutcome.HALTED)
        self.assertEqual(self.store.get_decision(49 * HOUR), original)
        self.assert_no_send()


class HistoricalSegmentationCorrectionTests(CycleCase):
    def interrupt_before(self, index):
        commit = self.store.commit_decision

        def interrupt(record, *args, **kwargs):
            if record.candle_open_ms == index * HOUR:
                raise RuntimeStoreError("Synthetic interruption")
            return commit(record, *args, **kwargs)

        with patch.object(self.store, "commit_decision", side_effect=interrupt), self.assertRaises(RuntimeStoreError):
            self.run_cycle()
        self.reopen()

    def assert_bootstrap_range(self, end=50):
        self.assertTrue(all(self.store.get_decision(i * HOUR).disposition == DecisionDisposition.BOOTSTRAP
                            for i in range(end)))

    def test_early_bootstrap_crash_keeps_all_remaining_original_history(self):
        self.interrupt_before(11)
        self.assertEqual(self.store.get_checkpoint().last_processed_candle_ms, 10 * HOUR)
        result = self.run_cycle()
        self.assertEqual(result.processed_candle_open_ms, tuple(i * HOUR for i in range(11, 50)))
        self.assert_bootstrap_range()
        self.assertEqual(result.checkpoint.bootstrap_until_ms, 49 * HOUR)
        self.assertIsNone(result.checkpoint.replay_until_ms)
        self.assert_no_send()

    def test_early_bootstrap_crash_and_later_backlog_use_separate_cutoffs(self):
        self.interrupt_before(11)
        self.advance(*(["110"] * 6))
        result = self.run_cycle()
        self.assert_bootstrap_range()
        self.assertTrue(all(self.store.get_decision(i * HOUR).disposition == DecisionDisposition.REPLAY_ONLY
                            for i in range(50, 56)))
        self.assertEqual(result.checkpoint.bootstrap_until_ms, 49 * HOUR)
        self.assertEqual(result.checkpoint.replay_until_ms, 55 * HOUR)
        self.assertEqual(result.processed_candle_count, 45)
        self.assertEqual(self.store.list_actions(), ())
        self.assert_no_send()

    def test_first_future_candle_after_mixed_history_may_be_live(self):
        self.interrupt_before(11)
        self.advance(*(["100"] * 6))
        self.run_cycle()
        self.assert_no_send()
        self.advance("110")
        result = self.run_cycle()
        self.assertIs(result.planner_kind, PlanKind.PLACE_BUY)
        self.assertIs(self.store.get_decision(56 * HOUR).disposition, DecisionDisposition.ACTION)
        self.assertEqual(result.processed_candle_open_ms, (56 * HOUR,))
        self.assertEqual(result.checkpoint.bootstrap_until_ms, 49 * HOUR)
        self.assertEqual(result.checkpoint.replay_until_ms, 55 * HOUR)
        self.assertEqual(sum(name == "place_order" for name, _ in self.session.calls), 1)

    def test_interrupted_replay_with_multiple_remaining_candles_stays_replay(self):
        self.bootstrap()
        self.advance(*(["110"] * 6))
        self.interrupt_before(52)
        result = self.run_cycle()
        self.assert_bootstrap_range()
        self.assertTrue(all(self.store.get_decision(i * HOUR).disposition == DecisionDisposition.REPLAY_ONLY
                            for i in range(50, 56)))
        self.assertEqual(result.processed_candle_open_ms, tuple(i * HOUR for i in range(52, 56)))
        self.assertEqual(result.checkpoint.bootstrap_until_ms, 49 * HOUR)
        self.assertEqual(result.checkpoint.replay_until_ms, 55 * HOUR)
        self.assert_no_send()

    def test_reserved_bootstrap_survives_crash_before_first_decision(self):
        self.interrupt_before(0)
        self.assertIsNone(self.store.get_checkpoint().last_processed_candle_ms)
        self.assertEqual(self.store.get_checkpoint().bootstrap_until_ms, 49 * HOUR)
        self.advance("110", "110")
        result = self.run_cycle()
        self.assert_bootstrap_range()
        for index in (50, 51):
            self.assertIs(self.store.get_decision(index * HOUR).disposition, DecisionDisposition.REPLAY_ONLY)
        self.assertEqual(result.checkpoint.bootstrap_until_ms, 49 * HOUR)
        self.assertEqual(result.checkpoint.replay_until_ms, 51 * HOUR)
        self.assert_no_send()


class PreSubmitTimingCase(CycleCase):
    def run_with_metadata_time(self, target_ms):
        metadata = self.session.get_instruments_info
        place = self.order_adapter.place_market_order
        self.boundary = Mock()

        def delayed_metadata(**kwargs):
            response = metadata(**kwargs)
            self.now_ms = target_ms
            return response

        def with_boundary(request, *, before_submit):
            def callback():
                self.boundary()
                return before_submit()
            return place(request, before_submit=callback)

        with patch.object(self.session, "get_instruments_info", side_effect=delayed_metadata), \
             patch.object(self.order_adapter, "place_market_order", side_effect=with_boundary), \
             patch.object(self.store, "start_attempt", wraps=self.store.start_attempt) as attempt:
            self.attempt = attempt
            return self.run_cycle()

    def assert_unsent_consumed(self, result, previous_sends=0):
        self.boundary.assert_called_once_with()
        self.attempt.assert_not_called()
        action = self.action(result)
        self.assertIs(result.outcome, CycleOutcome.ABANDONED_UNSENT)
        self.assertIs(action.phase, ActionPhase.ABANDONED_UNSENT)
        self.assertEqual(action.attempt_count, 0)
        self.assertIsNone(result.checkpoint.snapshot.pending_action)
        decision = self.store.get_decision(action.candle_open_ms)
        self.assertIs(decision.disposition, DecisionDisposition.ACTION)
        self.assertEqual(decision.action_id, action.logical_action_id)
        self.assertEqual(sum(name == "place_order" for name, _ in self.session.calls), previous_sends)
        self.assertIn(action, self.store.list_actions())
        # A subsequent invocation reconciles, but cannot resend this consumed ID.
        self.market.error = StaleMarketDataError("Synthetic stale market")
        calls = len(self.order_adapter.calls)
        self.run_cycle()
        self.assertEqual(len(self.order_adapter.calls), calls)
        self.assertEqual(self.store.get_action(action.logical_action_id), action)
        self.assertEqual(sum(name == "place_order" for name, _ in self.session.calls), previous_sends)


class PreSubmitFreshnessCorrectionTests(PreSubmitTimingCase):
    def test_metadata_delay_at_exact_decision_age_limit_may_send(self):
        self.bootstrap()
        self.advance("110")
        result = self.run_with_metadata_time(51 * HOUR + self.config.decision_max_age_ms)
        self.boundary.assert_called_once_with()
        self.attempt.assert_called_once()
        self.assertIs(result.outcome, CycleOutcome.OBSERVED)
        self.assertEqual(sum(name == "place_order" for name, _ in self.session.calls), 1)

    def test_metadata_delay_one_ms_past_decision_age_is_abandoned_unsent(self):
        self.bootstrap()
        self.advance("110")
        result = self.run_with_metadata_time(51 * HOUR + self.config.decision_max_age_ms + 1)
        self.assert_unsent_consumed(result)
        self.assertIs(result.checkpoint.snapshot.state, RuntimeState.FLAT)
        self.assertEqual(result.checkpoint.snapshot.owned_base_quantity, D("0"))

    def test_expired_sell_preserves_exact_long_inventory(self):
        self.broker.buy_quantity = D("0.0500009")
        self.entry()
        self.advance("80")
        result = self.run_with_metadata_time(52 * HOUR + self.config.decision_max_age_ms + 1)
        self.assert_unsent_consumed(result, previous_sends=1)
        self.assertIs(result.checkpoint.snapshot.state, RuntimeState.LONG)
        self.assertEqual(result.checkpoint.snapshot.owned_base_quantity, D("0.0500009"))

    def test_regressing_metadata_clock_stops_without_attempt_or_abandon(self):
        self.bootstrap()
        self.advance("110")
        with patch.object(self.store, "abandon_prepared") as abandon, self.assertRaises(CycleError):
            self.run_with_metadata_time(self.now_ms - 1)
        self.boundary.assert_called_once_with()
        self.attempt.assert_not_called()
        abandon.assert_not_called()
        self.assertIs(self.store.get_action(self.pending_id()).phase, ActionPhase.PREPARED)
        self.assert_no_send()


class PreSubmitDeadlineCorrectionTests(PreSubmitTimingCase):
    def runtime_configuration(self):
        # Keep the decision fresh long enough to isolate the action deadline.
        return replace(super().runtime_configuration(), decision_max_age_ms=4 * HOUR, observation_max_age_ms=4 * HOUR)

    def test_metadata_delay_one_ms_before_action_deadline_may_send(self):
        self.bootstrap()
        self.advance("110")
        result = self.run_with_metadata_time(51 * HOUR + self.config.reconciliation_timeout_ms - 1)
        self.boundary.assert_called_once_with()
        self.attempt.assert_called_once()
        self.assertIs(result.outcome, CycleOutcome.OBSERVED)
        self.assertEqual(sum(name == "place_order" for name, _ in self.session.calls), 1)

    def test_metadata_delay_at_action_deadline_is_abandoned_unsent(self):
        self.bootstrap()
        self.advance("110")
        result = self.run_with_metadata_time(51 * HOUR + self.config.reconciliation_timeout_ms)
        self.assert_unsent_consumed(result)


class MarketFreshnessCorrectionTests(CycleCase):
    def assert_freshness_lost(self, result, quantity, transitions):
        snapshot = result.checkpoint.snapshot
        self.assertIs(snapshot.state, RuntimeState.SYNCHRONIZING)
        self.assertIs(snapshot.position_evidence, PositionEvidence.LAST_KNOWN)
        self.assertEqual(snapshot.owned_base_quantity, quantity)
        self.assertIsNone(snapshot.pending_action)
        self.assertEqual(snapshot, self.store.get_checkpoint().snapshot)
        self.assertTrue(any(call.args[0].state in (RuntimeState.FLAT, RuntimeState.LONG)
                            and call.args[1].kind == RuntimeEventType.FRESHNESS_LOST
                            for call in transitions.call_args_list))
        self.assertIs(result.reason, RuntimeReason.EVIDENCE_MISSING)
        self.assertEqual(result.processed_candle_count, 0)

    def stale_read(self):
        self.market.error = StaleMarketDataError("Synthetic stale market")
        with patch.object(module, "transition_runtime_state", wraps=transition_runtime_state) as transitions:
            result = self.run_cycle()
        return result, transitions

    def stale_prefix(self):
        self.advance("110")
        self.now_ms += self.config.decision_max_age_ms
        with patch.object(module, "transition_runtime_state", wraps=transition_runtime_state) as transitions:
            result = self.run_cycle()
        return result, transitions

    def test_stale_reader_from_flat_persists_synchronizing_last_known_zero(self):
        self.bootstrap()
        result, transitions = self.stale_read()
        self.assert_freshness_lost(result, D("0"), transitions)
        self.assert_no_send()

    def test_stale_reader_from_long_persists_exact_last_known_exposure(self):
        self.entry()
        result, transitions = self.stale_read()
        self.assert_freshness_lost(result, D("0.05"), transitions)
        self.assertEqual(sum(name == "place_order" for name, _ in self.session.calls), 1)

    def test_locally_stale_prefix_from_flat_persists_freshness_loss(self):
        self.bootstrap()
        result, transitions = self.stale_prefix()
        self.assert_freshness_lost(result, D("0"), transitions)
        self.assertIsNone(self.store.get_decision(50 * HOUR))
        self.assert_no_send()

    def test_locally_stale_prefix_from_long_persists_freshness_loss(self):
        self.entry()
        result, transitions = self.stale_prefix()
        self.assert_freshness_lost(result, D("0.05"), transitions)
        self.assertIsNone(self.store.get_decision(51 * HOUR))
        self.assertEqual(sum(name == "place_order" for name, _ in self.session.calls), 1)

    def test_next_invocation_reconciles_before_planning_after_freshness_loss(self):
        self.bootstrap()
        self.stale_read()
        self.market.error = None
        self.advance("100")
        self.trace.clear()
        planner = module.plan_action

        def plan(*args, **kwargs):
            self.trace.append("plan")
            self.assertIs(args[1].snapshot.state, RuntimeState.FLAT)
            self.assertIs(args[1].snapshot.position_evidence, PositionEvidence.CONFIRMED)
            return planner(*args, **kwargs)

        with patch.object(module, "reconcile_startup", wraps=reconcile_startup) as reconcile, \
             patch.object(module, "plan_action", side_effect=plan):
            result = self.run_cycle()
        reconcile.assert_called_once()
        self.assertLess(self.trace.index("broker:account"), self.trace.index("market"))
        self.assertLess(self.trace.index("market"), self.trace.index("plan"))
        self.assertIs(result.outcome, CycleOutcome.NOOP)
        self.assert_no_send()

    def test_stale_market_does_not_apply_invalid_event_to_pending_state(self):
        self.entry(status=OrderStatus.OPEN)
        pending = self.store.get_checkpoint().snapshot.pending_action
        result, transitions = self.stale_read()
        self.assertIs(result.checkpoint.snapshot.state, RuntimeState.ORDER_PENDING)
        self.assertEqual(result.checkpoint.snapshot.pending_action, pending)
        self.assertFalse(any(call.args[1].kind == RuntimeEventType.FRESHNESS_LOST
                             for call in transitions.call_args_list))
        self.assertEqual(sum(name == "place_order" for name, _ in self.session.calls), 1)

    def test_transient_market_timeout_synchronizes_without_halt(self):
        self.bootstrap()
        self.market.error = MarketDataTransportError("Synthetic timeout", kind=MarketDataReadFailureKind.TRANSIENT)
        with patch.object(module, "transition_runtime_state", wraps=transition_runtime_state) as transitions:
            result = self.run_cycle()
        self.assert_freshness_lost(result, D("0"), transitions)
        self.assertIs(result.outcome, CycleOutcome.WAIT)
        self.assert_no_send()

    def test_empty_market_cannot_leave_operational_freshness_claim(self):
        self.prices, self.now_ms = [], 1000
        with patch.object(module, "transition_runtime_state", wraps=transition_runtime_state) as transitions:
            result = self.run_cycle()
        self.assert_freshness_lost(result, D("0"), transitions)
        self.assertIs(result.outcome, CycleOutcome.NO_NEW_DATA)
        self.assert_no_send()


class PlacementTests(CycleCase):
    def test_exact_persistence_and_observation_order_with_no_external_transaction(self):
        self.bootstrap()
        self.advance("110")
        commit, start, observe = self.store.commit_decision, self.store.start_attempt, self.store.record_observation

        def prepared(*args, **kwargs):
            result = commit(*args, **kwargs)
            self.trace.append("PREPARED committed")
            return result

        def attempt(*args, **kwargs):
            result = start(*args, **kwargs)
            self.trace.append("ATTEMPT_STARTED committed")
            return result

        def observation(action, *args, **kwargs):
            result = observe(action, *args, **kwargs)
            self.trace.append(action.phase.value + " committed")
            if action.phase == ActionPhase.ACKNOWLEDGED and self.trace.count("ACKNOWLEDGED committed") == 1:
                self.assertIs(self.store.get_checkpoint().snapshot.state, RuntimeState.ORDER_PENDING)
                self.assertEqual(self.store.get_checkpoint().snapshot.owned_base_quantity, D("0"))
            return result

        with patch.object(self.store, "commit_decision", side_effect=prepared), \
             patch.object(self.store, "start_attempt", side_effect=attempt), \
             patch.object(self.store, "record_observation", side_effect=observation), \
             patch.object(module, "reconcile_startup", wraps=reconcile_startup) as rounds:
            self.run_cycle()
        self.assertEqual(rounds.call_count, 2)
        ordered = [self.trace.index(label) for label in ("market", "PREPARED committed", "metadata", "ATTEMPT_STARTED committed", "send", "ACKNOWLEDGED committed")]
        self.assertEqual(ordered, sorted(ordered))
        post_reads = [i for i, label in enumerate(self.trace) if label == "broker:account"]
        self.assertLess(post_reads[0], self.trace.index("market"))
        self.assertGreater(post_reads[1], self.trace.index("ACKNOWLEDGED committed"))

    def test_constraint_preflight_failure_has_no_attempt_or_send(self):
        self.bootstrap()
        self.session.instrument["result"]["list"][0]["lotSizeFilter"]["minOrderAmt"] = "100"
        self.advance("110")
        with patch.object(self.store, "start_attempt", wraps=self.store.start_attempt) as attempt:
            result = self.run_cycle()
        attempt.assert_not_called()
        self.assertIs(self.action(result).phase, ActionPhase.ABANDONED_UNSENT)
        self.assert_no_send()

    def test_unsent_sell_preserves_long_inventory_and_clears_pending(self):
        self.entry()
        self.session.errors["get_instruments_info"] = TimeoutError(PRIVATE)
        self.advance("80")
        result = self.run_cycle()
        self.assertIs(result.outcome, CycleOutcome.ABANDONED_UNSENT)
        self.assertIs(result.checkpoint.snapshot.state, RuntimeState.LONG)
        self.assertEqual(result.checkpoint.snapshot.owned_base_quantity, D("0.05"))
        self.assertIsNone(result.checkpoint.snapshot.pending_action)
        self.assertEqual(sum(name == "place_order" for name, _ in self.session.calls), 1)

    def test_normalized_receipt_mismatch_is_discarded_before_verified_recovery(self):
        self.bootstrap()
        self.order_adapter.receipt_change = lambda receipt: replace(receipt, order_link_id="wrong-link", submitted_amount=D("999"))
        self.advance("110")
        with patch.object(self.store, "record_observation", wraps=self.store.record_observation) as writes:
            result = self.run_cycle()
        first = writes.call_args_list[0].args[0]
        self.assertIs(first.phase, ActionPhase.UNKNOWN_OUTCOME)
        self.assertIsNone(first.broker_order_id)
        self.assertIsNone(first.submitted_amount)
        self.assertIsNone(self.action(result).acknowledgement_broker_ms)
        self.assertIsNone(result.broker_order_id)
        self.assertIs(result.checkpoint.snapshot.state, RuntimeState.LONG)  # actual owned fills, not bad receipt
        self.assertEqual(len(self.order_adapter.calls), 1)

    def test_post_send_unknown_status_remains_uncertain(self):
        result = self.entry(status=OrderStatus.UNKNOWN)
        self.assertIs(result.checkpoint.snapshot.state, RuntimeState.UNCERTAIN)
        self.assertEqual(result.checkpoint.snapshot.owned_base_quantity, D("0"))
        self.assertEqual(len(self.order_adapter.calls), 1)

    def test_unknown_fill_currency_blocks_settlement(self):
        self.broker.fee, self.broker.fee_currency = D("0.00005"), None
        result = self.entry()
        self.assertIs(result.checkpoint.snapshot.state, RuntimeState.UNCERTAIN)
        self.assertEqual(result.checkpoint.snapshot.owned_base_quantity, D("0"))
        self.assertEqual(len(self.order_adapter.calls), 1)

    def test_actual_sell_base_fee_oversell_halts_without_another_send(self):
        self.entry()
        self.broker.fee = D("0.01")
        self.advance("80")
        result = self.run_cycle()
        self.assertIs(result.checkpoint.snapshot.state, RuntimeState.HALTED)
        self.assertEqual(len(self.order_adapter.calls), 2)
        self.assertEqual(result.checkpoint.snapshot.owned_base_quantity, D("0.05"))  # retained last-known evidence

    def test_initial_pending_terminal_recovery_can_allow_one_new_planned_exit(self):
        self.entry(status=OrderStatus.OPEN)
        self.advance("80")
        self.broker.status = OrderStatus.FILLED
        params = [params for name, params in self.session.calls if name == "place_order"][0]
        self.broker.publish(params, "order-1")
        result = self.run_cycle()
        self.assertIs(result.planner_kind, PlanKind.PLACE_SELL)
        self.assertIs(result.checkpoint.snapshot.state, RuntimeState.FLAT)
        self.assertEqual(result.new_execution_ids, ("exec-order-1", "exec-order-2"))
        self.assertEqual(len(self.order_adapter.calls), 2)

    def test_live_entry_fills_through_one_send_and_one_post_round(self):
        result = self.entry()
        self.assertIs(result.outcome, CycleOutcome.OBSERVED)
        self.assertIs(result.planner_kind, PlanKind.PLACE_BUY)
        self.assertIs(result.checkpoint.snapshot.state, RuntimeState.LONG)
        self.assertEqual(result.checkpoint.snapshot.owned_base_quantity, D("0.05"))
        self.assertEqual(result.new_execution_ids, ("exec-order-1",))
        self.assertEqual(result.broker_order_id, "order-1")
        action = self.action(result)
        self.assertIs(action.phase, ActionPhase.TERMINAL_CONFIRMED)
        self.assertEqual(action.authorized_amount, self.config.buy_quote_budget)
        self.assertEqual(action.submitted_amount, D("10.1234567"))
        self.assertEqual(len(self.order_adapter.calls), 1)
        self.assertEqual(self.order_adapter.calls[0].authorized_amount, self.config.buy_quote_budget)
        self.assertEqual(self.broker.calls.count("account"), 3)  # bootstrap + initial + one post-send

    def test_live_exit_uses_owned_base_and_actual_fill_confirms_flat(self):
        self.entry()
        self.advance("80")
        result = self.run_cycle()
        self.assertIs(result.planner_kind, PlanKind.PLACE_SELL)
        self.assertIs(result.checkpoint.snapshot.state, RuntimeState.FLAT)
        self.assertEqual(result.checkpoint.snapshot.owned_base_quantity, D("0"))
        self.assertEqual(self.order_adapter.calls[-1].authorized_amount, D("0.05"))
        self.assertEqual(self.order_adapter.calls[-1].amount_unit, "BASE")
        self.assertEqual(len(self.order_adapter.calls), 2)  # one per explicit invocation

    def test_filled_sell_round_down_retains_exact_positive_long_remainder(self):
        self.broker.buy_quantity = D("0.0500009")
        self.entry()
        self.advance("80")
        result = self.run_cycle()
        self.assertIs(result.checkpoint.snapshot.state, RuntimeState.LONG)
        self.assertEqual(result.checkpoint.snapshot.owned_base_quantity, D("0.0000009"))
        self.assertEqual(self.action(result).submitted_amount, D("0.05"))

    def test_buy_ack_with_open_order_is_pending_not_long(self):
        result = self.entry(status=OrderStatus.OPEN)
        self.assertIs(result.checkpoint.snapshot.state, RuntimeState.ORDER_PENDING)
        self.assertEqual(result.checkpoint.snapshot.owned_base_quantity, D("0"))
        self.assertIs(self.action(result).phase, ActionPhase.ACKNOWLEDGED)
        self.assertEqual(result.new_execution_ids, ())
        self.assertEqual(len(self.order_adapter.calls), 1)

    def test_sell_ack_with_open_order_is_pending_not_flat(self):
        self.entry()
        self.broker.status = OrderStatus.OPEN
        self.advance("80")
        result = self.run_cycle()
        self.assertIs(result.checkpoint.snapshot.state, RuntimeState.ORDER_PENDING)
        self.assertEqual(result.checkpoint.snapshot.owned_base_quantity, D("0.05"))
        self.assertIs(self.action(result).phase, ActionPhase.ACKNOWLEDGED)

    def test_partial_buy_fill_updates_exact_quantity_without_second_order(self):
        self.broker.fee = D("0.00002")
        result = self.entry(status=OrderStatus.PARTIALLY_FILLED)
        self.assertIs(result.checkpoint.snapshot.state, RuntimeState.ORDER_PENDING)
        self.assertEqual(result.checkpoint.snapshot.owned_base_quantity, D("0.01998"))
        self.assertEqual(len(self.order_adapter.calls), 1)
        self.assertEqual(len(self.store.list_fills()), 1)

    def test_pending_new_exit_intent_is_wait_without_replacement_or_cancel(self):
        previous = self.entry(status=OrderStatus.OPEN)
        self.advance("80")
        result = self.run_cycle()
        self.assertIs(result.planner_kind, PlanKind.WAIT)
        self.assertEqual(result.checkpoint.snapshot.desired_position, 0)
        self.assertEqual(result.logical_action_id, previous.logical_action_id)
        self.assertIs(self.store.get_decision(51 * HOUR).disposition, DecisionDisposition.WAIT)
        self.assertEqual(len(self.order_adapter.calls), 1)
        self.assertFalse(any(name == "cancel_order" for name, _ in self.session.calls))

    def test_preflight_failure_abandons_unsent_and_clears_pending(self):
        self.bootstrap()
        self.session.errors["get_instruments_info"] = TimeoutError(PRIVATE)
        self.advance("110")
        result = self.run_cycle()
        self.assertIs(result.outcome, CycleOutcome.ABANDONED_UNSENT)
        self.assertIs(result.checkpoint.snapshot.state, RuntimeState.FLAT)
        self.assertIsNone(result.checkpoint.snapshot.pending_action)
        self.assertEqual(result.checkpoint.snapshot.owned_base_quantity, D("0"))
        action = self.action(result)
        self.assertIs(action.phase, ActionPhase.ABANDONED_UNSENT)
        self.assertEqual(action.attempt_count, 0)
        self.assertIsNone(action.broker_order_id)
        self.assert_no_send()
        self.run_cycle()
        self.assertEqual(len(self.order_adapter.calls), 1)
        self.assertEqual(self.store.list_actions(), (action,))

    def test_confirmed_rejection_records_code_clears_pending_and_halts(self):
        self.bootstrap()
        self.session.raw_ack = {"retCode": 10001, "retMsg": PRIVATE}
        self.advance("110")
        result = self.run_cycle()
        action = self.action(result)
        self.assertIs(result.outcome, CycleOutcome.HALTED)
        self.assertIs(result.checkpoint.snapshot.state, RuntimeState.HALTED)
        self.assertIsNone(result.checkpoint.snapshot.pending_action)
        self.assertIs(action.phase, ActionPhase.REJECTED)
        self.assertEqual(action.rejection_code, 10001)
        self.assertEqual(action.attempt_count, 1)
        self.assertIsNone(action.broker_order_id)
        self.assertEqual(result.checkpoint.snapshot.reason, RuntimeReason.INCONSISTENT_EVIDENCE)
        self.assertEqual(len(self.order_adapter.calls), 1)
        self.assertEqual(self.broker.calls.count("account"), 2)  # no post-send round after rejection

    def test_ambiguous_send_remains_unknown_and_uncertain_without_resend(self):
        self.bootstrap()
        self.session.errors["place_order"] = TimeoutError(PRIVATE)
        self.advance("110")
        result = self.run_cycle()
        action = self.action(result)
        self.assertIs(action.phase, ActionPhase.UNKNOWN_OUTCOME)
        self.assertIs(result.checkpoint.snapshot.state, RuntimeState.UNCERTAIN)
        self.assertIsNone(action.submitted_amount)
        self.assertIsNone(action.broker_order_id)
        self.assertEqual(len(self.order_adapter.calls), 1)
        self.assertNotIn(PRIVATE, repr(result))

    def test_malformed_raw_acknowledgement_is_unknown_without_retry(self):
        self.bootstrap()
        self.session.raw_ack = {"retCode": 0, "result": {}}
        self.advance("110")
        result = self.run_cycle()
        self.assertIs(self.action(result).phase, ActionPhase.UNKNOWN_OUTCOME)
        self.assertIs(result.checkpoint.snapshot.state, RuntimeState.UNCERTAIN)
        self.assertEqual(len(self.order_adapter.calls), 1)

    def test_unknown_outcome_can_recover_exact_order_without_invented_receipt(self):
        self.bootstrap()
        self.session.publish_on_error = True
        self.session.errors["place_order"] = TimeoutError(PRIVATE)
        self.broker.status = OrderStatus.OPEN
        self.advance("110")
        result = self.run_cycle()
        action = self.action(result)
        self.assertIs(result.checkpoint.snapshot.state, RuntimeState.ORDER_PENDING)
        self.assertIs(action.phase, ActionPhase.UNKNOWN_OUTCOME)
        self.assertEqual(action.broker_order_id, "order-1")
        self.assertIsNone(action.acknowledgement_broker_ms)
        self.assertIsNone(action.submitted_amount)
        self.assertIsNone(result.broker_order_id)  # Only durable receipt IDs are exposed here.
        self.assertEqual(len(self.order_adapter.calls), 1)

    def test_post_callback_demo_refusal_never_abandons_attempt(self):
        self.bootstrap()
        self.order_adapter.change_guard = True
        self.advance("110")
        result = self.run_cycle()
        self.assertIs(self.action(result).phase, ActionPhase.UNKNOWN_OUTCOME)
        self.assertEqual(self.action(result).attempt_count, 1)
        self.assertIs(result.checkpoint.snapshot.state, RuntimeState.HALTED)
        self.assertIs(result.checkpoint.snapshot.reason, RuntimeReason.INVALID_CONFIGURATION)
        self.assert_no_send()
        self.assertEqual(len(self.order_adapter.calls), 1)


class PersistenceTests(CycleCase):
    def test_initial_reconciliation_persistence_failure_prevents_adapter_invocation(self):
        self.bootstrap()
        self.advance("110")
        with patch.object(self.store, "_commit", side_effect=sqlite3.OperationalError("Synthetic fault")):
            # Initial reconciliation also writes; target the decision transaction
            # explicitly in the next test, while any failure must block dispatch.
            with self.assertRaises(RuntimeStoreError):
                self.run_cycle()
        self.assertEqual(self.order_adapter.calls, [])
        self.assert_no_send()

    def test_decision_transaction_fault_rolls_back_prepared_and_frontier(self):
        self.bootstrap()
        self.advance("110")
        original = self.store.commit_decision

        def fail(*args, **kwargs):
            with patch.object(self.store, "_commit", side_effect=sqlite3.OperationalError("Synthetic decision fault")):
                return original(*args, **kwargs)

        with patch.object(self.store, "commit_decision", side_effect=fail), self.assertRaises(RuntimeStoreError):
            self.run_cycle()
        self.reopen()
        self.assertIsNone(self.store.get_decision(50 * HOUR))
        self.assertEqual(self.store.list_actions(), ())
        self.assertEqual(self.store.get_checkpoint().last_processed_candle_ms, 49 * HOUR)
        self.assertEqual(self.order_adapter.calls, [])

    def assert_attempt_fault(self, *, indeterminate):
        self.bootstrap()
        self.advance("110")
        original_attempt, original_commit = self.store.start_attempt, self.store._commit

        def commit_fault():
            if indeterminate:
                original_commit()
            raise sqlite3.OperationalError("Synthetic attempt fault")

        def fail(*args, **kwargs):
            with patch.object(self.store, "_commit", side_effect=commit_fault):
                return original_attempt(*args, **kwargs)

        with patch.object(self.store, "start_attempt", side_effect=fail) as start, \
             patch.object(self.store, "abandon_prepared", side_effect=AssertionError("No abandonment after callback entry")) as abandon, \
             patch.object(self.store, "record_observation", side_effect=AssertionError("No follow-up observation write")) as observe, \
             self.assertRaises(RuntimeStoreError):
            self.run_cycle()
        start.assert_called_once()
        abandon.assert_not_called()
        observe.assert_not_called()
        self.assert_no_send()
        self.reopen()
        action = self.store.list_actions()[0]
        self.assertIs(action.phase, ActionPhase.ATTEMPT_STARTED if indeterminate else ActionPhase.PREPARED)
        self.assertIsNone(action.broker_order_id)
        self.assertEqual(len(self.order_adapter.calls), 1)

    def test_attempt_commit_failure_has_no_follow_up_write_or_send(self):
        self.assert_attempt_fault(indeterminate=False)

    def test_indeterminate_attempt_commit_has_no_follow_up_write_or_send(self):
        self.assert_attempt_fault(indeterminate=True)

    def test_ack_persistence_fault_retains_attempt_then_original_link_recovers(self):
        self.bootstrap()
        self.advance("110")
        original_observe = self.store.record_observation

        def fail(*args, **kwargs):
            with patch.object(self.store, "_commit", side_effect=sqlite3.OperationalError("Synthetic receipt fault")):
                return original_observe(*args, **kwargs)

        with patch.object(self.store, "record_observation", side_effect=fail), self.assertRaises(RuntimeStoreError):
            self.run_cycle()
        self.reopen()
        action = self.store.list_actions()[0]
        self.assertIs(action.phase, ActionPhase.ATTEMPT_STARTED)
        self.assertIsNone(action.broker_order_id)
        self.assertEqual(len(self.order_adapter.calls), 1)
        result = self.run_cycle()
        self.assertIs(result.checkpoint.snapshot.state, RuntimeState.LONG)
        self.assertEqual(len(self.order_adapter.calls), 1)
        self.assertIsNone(self.store.get_action(action.logical_action_id).acknowledgement_broker_ms)

    def test_exact_commit_replay_never_sends_in_memory_authorization(self):
        self.bootstrap()
        self.advance("110")
        original = self.store.commit_decision

        def replay(*args, **kwargs):
            original(*args, **kwargs)
            return original(*args, **kwargs)  # Real public exact replay, False.

        with patch.object(self.store, "commit_decision", side_effect=replay):
            result = self.run_cycle()
        self.assertIs(result.outcome, CycleOutcome.WAIT)
        self.assertEqual(result.processed_candle_count, 0)
        self.assertIs(self.store.list_actions()[0].phase, ActionPhase.PREPARED)
        self.assertEqual(self.order_adapter.calls, [])
        self.assert_no_send()

    def test_unknown_outcome_write_failure_stops_before_post_round(self):
        self.bootstrap()
        self.session.errors["place_order"] = TimeoutError(PRIVATE)
        self.advance("110")
        observe = self.store.record_observation

        def fail(*args, **kwargs):
            with patch.object(self.store, "_commit", side_effect=sqlite3.OperationalError("Synthetic outcome fault")):
                return observe(*args, **kwargs)

        with patch.object(self.store, "record_observation", side_effect=fail), self.assertRaises(RuntimeStoreError):
            self.run_cycle()
        self.reopen()
        self.assertIs(self.store.list_actions()[0].phase, ActionPhase.ATTEMPT_STARTED)
        self.assertEqual(len(self.order_adapter.calls), 1)
        self.assertEqual(self.broker.calls.count("account"), 2)

    def test_indeterminate_ack_commit_stops_without_repair_or_post_round(self):
        self.bootstrap()
        self.broker.status = OrderStatus.OPEN
        self.advance("110")
        observe, commit = self.store.record_observation, self.store._commit

        def commit_then_fail():
            commit()
            raise sqlite3.OperationalError("Synthetic post-receipt commit fault")

        def fail(*args, **kwargs):
            with patch.object(self.store, "_commit", side_effect=commit_then_fail):
                return observe(*args, **kwargs)

        with patch.object(self.store, "record_observation", side_effect=fail), self.assertRaises(RuntimeStoreError):
            self.run_cycle()
        self.reopen()
        self.assertIs(self.store.list_actions()[0].phase, ActionPhase.ACKNOWLEDGED)
        self.assertEqual(len(self.order_adapter.calls), 1)
        self.assertEqual(self.broker.calls.count("account"), 2)
        result = self.run_cycle()
        self.assertIs(result.checkpoint.snapshot.state, RuntimeState.ORDER_PENDING)
        self.assertEqual(len(self.order_adapter.calls), 1)

    def test_retained_prepared_action_is_abandoned_by_initial_reconciliation_without_send(self):
        self.bootstrap()
        self.advance("110")
        original = self.store.commit_decision

        def stop_after_commit(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeStoreError("Synthetic stop after prepared commit")

        with patch.object(self.store, "commit_decision", side_effect=stop_after_commit), self.assertRaises(RuntimeStoreError):
            self.run_cycle()
        self.reopen()
        result = self.run_cycle()
        self.assertIs(result.outcome, CycleOutcome.NO_NEW_DATA)
        self.assertIs(self.store.list_actions()[0].phase, ActionPhase.ABANDONED_UNSENT)
        self.assertEqual(self.order_adapter.calls, [])


class MarketAndSafetyTests(CycleCase):
    def test_caller_resources_and_unrelated_checkpoint_coverage_are_preserved(self):
        cp = self.store.get_checkpoint()
        covered = replace(cp, sequence=cp.sequence + 1, coverage_start_ms=0, coverage_end_ms=50 * HOUR)
        self.store.save_checkpoint(covered, expected_sequence=cp.sequence)
        with patch.object(self.store, "close", wraps=self.store.close) as close:
            result = self.bootstrap()
        close.assert_not_called()
        self.assertEqual((result.checkpoint.coverage_start_ms, result.checkpoint.coverage_end_ms), (0, 50 * HOUR))
        self.assertEqual(self.store.get_checkpoint(), result.checkpoint)

    def test_post_send_broker_read_failure_keeps_ack_pending_evidence_uncertain(self):
        self.bootstrap()
        self.advance("110")
        place = self.session.place_order

        def fail_reads(**params):
            response = place(**params)
            self.broker.errors["account"] = BrokerReadError(BrokerReadFailureKind.TRANSIENT)
            return response

        with patch.object(self.session, "place_order", side_effect=fail_reads):
            result = self.run_cycle()
        self.assertIs(result.checkpoint.snapshot.state, RuntimeState.UNCERTAIN)
        self.assertEqual(result.checkpoint.snapshot.owned_base_quantity, D("0"))
        self.assertIs(self.action_from_result(result).phase, ActionPhase.ACKNOWLEDGED)
        self.assertEqual(result.broker_order_id, "order-1")
        self.assertEqual(len(self.order_adapter.calls), 1)

    def action_from_result(self, result):
        return self.store.get_action(result.logical_action_id)

    def test_strategy_float_overflow_fails_without_changing_durable_history(self):
        self.prices = ["1e400"] * 50
        result = self.run_cycle()
        self.assertIs(result.outcome, CycleOutcome.HALTED)
        self.assertIsNone(self.store.get_candle(0))
        self.assert_no_send()

    def test_strategy_float_underflow_fails_without_zero_equity_or_order(self):
        self.prices = ["1e-400"] * 50
        result = self.run_cycle()
        self.assertIs(result.outcome, CycleOutcome.HALTED)
        self.assertIsNone(self.store.get_decision(0))
        self.assert_no_send()

    def test_bypassed_forming_prefix_is_refused_without_processing(self):
        prefix = self.prefix()
        object.__setattr__(prefix, "candles", prefix.candles[:-1] + (replace(prefix.candles[-1], candle_open_ms=50 * HOUR),))
        self.market.override = prefix
        self.assertIs(self.run_cycle().outcome, CycleOutcome.HALTED)
        self.assertIsNone(self.store.get_decision(0))

    def test_wrong_prefix_context_is_refused(self):
        prefix = self.prefix()
        self.market.override = replace(prefix, symbol="ETHUSDT", candles=tuple(replace(candle, symbol="ETHUSDT") for candle in prefix.candles))
        self.assertIs(self.run_cycle().outcome, CycleOutcome.HALTED)
        self.assert_no_send()

    def test_truncated_anchor_history_is_refused_without_frontier_regression(self):
        self.bootstrap()
        self.market.override = replace(self.prefix(), end_ms=49 * HOUR, candles=self.prefix().candles[:49])
        result = self.run_cycle()
        self.assertIs(result.outcome, CycleOutcome.HALTED)
        self.assertEqual(result.checkpoint.last_processed_candle_ms, 49 * HOUR)
        self.assert_no_send()

    def test_regressing_control_clock_after_market_read_fails_closed(self):
        self.bootstrap()
        self.advance("110")
        original = self.market.get_closed_candles

        def regress(**kwargs):
            result = original(**kwargs)
            self.now_ms -= 1
            return result

        with patch.object(self.market, "get_closed_candles", side_effect=regress), self.assertRaises(CycleError):
            self.run_cycle()
        self.assertEqual(self.order_adapter.calls, [])
        self.assertIsNone(self.store.get_decision(50 * HOUR))

    def test_reader_uses_exact_configured_context_and_decision_age_limit(self):
        self.bootstrap()
        self.assertEqual(self.market.calls, [{"symbol": "BTCUSDT", "timeframe": "60",
                                             "history_anchor_ms": 0, "max_data_age_ms": self.config.decision_max_age_ms}])

    def test_clock_skew_at_bound_is_accepted(self):
        self.bootstrap()
        self.advance("110")
        self.market.override = replace(self.prefix(), server_time_ms=self.now_ms + self.config.max_clock_skew_ms,
                                       observed_at_ms=self.now_ms + self.config.max_clock_skew_ms)
        self.assertIs(self.run_cycle().checkpoint.snapshot.state, RuntimeState.LONG)

    def test_clock_skew_beyond_bound_halts_without_order(self):
        self.bootstrap()
        self.advance("110")
        self.market.override = replace(self.prefix(), server_time_ms=self.now_ms + self.config.max_clock_skew_ms + 1,
                                       observed_at_ms=self.now_ms + self.config.max_clock_skew_ms + 1)
        result = self.run_cycle()
        self.assertIs(result.checkpoint.snapshot.state, RuntimeState.HALTED)
        self.assertIs(result.reason, RuntimeReason.INVALID_CONFIGURATION)
        self.assertEqual(self.order_adapter.calls, [])

    def test_pagination_latency_is_not_mistaken_for_skew(self):
        self.bootstrap()
        self.advance("110")
        start_ms, prefix = self.now_ms, self.prefix()

        def delayed(**kwargs):
            self.assertFalse(self.store._connection.in_transaction)
            self.now_ms += 2000
            return replace(prefix, server_time_ms=start_ms + 100, observed_at_ms=start_ms + 1500)

        with patch.object(self.market, "get_closed_candles", side_effect=delayed):
            self.assertIs(self.run_cycle().checkpoint.snapshot.state, RuntimeState.LONG)

    def test_stale_prefix_is_not_processed_or_traded(self):
        self.bootstrap()
        self.advance("110")
        self.now_ms = 51 * HOUR + self.config.decision_max_age_ms + 1
        result = self.run_cycle()
        self.assertIs(result.outcome, CycleOutcome.WAIT)
        self.assertIsNone(self.store.get_decision(50 * HOUR))
        self.assertEqual(self.order_adapter.calls, [])

    def test_stale_reader_failure_is_safe_wait_without_strategy(self):
        self.market.error = StaleMarketDataError(PRIVATE)
        with patch.object(module, "generate_ema_signals") as generate:
            result = self.run_cycle()
        self.assertIs(result.outcome, CycleOutcome.WAIT)
        generate.assert_not_called()
        self.assertNotIn(PRIVATE, repr(result))

    def test_market_transport_failure_returns_wait_without_mutation(self):
        self.market.error = MarketDataTransportError(PRIVATE, kind=MarketDataReadFailureKind.TRANSIENT)
        result = self.run_cycle()
        self.assertIs(result.outcome, CycleOutcome.WAIT)
        self.assertEqual(result.processed_candle_count, 0)
        self.assertIsNone(result.checkpoint.last_processed_candle_ms)
        self.assert_no_send()

    def test_forming_candle_is_excluded_by_frozen_market_gate(self):
        accepted = candles(self.prices)
        forming = MarketCandle("BTCUSDT", "60", 50 * HOUR, D("110"), D("110"), D("110"), D("110"), D("1"))
        self.market.override = validate_closed_prefix(accepted + (forming,), symbol="BTCUSDT", history_anchor_ms=0,
                                                     server_time_ms=self.now_ms)
        result = self.bootstrap()
        self.assertEqual(result.processed_candle_count, 50)
        self.assertIsNone(self.store.get_candle(50 * HOUR))

    def test_no_closed_candles_produces_no_decision(self):
        self.prices, self.now_ms = [], 1000
        result = self.run_cycle()
        self.assertIs(result.outcome, CycleOutcome.NO_NEW_DATA)
        self.assertEqual(result.processed_candle_count, 0)
        self.assertIsNone(result.checkpoint.last_processed_candle_ms)
        self.assert_no_send()

    def test_raw_market_payload_is_refused(self):
        self.market.override = {"retCode": 0, "result": []}
        result = self.run_cycle()
        self.assertIs(result.outcome, CycleOutcome.HALTED)
        self.assert_no_send()

    def test_bypassed_mutable_or_forming_prefix_is_not_repaired(self):
        prefix = self.prefix()
        object.__setattr__(prefix, "candles", list(prefix.candles))
        self.market.override = prefix
        self.assertIs(self.run_cycle().outcome, CycleOutcome.HALTED)
        self.assertEqual(self.store.list_actions(), ())

    def test_reconciliation_uncertainty_blocks_market_strategy_and_planner(self):
        self.broker.errors["account"] = BrokerReadError(BrokerReadFailureKind.TRANSIENT)
        with patch.object(module, "plan_action") as planner, patch.object(module, "generate_ema_signals") as strategy:
            result = self.run_cycle()
        self.assertIs(result.checkpoint.snapshot.state, RuntimeState.UNCERTAIN)
        self.assertEqual(self.market.calls, [])
        self.assertEqual(self.order_adapter.calls, [])
        planner.assert_not_called()
        strategy.assert_not_called()

    def test_unrelated_managed_symbol_order_halts_before_market_read(self):
        self.broker.status = OrderStatus.OPEN
        self.broker.publish({"qty": "10", "side": "Buy", "orderLinkId": "foreign"}, "foreign-order")
        result = self.run_cycle()
        self.assertIs(result.checkpoint.snapshot.state, RuntimeState.HALTED)
        self.assertEqual(self.market.calls, [])
        self.assert_no_send()

    def test_halt_latch_is_preserved_without_broker_or_market_calls(self):
        cp = self.store.get_checkpoint()
        halted = transition_runtime_state(cp.snapshot, RuntimeEvent(RuntimeEventType.FATAL_INCONSISTENCY,
                                                                   reason=RuntimeReason.OWNERSHIP_CONFLICT))
        cp = replace(cp, sequence=cp.sequence + 1, snapshot=halted, halted_at_ms=self.now_ms)
        self.store.save_checkpoint(cp, expected_sequence=cp.sequence - 1)
        result = self.run_cycle()
        self.assertEqual(result.checkpoint, cp)
        self.assertIs(result.outcome, CycleOutcome.HALTED)
        self.assertEqual(self.broker.calls, [])
        self.assertEqual(self.market.calls, [])
        self.assert_no_send()

    def test_stopping_returns_without_new_decision_or_mutation(self):
        cp = self.store.get_checkpoint()
        stopped = transition_runtime_state(cp.snapshot, RuntimeEvent(RuntimeEventType.SHUTDOWN_REQUESTED))
        cp = replace(cp, sequence=cp.sequence + 1, snapshot=stopped, shutdown_at_ms=self.now_ms)
        self.store.save_checkpoint(cp, expected_sequence=cp.sequence - 1)
        result = self.run_cycle()
        self.assertEqual(result.checkpoint, cp)
        self.assertIs(result.outcome, CycleOutcome.STOPPING)
        self.assertEqual(self.broker.calls, [])
        self.assertEqual(self.market.calls, [])

    def test_strategy_is_called_once_with_frozen_parameters_and_canonical_parity(self):
        prefix = self.prefix()
        direct = generate_ema_signals(pd.DataFrame({"timestamp": pd.to_datetime([c.candle_open_ms for c in prefix.candles], unit="ms", utc=True),
                                                   "close": [float(c.close) for c in prefix.candles]}))
        with patch.object(module, "generate_ema_signals", wraps=generate_ema_signals) as generate:
            self.bootstrap()
        generate.assert_called_once()
        self.assertEqual(generate.call_args.kwargs, {"fast_span": 20, "slow_span": 50, "warmup_candles": 50})
        for i in range(50):
            stored = self.store.get_decision(i * HOUR)
            self.assertEqual((stored.signal, stored.desired_position), (direct.iloc[i].signal, direct.iloc[i].desired_position))
            self.assertEqual(stored.available_at_ms, (i + 1) * HOUR)
            self.assertEqual(self.store.get_candle(i * HOUR).close, prefix.candles[i].close)

    def test_invalid_strategy_output_halts_before_any_decision_commit(self):
        generate = generate_ema_signals

        def invalid(frame, **kwargs):
            output = generate(frame, **kwargs)
            output["signal_time"] += pd.Timedelta(seconds=1)
            return output

        with patch.object(module, "generate_ema_signals", side_effect=invalid):
            result = self.run_cycle()
        self.assertIs(result.outcome, CycleOutcome.HALTED)
        self.assertIsNone(result.checkpoint.last_processed_candle_ms)
        self.assert_no_send()

    def test_result_is_frozen_slotted_and_contains_only_safe_normalized_facts(self):
        result = self.bootstrap()
        self.assertIsInstance(result, SingleCycleResult)
        self.assertFalse(hasattr(result, "__dict__"))
        with self.assertRaises(FrozenInstanceError):
            result.outcome = CycleOutcome.WAIT
        self.assertEqual({field.name for field in fields(result)}, {
            "checkpoint", "outcome", "processed_candle_open_ms", "planner_kind", "logical_action_id",
            "broker_order_id", "new_execution_ids", "reason"})

    def test_structural_scope_has_no_private_store_sdk_execution_or_scheduler(self):
        source = inspect.getsource(module)
        tree = ast.parse(source)
        for node in ast.walk(tree):
            self.assertNotIsInstance(node, (ast.While, ast.AsyncFunctionDef, ast.Await))
            if isinstance(node, ast.Attribute):
                self.assertNotIn(node.attr, {"_connection", "_session", "_mutate", "execute", "connect", "place_order",
                                             "cancel_order", "sleep", "now", "get_wallet_balance", "environ"})
        names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        self.assertFalse(names & {"RuntimeAccountLock", "load_bybit_demo_credentials", "create_bybit_demo_session",
                                  "BybitPublicMarketReader", "BybitDemoReadOnlyAdapter", "calculate_position_budget",
                                  "apply_next_open_execution", "run_backtest_pipeline"})
        imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        self.assertFalse(imports & {"sqlite3", "os", "requests", "pybit"})
        backtest = {name for name in imports if name and name.startswith("backtest")}
        self.assertEqual(backtest, {"backtest.strategy_validation"})  # pure canonical intent validation only
        self.assertNotIn(".ewm(", source)


class MarketReadClassificationCycleTests(integration_fixtures.IntegrationCase):
    """Real public parser/cycle/reconciliation, with only external transport fake."""

    def malformed_time(self):
        return {"retCode": 0, "time": self.clock.ms,
                "result": {"timeSecond": str(self.clock.ms // 1000), "timeNano": integration_fixtures.PRIVATE}}

    def assert_fatal(self, result, *, prior=None, actions=(), fills=()):
        self.assertIs(result.outcome, CycleOutcome.HALTED)
        snapshot = result.checkpoint.snapshot
        self.assertIs(snapshot.state, RuntimeState.HALTED)
        self.assertIs(snapshot.reason, RuntimeReason.INCONSISTENT_EVIDENCE)
        self.assertIs(snapshot.position_evidence, PositionEvidence.LAST_KNOWN)
        self.assertEqual(snapshot.owned_base_quantity, D("0") if prior is None else prior.owned_base_quantity)
        self.assertEqual(snapshot.pending_action, None if prior is None else prior.pending_action)
        self.assertEqual(result.processed_candle_count, 0)
        self.assertEqual(self.store.list_fills(), fills)
        retained = self.store.list_actions()
        self.assertEqual(len(retained), len(actions))
        for old, new in zip(actions, retained):
            for name in ("logical_action_id", "order_link_id", "broker_order_id", "attempt_count", "reconciliation_deadline_ms"):
                self.assertEqual(getattr(new, name), getattr(old, name))
            self.assertLessEqual(new.remaining_read_attempts, old.remaining_read_attempts)
        self.assertEqual(len(self.sends), len(actions))
        self.assertEqual(self.cancels, [])
        self.assertNotIn(integration_fixtures.PRIVATE, repr(result))
        self.audit("fatal-market")

    def test_malformed_server_time_halts_after_one_public_request(self):
        with self.public_time_failure(self.malformed_time()):
            result = self.cycle()
        self.assert_fatal(result)
        self.assertEqual([name for name, *_ in self.trace if name.startswith("public_")], ["public_time"])

    def test_unknown_public_api_code_halts_without_mutation(self):
        with self.public_time_failure({"retCode": 987654, "retMsg": integration_fixtures.PRIVATE}):
            result = self.cycle()
        self.assert_fatal(result)
        self.assertEqual([name for name, *_ in self.trace if name.startswith("public_")], ["public_time"])

    def test_verified_timeout_returns_wait_instead_of_halt(self):
        with self.public_time_failure(TimeoutError(integration_fixtures.PRIVATE)):
            result = self.cycle()
        self.assertIs(result.outcome, CycleOutcome.WAIT)
        self.assertIs(result.reason, RuntimeReason.EVIDENCE_MISSING)
        self.assertIs(result.checkpoint.snapshot.state, RuntimeState.SYNCHRONIZING)
        self.assertEqual((self.sends, self.cancels), ([], []))

    def test_verified_connection_failure_returns_wait(self):
        with self.public_time_failure(requests.ConnectionError(integration_fixtures.PRIVATE)):
            result = self.cycle()
        self.assertIs(result.outcome, CycleOutcome.WAIT)
        self.assertIs(result.reason, RuntimeReason.EVIDENCE_MISSING)
        self.assertEqual((self.sends, self.cancels), ([], []))

    def test_unclassified_reader_exception_halts_without_message_guessing(self):
        with patch.object(self.market, "get_closed_candles", side_effect=TimeoutError(integration_fixtures.PRIVATE)):
            self.assert_fatal(self.cycle())

    def test_unclassified_legacy_transport_error_halts(self):
        with patch.object(self.market, "get_closed_candles", side_effect=MarketDataTransportError("temporary retry")):
            self.assert_fatal(self.cycle())

    def test_valid_stale_public_evidence_remains_wait(self):
        self.page_latency = self.config.decision_max_age_ms + 1
        result = self.cycle()
        self.assertIs(result.outcome, CycleOutcome.WAIT)
        self.assertIs(result.reason, RuntimeReason.EVIDENCE_MISSING)
        self.assertIs(result.checkpoint.snapshot.state, RuntimeState.SYNCHRONIZING)
        self.assertEqual((self.sends, self.cancels), ([], []))

    def test_malformed_read_from_flat_latches_halt_with_exact_zero(self):
        self.cycle()
        prior = self.store.get_checkpoint().snapshot
        self.assertIs(prior.state, RuntimeState.FLAT)
        with self.public_time_failure(self.malformed_time()):
            self.assert_fatal(self.cycle(), prior=prior)
        trace = deepcopy(self.trace)
        checkpoint_before = self.store.get_checkpoint()
        self.assertIs(self.cycle().outcome, CycleOutcome.HALTED)
        self.assertEqual(self.trace, trace)
        self.assertEqual(self.store.get_checkpoint(), checkpoint_before)

    def test_malformed_read_from_long_preserves_exact_owned_fills(self):
        self.enter()
        prior = self.store.get_checkpoint().snapshot
        self.assertIs(prior.state, RuntimeState.LONG)
        self.assertEqual(prior.owned_base_quantity, D("0.04995"))
        actions, fills = self.store.list_actions(), self.store.list_fills()
        with self.public_time_failure(self.malformed_time()):
            self.assert_fatal(self.cycle(), prior=prior, actions=actions, fills=fills)

    def test_permanent_read_from_long_does_not_sell_or_erase_exposure(self):
        self.enter()
        prior = self.store.get_checkpoint().snapshot
        actions, fills = self.store.list_actions(), self.store.list_fills()
        with self.public_time_failure({"retCode": 987654, "retMsg": integration_fixtures.PRIVATE}):
            self.assert_fatal(self.cycle(), prior=prior, actions=actions, fills=fills)

    def test_malformed_read_preserves_partial_fill_and_pending_identity(self):
        self.enter(status="PartiallyFilled")
        prior = self.store.get_checkpoint().snapshot
        self.assertIs(prior.state, RuntimeState.ORDER_PENDING)
        self.assertEqual(prior.owned_base_quantity, D("0.01995"))
        actions, fills = self.store.list_actions(), self.store.list_fills()
        with self.public_time_failure(self.malformed_time()):
            self.assert_fatal(self.cycle(), prior=prior, actions=actions, fills=fills)

    def test_permanent_read_preserves_open_pending_order_without_resend(self):
        self.enter(status="New")
        prior = self.store.get_checkpoint().snapshot
        self.assertIs(prior.state, RuntimeState.ORDER_PENDING)
        actions, fills = self.store.list_actions(), self.store.list_fills()
        with self.public_time_failure({"retCode": 987654}):
            self.assert_fatal(self.cycle(), prior=prior, actions=actions, fills=fills)

    def freshness_failure(self, error):
        # Only the cycle's second validation boundary is fault-injected; the
        # real public reader has already delivered a complete valid prefix.
        with patch.object(module, "validate_candle_freshness", side_effect=error) as freshness:
            result = self.cycle()
        freshness.assert_called_once()
        return result

    def test_post_read_freshness_input_error_is_fatal(self):
        self.assert_fatal(self.freshness_failure(MarketDataInputError("Synthetic invalid input")))

    def test_post_read_freshness_integrity_error_is_fatal(self):
        self.assert_fatal(self.freshness_failure(MarketDataIntegrityError("Synthetic invalid facts")))

    def test_post_read_freshness_response_error_is_fatal(self):
        self.assert_fatal(self.freshness_failure(MarketDataResponseError("Synthetic malformed facts")))

    def test_post_read_freshness_unclassified_error_is_fatal(self):
        self.assert_fatal(self.freshness_failure(RuntimeError(integration_fixtures.PRIVATE)))

    def test_post_read_freshness_stale_error_remains_wait(self):
        result = self.freshness_failure(StaleMarketDataError("Synthetic stale facts"))
        self.assertIs(result.outcome, CycleOutcome.WAIT)
        self.assertIs(result.reason, RuntimeReason.EVIDENCE_MISSING)
        self.assertEqual((self.sends, self.cancels), ([], []))


class FingerprintTests(unittest.TestCase):
    def golden_candle(self):
        return MarketCandle("BTCUSDT", "60", 0, D("100"), D("110"), D("90"), D("105.25"), D("1.23456789"))

    def test_golden_exact_json_bytes_and_sha256(self):
        candle = self.golden_candle()
        expected = b'{"candle_open_ms":0,"close":"105.25","high":"110","low":"90","open":"100","symbol":"BTCUSDT","timeframe":"60","volume":"1.23456789"}'
        self.assertEqual(module._candle_bytes(candle), expected)
        self.assertEqual(module._candle_record(candle).input_fingerprint,
                         "c51b1a702fd5f7270194b8f349d0e955895853a59bc17ae0190f7f2aebde67bd")

    def test_scale_equivalence_and_small_decimal_context_preserve_exact_identity(self):
        candle = self.golden_candle()
        equivalent = replace(candle, close=D("105.25000"), open=D("1E+2"))
        with localcontext() as context:
            context.prec = 2
            self.assertEqual(module._candle_record(candle), module._candle_record(equivalent))

    def test_observation_times_do_not_enter_identity(self):
        candle = self.golden_candle()
        first = ClosedCandlePrefix("BTCUSDT", "60", 0, HOUR, HOUR, HOUR, (candle,))
        second = replace(first, server_time_ms=HOUR + 500, observed_at_ms=HOUR + 1000)
        self.assertEqual(module._candle_record(first.candles[0]), module._candle_record(second.candles[0]))

    def test_each_semantic_ohlcv_or_identity_change_changes_fingerprint(self):
        candle = self.golden_candle()
        original = module._candle_record(candle).input_fingerprint
        for field, value in (("open", D("101")), ("high", D("111")), ("low", D("89")),
                             ("close", D("104")), ("volume", D("2")), ("candle_open_ms", HOUR),
                             ("symbol", "ETHUSDT")):
            with self.subTest(field=field):
                self.assertNotEqual(module._candle_record(replace(candle, **{field: value})).input_fingerprint, original)

    def test_fingerprint_and_durable_values_use_no_float_conversion(self):
        candle = self.golden_candle()
        with patch("builtins.float", side_effect=AssertionError("No money conversion")):
            record = module._candle_record(candle)
        self.assertEqual(record.close, candle.close)
        self.assertIsInstance(record.close, Decimal)


class PureBoundaryValidationTests(unittest.TestCase):
    def test_public_signature_requires_existing_resources_and_explicit_utc_clock(self):
        parameters = inspect.signature(run_single_cycle).parameters
        self.assertEqual(list(parameters), ["store", "market_reader", "broker", "order_adapter", "utc_now", "monotonic"])
        self.assertIs(parameters["utc_now"].kind, inspect.Parameter.KEYWORD_ONLY)
        self.assertIs(parameters["utc_now"].default, inspect.Parameter.empty)
        with self.assertRaises(CycleError):
            run_single_cycle(object(), Mock(), Mock(), Mock(), utc_now=lambda: utc(HOUR))

    def test_integer_utc_floor_and_invalid_clock_types(self):
        self.assertEqual(module._milliseconds(utc(HOUR) + timedelta(microseconds=999)), HOUR)
        for value in (datetime(2026, 1, 1), utc(0) - timedelta(milliseconds=1), 1.0,
                      datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=9)))):
            with self.subTest(value_type=type(value).__name__), self.assertRaises(CycleError):
                module._milliseconds(value)

    def attempted(self):
        config = configuration()
        plan = module.plan_action(config, checkpoint(), canonical(), evaluated_at_ms=HOUR,
                                  mode=DecisionMode.LIVE, action_history=())
        return config, replace(plan.action, phase=ActionPhase.ATTEMPT_STARTED, attempt_count=1)

    def receipt(self, action):
        return SpotMarketOrderAcknowledgement("bybit-demo", "order-1", action.order_link_id, "BTCUSDT",
                                              "BUY", "MARKET", D("10.1234567"), "QUOTE", utc(HOUR + 1000), utc(HOUR + 1000))

    def test_receipt_validation_checks_identity_money_and_utc_without_coercion(self):
        config, action = self.attempted()
        receipt = self.receipt(action)
        invalid = [(field, value) for field, value in (
            ("broker_id", "live"), ("broker_order_id", ""), ("broker_order_id", "unsafe/id"),
            ("order_link_id", "different"), ("symbol", "ETHUSDT"), ("side", "SELL"),
            ("order_type", "LIMIT"), ("amount_unit", "BASE"),
            ("submitted_amount", 10.0), ("submitted_amount", D("0")), ("submitted_amount", D("999")),
            ("submitted_amount", D("NaN")), ("fetched_at", datetime(2026, 1, 1)),
            ("broker_timestamp", utc(HOUR - 1)), ("fetched_at", utc(HOUR + 2001)),
            ("broker_timestamp", utc(HOUR + 2001)),
        )]
        for field, value in invalid:
            with self.subTest(field=field, value_type=type(value).__name__), self.assertRaises((CycleError, RuntimeStoreError)):
                module._receipt_action(action, replace(receipt, **{field: value}), config, HOUR + 1000)
        with self.assertRaises(CycleError):
            module._receipt_action(action, {"orderId": "order-1"}, config, HOUR + 1000)

    def test_valid_receipt_is_only_ack_with_no_fill_status_or_inventory(self):
        config, action = self.attempted()
        acknowledged = module._receipt_action(action, self.receipt(action), config, HOUR + 1000)
        self.assertIs(acknowledged.phase, ActionPhase.ACKNOWLEDGED)
        self.assertIsNone(acknowledged.order_status)
        self.assertIsNone(acknowledged.terminal_at_ms)
        self.assertEqual(acknowledged.attempt_count, 1)
        self.assertEqual(acknowledged.authorized_amount, action.authorized_amount)

    def test_strategy_alignment_types_and_transition_failures_are_not_repaired(self):
        config = configuration()
        prefix = ClosedCandlePrefix("BTCUSDT", "60", 0, 50 * HOUR, 50 * HOUR, 50 * HOUR, candles(["100"] * 50))
        for case in ("row_count", "index", "timestamp", "signal_time", "signal", "float_desired", "bool_desired", "hold_changes_intent"):
            def changed(frame, **kwargs):
                output = generate_ema_signals(frame, **kwargs)
                if case == "row_count":
                    return output.iloc[:-1]
                if case == "index":
                    output.index = output.index + 1
                elif case == "timestamp":
                    output["timestamp"] += pd.Timedelta(seconds=1)
                elif case == "signal_time":
                    output["signal_time"] += pd.Timedelta(hours=1)
                elif case == "signal":
                    output.loc[0, "signal"] = "BUY"
                elif case == "float_desired":
                    output["desired_position"] = output["desired_position"].astype(float)
                elif case == "bool_desired":
                    output["desired_position"] = False
                else:
                    output.loc[0, "desired_position"] = 1
                return output
            with self.subTest(case=case), patch.object(module, "generate_ema_signals", side_effect=changed), self.assertRaises(ValueError):
                module._strategy_decisions(prefix, config)

    def test_cycle_outcomes_are_explicit_and_finite(self):
        self.assertEqual([value.value for value in CycleOutcome], ["BOOTSTRAP", "REPLAY_ONLY", "NO_NEW_DATA", "NOOP", "WAIT",
                                                                  "RECONCILE", "HALTED", "STOPPING", "OBSERVED", "ABANDONED_UNSENT"])


if __name__ == "__main__":
    unittest.main()
