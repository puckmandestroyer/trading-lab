"""Offline startup recovery through public journal APIs and normalized reads."""

import ast
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal, localcontext
import inspect
import sqlite3
import unittest
from unittest.mock import patch

from trading_lab.exchange.account_state import (
    AccountState, BrokerOrderNotFoundError, CurrencyBalance, ExecutionState, OrderState, OrderStatus,
)
from trading_lab.runtime.reconciliation import ReconciliationError, reconcile_startup
import trading_lab.runtime.reconciliation as module
from trading_lab.runtime.state import (
    PendingAction, PendingActionKind, PositionEvidence, RuntimeEvent, RuntimeEventType,
    RuntimeEvidence, RuntimeReason, RuntimeState, RuntimeStateSnapshot, transition_runtime_state,
)
from trading_lab.runtime.store import ActionPhase, ActionRecord, JournalActionKind, RuntimeStoreError
from tests.test_runtime_store import ACTION_ID, D, HOUR, StoreCase, candle, fill, terminal


NOW_MS = HOUR + 10000


def utc(milliseconds=NOW_MS):
    return datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(milliseconds=milliseconds)


def account(quantity="1"):
    return AccountState("bybit-demo", "research", "USD", D("50000"), D("50000"), D("50000"),
                        (CurrencyBalance("BTC", D(quantity), D(quantity), D(quantity)),
                         CurrencyBalance("USDT", D("1000"), D("1000"), D("0"))), utc(), utc())


def order(status=OrderStatus.OPEN, *, quantity="0", order_id="order-1", action_id=ACTION_ID,
          requested="10.1234567", side="BUY", unit="QUOTE"):
    base = D(quantity)
    quote = base * D("100")
    filled = quote if unit == "QUOTE" else base
    return OrderState(
        broker_id="bybit-demo", account_id="research", broker_order_id=order_id,
        symbol="BTCUSDT", side=side, order_type="MARKET", status=status,
        external_status={OrderStatus.OPEN: "New", OrderStatus.PARTIALLY_FILLED: "PartiallyFilled",
                         OrderStatus.FILLED: "Filled", OrderStatus.CANCELLED: "Cancelled",
                         OrderStatus.REJECTED: "Rejected", OrderStatus.EXPIRED: "Expired",
                         OrderStatus.UNKNOWN: "FutureStatus", OrderStatus.NEW: "Triggered"}[status],
        quantity_unit=unit, requested_quantity=D(requested), filled_quantity=filled,
        remaining_quantity=D(requested) - filled, filled_base_quantity=base,
        filled_quote_amount=quote, average_fill_price=D("100") if base else None,
        limit_price=None, stop_price=None, created_at=utc(HOUR + 1), updated_at=utc(HOUR + 8000),
        broker_timestamp=utc(), fetched_at=utc(), order_link_id="bot1-" + action_id[:23],
    )


def execution(execution_id="exec-1", *, quantity="0.05", fee="0.00005", currency="BTC",
              action_id=ACTION_ID, order_id="order-1", side="BUY"):
    return ExecutionState("bybit-demo", "research", execution_id, order_id, "bot1-" + action_id[:23],
                          "BTCUSDT", side, D(quantity), D("100"), D(fee), currency,
                          utc(HOUR + 4000), utc(), utc())


class FakeReadOnlyBroker:
    def __init__(self, store):
        self.store = store
        self.account = account()
        self.opens = ()
        self.executions = ()
        self.exact_executions = None
        self.order = order()
        self.errors = {}
        self.calls = []

    def observe(self, method, **kwargs):
        # Instrument the real temporary SQLite connection, not a comment or mock
        # transaction flag. Production code never accesses this private field.
        if self.store._connection.in_transaction:
            raise AssertionError("Broker read occurred inside a SQLite transaction")
        self.calls.append((method, kwargs))
        if method in self.errors:
            raise self.errors[method]

    def get_account_state(self):
        self.observe("get_account_state")
        return self.account

    def get_open_orders(self, symbol=None):
        self.observe("get_open_orders", symbol=symbol)
        return self.opens

    def get_order(self, order_id):
        self.observe("get_order", order_id=order_id)
        return self.order

    def get_executions(self, order_id=None, symbol=None):
        self.observe("get_executions", order_id=order_id, symbol=symbol)
        if order_id is not None and self.exact_executions is not None:
            return self.exact_executions
        return self.executions


class ReconciliationTests(StoreCase):
    def setUp(self):
        super().setUp()
        self.enterContext(patch("socket.create_connection", side_effect=AssertionError("No network")))
        self.broker = FakeReadOnlyBroker(self.store)
        self.now_ms = NOW_MS

    def run_round(self, **kwargs):
        return reconcile_startup(self.store, self.broker, utc_now=lambda: utc(self.now_ms), monotonic=lambda: 1.0, **kwargs)

    def sell(self, amount="0.1"):
        entry = self.acknowledge()
        current = self.store.get_checkpoint()
        owned = replace(fill(), executed_quantity=D("0.1"), execution_fee=D("0"))
        self.store.record_observation(terminal(entry), self.next_checkpoint(snapshot=RuntimeStateSnapshot(
            RuntimeState.LONG, D("0.1"), PositionEvidence.CONFIRMED, 1)), expected_sequence=current.sequence, fills=(owned,))
        exit_id = "e" * 64
        action = ActionRecord(exit_id, JournalActionKind.EXIT, "BTCUSDT", 2 * HOUR + 600000, 5, 3,
                             "bot1-" + exit_id[:23], HOUR, side="SELL", amount_unit="BASE",
                             currency="BTC", authorized_amount=D("0.1"))
        from trading_lab.runtime.store import DecisionRecord, DecisionDisposition
        decision = DecisionRecord("BTCUSDT", "60", HOUR, "d" * 64, "LONG_EXIT", 0,
                                  DecisionDisposition.ACTION, 2 * HOUR, exit_id)
        pending = RuntimeStateSnapshot(RuntimeState.ORDER_PENDING, D("0.1"), PositionEvidence.CONFIRMED, 0,
                                       PendingAction(exit_id, PendingActionKind.EXIT))
        current = self.store.get_checkpoint()
        self.store.commit_decision(candle(HOUR), decision,
                                   self.next_checkpoint(snapshot=pending, last_processed_candle_ms=HOUR),
                                   expected_sequence=current.sequence, action=action)
        current = self.store.get_checkpoint()
        self.store.start_attempt(exit_id, self.next_checkpoint(), expected_sequence=current.sequence)
        action = replace(self.store.get_action(exit_id), phase=ActionPhase.ACKNOWLEDGED,
                         broker_order_id="order-2", submitted_amount=D(amount),
                         acknowledgement_broker_ms=2 * HOUR + 1, acknowledgement_observed_ms=2 * HOUR + 2)
        current = self.store.get_checkpoint()
        self.store.record_observation(action, self.next_checkpoint(), expected_sequence=current.sequence)
        self.now_ms = 2 * HOUR + 10000
        self.broker.account = replace(account(), broker_timestamp=utc(self.now_ms), fetched_at=utc(self.now_ms))
        self.broker.order = replace(order(OrderStatus.FILLED, quantity=amount, order_id="order-2", action_id=exit_id,
                                          requested=amount, side="SELL", unit="BASE"),
                                    created_at=utc(2 * HOUR + 1), updated_at=utc(2 * HOUR + 8000),
                                    broker_timestamp=utc(self.now_ms), fetched_at=utc(self.now_ms))
        self.broker.executions = (replace(execution("sell-1", quantity=amount, fee="0.01", currency="USDT",
                                                   action_id=exit_id, order_id="order-2", side="SELL"),
                                         executed_at=utc(2 * HOUR + 4000), broker_timestamp=utc(self.now_ms), fetched_at=utc(self.now_ms)),)
        return action

    def unknown(self):
        action = replace(self.attempt(), phase=ActionPhase.UNKNOWN_OUTCOME,
                         safe_reason=RuntimeReason.ACTION_OUTCOME_UNKNOWN)
        current = self.store.get_checkpoint()
        snapshot = transition_runtime_state(current.snapshot, RuntimeEvent(
            RuntimeEventType.UNCERTAINTY_DETECTED, reason=RuntimeReason.ACTION_OUTCOME_UNKNOWN))
        self.store.record_observation(action, self.next_checkpoint(snapshot=snapshot), expected_sequence=current.sequence)
        return action

    def known(self, status=OrderStatus.OPEN, quantity="0", **kwargs):
        self.acknowledge()
        self.broker.order = order(status, quantity=quantity, **kwargs)
        return self.store.get_action(ACTION_ID)

    def cancel_control(self, *, unknown=True):
        cancel = ActionRecord("e" * 64, JournalActionKind.CANCEL, "BTCUSDT", HOUR + 600000, 5, 3,
                              control_id="operator-cancel", parent_action_id=ACTION_ID, target_broker_order_id="order-1")
        current = self.store.get_checkpoint()
        self.store.prepare_cancellation(cancel, self.next_checkpoint(), expected_sequence=current.sequence)
        current = self.store.get_checkpoint()
        self.store.start_attempt(cancel.logical_action_id, self.next_checkpoint(), expected_sequence=current.sequence)
        cancel = self.store.get_action(cancel.logical_action_id)
        if unknown:
            cancel = replace(cancel, phase=ActionPhase.UNKNOWN_OUTCOME, safe_reason=RuntimeReason.ACTION_OUTCOME_UNKNOWN)
            snapshot = transition_runtime_state(self.store.get_checkpoint().snapshot, RuntimeEvent(
                RuntimeEventType.UNCERTAINTY_DETECTED, reason=RuntimeReason.ACTION_OUTCOME_UNKNOWN))
        else:
            cancel = replace(cancel, phase=ActionPhase.ACKNOWLEDGED,
                             acknowledgement_broker_ms=HOUR + 5000, acknowledgement_observed_ms=HOUR + 6000)
            snapshot = self.store.get_checkpoint().snapshot
        current = self.store.get_checkpoint()
        self.store.record_observation(cancel, self.next_checkpoint(snapshot=snapshot), expected_sequence=current.sequence)
        return cancel

    def assert_state(self, result, expected, quantity=None):
        self.assertIs(result.checkpoint.snapshot.state, expected)
        self.assertEqual(result.checkpoint, self.store.get_checkpoint())
        if quantity is not None:
            self.assertEqual(result.checkpoint.snapshot.owned_base_quantity, D(quantity))

    def test_fresh_store_with_unrelated_wallet_btc_is_bot_flat(self):
        self.assertIsNone(self.store.get_checkpoint().snapshot.owned_base_quantity)
        self.broker.account = account("50")
        result = self.run_round()
        self.assert_state(result, RuntimeState.FLAT, "0")
        self.assertEqual(self.store.list_actions(), ())
        self.assertEqual(self.store.list_fills(), ())
        self.assertEqual(len(self.broker.calls), 3)

    def test_durable_flat_does_not_adopt_extra_btc(self):
        self.flat()
        self.assert_state(self.run_round(), RuntimeState.FLAT, "0")

    def test_empty_coin_balances_do_not_invent_holdings_for_fresh_flat(self):
        self.broker.account = replace(account(), balances=())
        self.assert_state(self.run_round(), RuntimeState.FLAT, "0")

    def test_unrelated_historical_execution_does_not_become_bot_owned(self):
        self.broker.executions = (replace(execution(), order_link_id="manual-order", broker_order_id="manual-1"),)
        self.assert_state(self.run_round(), RuntimeState.FLAT, "0")
        self.assertEqual(self.store.list_fills(), ())

    def test_durable_long_survives_expired_broker_history_and_extra_wallet(self):
        self.settle(self.acknowledge(), fill())
        self.reopen()
        self.broker.store = self.store
        self.broker.account = account("50")
        self.broker.executions = ()
        self.assert_state(self.run_round(), RuntimeState.LONG, "0.1234691346789")
        self.assertEqual(self.store.list_fills(), (fill(),))
        self.assertFalse(any(name == "get_order" for name, _ in self.broker.calls))

    def test_locked_holdings_cover_long_without_available_cash(self):
        self.settle(self.acknowledge(), fill())
        self.broker.account = account("0.1234691346789")
        self.assertIsNone(self.broker.account.balances[0].available_balance)
        self.assert_state(self.run_round(), RuntimeState.LONG, "0.1234691346789")

    def test_insufficient_wallet_coverage_halts_and_keeps_last_known_quantity(self):
        self.settle(self.acknowledge(), fill())
        self.broker.account = account("0.01")
        result = self.run_round()
        self.assert_state(result, RuntimeState.HALTED, "0.1234691346789")
        self.assertIs(result.checkpoint.snapshot.position_evidence, PositionEvidence.LAST_KNOWN)

    def test_missing_base_currency_is_uncertain_not_zero_or_usd(self):
        self.settle(self.acknowledge(), fill())
        self.broker.account = replace(account(), balances=(account().balances[1],))
        self.assert_state(self.run_round(), RuntimeState.UNCERTAIN, "0.1234691346789")

    def test_owned_quantity_disagreeing_with_durable_fills_is_fatal(self):
        self.flat()
        current = self.store.get_checkpoint()
        self.store.save_checkpoint(self.next_checkpoint(snapshot=RuntimeStateSnapshot(
            RuntimeState.LONG, D("1"), PositionEvidence.CONFIRMED, 0)), expected_sequence=current.sequence)
        self.assert_state(self.run_round(), RuntimeState.HALTED, "1")

    def test_terminal_filled_action_without_required_fill_history_halts(self):
        self.settle(self.acknowledge())
        self.assert_state(self.run_round(), RuntimeState.HALTED)

    def test_known_open_order_is_pending_and_uses_exact_order_reads(self):
        original = self.known()
        result = self.run_round()
        self.assert_state(result, RuntimeState.ORDER_PENDING, "0")
        self.assertEqual(result.placement.broker_order_id, original.broker_order_id)
        self.assertIn(("get_order", {"order_id": "order-1"}), self.broker.calls)
        self.assertIn(("get_executions", {"order_id": "order-1", "symbol": None}), self.broker.calls)
        self.assertEqual(len(self.broker.calls), 5)

    def test_partial_fill_stays_pending_and_persists_exact_base_fee(self):
        self.known(OrderStatus.PARTIALLY_FILLED, "0.05")
        self.broker.executions = (execution(),)
        result = self.run_round()
        self.assert_state(result, RuntimeState.ORDER_PENDING, "0.04995")
        self.assertEqual(result.new_execution_ids, ("exec-1",))
        self.assertEqual(len(self.store.list_fills()), 1)

    def test_filled_quote_buy_can_leave_unused_authorization(self):
        self.known(OrderStatus.FILLED, "0.05")
        self.broker.executions = (execution(fee="0.01", currency="USDT"),)
        result = self.run_round()
        self.assert_state(result, RuntimeState.LONG, "0.05")
        self.assertIs(result.placement.phase, ActionPhase.TERMINAL_CONFIRMED)
        self.assertIsNone(result.checkpoint.snapshot.pending_action)
        self.assertEqual(result.placement.submitted_amount, D("10.1234567"))

    def test_cancelled_partial_buy_can_confirm_smaller_long(self):
        self.known(OrderStatus.CANCELLED, "0.05")
        self.broker.executions = (execution(),)
        self.assert_state(self.run_round(), RuntimeState.LONG, "0.04995")

    def test_unfilled_cancelled_rejected_and_expired_orders_confirm_flat(self):
        for status in (OrderStatus.CANCELLED, OrderStatus.REJECTED, OrderStatus.EXPIRED):
            with self.subTest(status=status):
                # Separate valid temporary stores; do not reuse a consumed action.
                case = ReconciliationTests()
                case.setUp()
                try:
                    case.known(status)
                    result = case.run_round()
                    case.assert_state(result, RuntimeState.FLAT, "0")
                    self.assertIs(result.placement.phase, ActionPhase.TERMINAL_CONFIRMED)
                finally:
                    case.doCleanups()

    def test_unknown_and_new_order_status_cannot_confirm_a_position(self):
        self.known(OrderStatus.UNKNOWN)
        unknown = self.run_round()
        self.assert_state(unknown, RuntimeState.UNCERTAIN, "0")
        self.assertEqual(unknown.placement.order_status, "UNKNOWN")
        self.assertEqual(unknown.placement.external_status, "FutureStatus")
        self.broker.order = order(OrderStatus.NEW)
        self.assert_state(self.run_round(), RuntimeState.UNCERTAIN, "0")

    def test_known_order_not_found_remains_uncertain_and_never_rejected(self):
        self.known()
        self.broker.errors["get_order"] = BrokerOrderNotFoundError("synthetic-private-history")
        result = self.run_round()
        self.assert_state(result, RuntimeState.UNCERTAIN, "0")
        self.assertIs(result.placement.phase, ActionPhase.ACKNOWLEDGED)
        self.assertIsNone(result.placement.terminal_at_ms)

    def test_lost_ack_open_discovery_recovers_id_without_inventing_receipt(self):
        original = self.unknown()
        self.broker.opens = (order(),)
        result = self.run_round()
        self.assert_state(result, RuntimeState.ORDER_PENDING, "0")
        self.assertIs(result.placement.phase, ActionPhase.UNKNOWN_OUTCOME)
        self.assertEqual(result.placement.attempt_count, 1)
        self.assertEqual((result.placement.logical_action_id, result.placement.order_link_id),
                         (original.logical_action_id, original.order_link_id))
        self.assertIsNone(result.placement.acknowledgement_broker_ms)
        self.assertIsNone(result.placement.acknowledgement_observed_ms)
        self.assertIsNone(result.placement.submitted_amount)
        self.reopen()
        self.assertEqual(self.store.get_action(ACTION_ID), result.placement)
        self.assertEqual(self.store.get_checkpoint(), result.checkpoint)

    def test_lost_ack_partial_fill_discovery_survives_reopen(self):
        self.unknown()
        self.broker.order = order(OrderStatus.PARTIALLY_FILLED, quantity="0.05")
        self.broker.opens = (self.broker.order,)
        self.broker.executions = (execution(),)
        result = self.run_round()
        self.assert_state(result, RuntimeState.ORDER_PENDING, "0.04995")
        self.reopen()
        self.broker.store = self.store
        self.assertEqual(len(self.store.list_fills()), 1)
        replay = self.run_round()
        self.assert_state(replay, RuntimeState.ORDER_PENDING, "0.04995")
        self.assertEqual(replay.new_execution_ids, ())
        self.assertIsNone(replay.placement.acknowledgement_observed_ms)
        self.assertEqual(replay.placement.attempt_count, 1)

    def test_lost_ack_execution_discovery_can_recover_terminal_order(self):
        self.unknown()
        self.broker.executions = (execution(),)
        self.broker.order = order(OrderStatus.FILLED, quantity="0.05")
        result = self.run_round()
        self.assert_state(result, RuntimeState.LONG, "0.04995")
        self.assertEqual(result.placement.broker_order_id, "order-1")
        self.assertIsNone(result.placement.submitted_amount)

    def test_missing_exact_link_is_uncertain_not_permission_to_resend(self):
        original = self.unknown()
        self.assert_state(self.run_round(), RuntimeState.UNCERTAIN, "0")
        self.assertEqual(self.store.get_action(ACTION_ID).order_link_id, original.order_link_id)
        self.assertIsNone(self.store.get_action(ACTION_ID).broker_order_id)

    def test_prefix_only_link_is_a_namespace_collision_not_ownership(self):
        self.unknown()
        self.broker.opens = (replace(order(), order_link_id=order().order_link_id + "-other"),)
        self.assert_state(self.run_round(), RuntimeState.HALTED)

    def test_multiple_exact_link_order_ids_halt_without_choosing_one(self):
        self.unknown()
        self.broker.opens = (order(), order(order_id="order-2"))
        result = self.run_round()
        self.assert_state(result, RuntimeState.HALTED)
        self.assertIsNone(result.placement.broker_order_id)

    def test_open_and_execution_candidates_with_different_ids_halt(self):
        self.unknown()
        self.broker.opens = (order(),)
        self.broker.executions = (execution(order_id="order-2"),)
        self.assert_state(self.run_round(), RuntimeState.HALTED)

    def test_unrecorded_namespace_execution_proves_missing_history_and_halts(self):
        self.broker.executions = (execution(action_id="f" * 64),)
        self.assert_state(self.run_round(), RuntimeState.HALTED)

    def test_unrelated_managed_symbol_order_blocks_activation_without_adoption(self):
        self.broker.opens = (replace(order(), order_link_id="manual-order"),)
        self.assert_state(self.run_round(), RuntimeState.HALTED)
        self.assertEqual(self.store.list_actions(), ())

    def test_repeated_execution_is_applied_once_and_aged_out_fill_is_retained(self):
        self.known(OrderStatus.PARTIALLY_FILLED, "0.05")
        self.broker.executions = (execution(), execution())
        self.run_round()
        self.broker.executions = ()
        result = self.run_round()
        self.assert_state(result, RuntimeState.ORDER_PENDING, "0.04995")
        self.assertEqual(result.new_execution_ids, ())
        self.assertEqual(len(self.store.list_fills(ACTION_ID)), 1)

    def test_conflicting_execution_id_halts_without_changing_original_fill(self):
        self.known(OrderStatus.PARTIALLY_FILLED, "0.05")
        self.broker.executions = (execution(),)
        self.run_round()
        original = self.store.get_fill("exec-1")
        self.broker.executions = (replace(execution(), execution_fee=D("0.001")),)
        self.assert_state(self.run_round(), RuntimeState.HALTED)
        self.assertEqual(self.store.get_fill("exec-1"), original)

    def test_wrong_order_link_side_or_symbol_execution_is_fatal(self):
        self.known(OrderStatus.PARTIALLY_FILLED, "0.05")
        self.broker.executions = (replace(execution(), side="SELL"),)
        self.assert_state(self.run_round(), RuntimeState.HALTED)
        self.assertEqual(self.store.list_fills(), ())

    def test_exact_order_read_cannot_return_a_different_broker_id(self):
        self.unknown()
        self.broker.opens = (order(),)
        self.broker.order = order(order_id="wrong-order")
        self.assert_state(self.run_round(), RuntimeState.HALTED)

    def test_order_identity_unit_or_authorization_mismatch_halts(self):
        self.known()
        self.broker.order = replace(order(), quantity_unit="BASE")
        self.assert_state(self.run_round(), RuntimeState.HALTED)

    def test_conditional_or_limit_owned_order_is_not_supported(self):
        self.known()
        self.broker.order = replace(order(), stop_price=D("99"))
        self.assert_state(self.run_round(), RuntimeState.HALTED)

    def test_filled_status_without_complete_executions_is_uncertain(self):
        self.known(OrderStatus.FILLED, "0.05")
        self.assert_state(self.run_round(), RuntimeState.UNCERTAIN)
        self.assertEqual(self.store.list_fills(), ())

    def test_non_atomic_open_and_exact_order_race_remains_uncertain(self):
        self.known(OrderStatus.FILLED, "0.05")
        self.broker.opens = (order(),)
        self.broker.executions = (execution(),)
        self.assert_state(self.run_round(), RuntimeState.UNCERTAIN)
        self.assertEqual(self.store.list_fills(), ())

    def test_nonzero_fee_without_currency_blocks_inventory_settlement(self):
        self.known(OrderStatus.FILLED, "0.05")
        self.broker.executions = (execution(currency=None),)
        self.assert_state(self.run_round(), RuntimeState.UNCERTAIN)
        self.assertEqual(self.store.list_fills(), ())

    def test_base_rebate_increases_only_exact_owned_quantity(self):
        self.known(OrderStatus.FILLED, "0.05")
        self.broker.executions = (execution(fee="-0.00005"),)
        with localcontext() as context:
            context.prec = 2
            self.assert_state(self.run_round(), RuntimeState.LONG, "0.05005")

    def test_zero_fee_with_unknown_currency_is_valid(self):
        self.known(OrderStatus.FILLED, "0.05")
        self.broker.executions = (execution(fee="0", currency=None),)
        self.assert_state(self.run_round(), RuntimeState.LONG, "0.05")

    def test_other_currency_fee_does_not_reduce_base_inventory(self):
        self.known(OrderStatus.FILLED, "0.05")
        self.broker.executions = (execution(fee="0.01", currency="BNB"),)
        self.assert_state(self.run_round(), RuntimeState.LONG, "0.05")

    def test_unknown_cancellation_is_discovered_and_not_resolved_by_open_parent(self):
        self.known()
        cancel = self.cancel_control()
        self.reopen()
        self.broker.store = self.store
        result = self.run_round()
        self.assert_state(result, RuntimeState.UNCERTAIN, "0")
        self.assertEqual(result.cancellation.logical_action_id, cancel.logical_action_id)
        self.assertIs(result.cancellation.phase, ActionPhase.UNKNOWN_OUTCOME)
        self.assertEqual(result.cancellation.target_broker_order_id, "order-1")

    def test_cancellation_receipt_is_not_terminal_proof(self):
        self.known()
        self.cancel_control(unknown=False)
        result = self.run_round()
        self.assert_state(result, RuntimeState.ORDER_PENDING)
        self.assertIs(result.cancellation.phase, ActionPhase.ACKNOWLEDGED)
        self.assertIsNone(result.cancellation.terminal_at_ms)

    def test_concurrent_fill_closes_parent_and_cancel_control_without_claiming_cancelled(self):
        self.known()
        self.cancel_control()
        self.broker.order = order(OrderStatus.FILLED, quantity="0.05")
        self.broker.executions = (execution(),)
        result = self.run_round()
        self.assert_state(result, RuntimeState.LONG, "0.04995")
        self.assertEqual(result.cancellation.order_status, "FILLED")
        self.assertIs(result.cancellation.phase, ActionPhase.TERMINAL_CONFIRMED)
        self.assertIsNone(result.cancellation.acknowledgement_broker_ms)
        self.assertIs(result.placement.phase, ActionPhase.TERMINAL_CONFIRMED)

    def test_halt_latch_and_stopping_from_halted_do_not_make_broker_reads(self):
        self.unknown()
        current = self.store.get_checkpoint()
        halted = transition_runtime_state(current.snapshot, RuntimeEvent(
            RuntimeEventType.FATAL_INCONSISTENCY, reason=RuntimeReason.RECOVERY_EXHAUSTED))
        self.store.save_checkpoint(self.next_checkpoint(snapshot=halted, halted_at_ms=NOW_MS), expected_sequence=current.sequence)
        before = self.store.get_checkpoint()
        self.assertEqual(self.run_round().checkpoint, before)
        current = self.store.get_checkpoint()
        stopped = transition_runtime_state(current.snapshot, RuntimeEvent(RuntimeEventType.SHUTDOWN_REQUESTED))
        self.store.save_checkpoint(self.next_checkpoint(snapshot=stopped, shutdown_at_ms=NOW_MS), expected_sequence=current.sequence)
        before = self.store.get_checkpoint()
        self.assertEqual(self.run_round().checkpoint, before)
        self.assertEqual(self.broker.calls, [])

    def test_explicit_rearm_keeps_unknown_outcome_then_reconciliation_recovers(self):
        self.unknown()
        current = self.store.get_checkpoint()
        halted = transition_runtime_state(current.snapshot, RuntimeEvent(
            RuntimeEventType.FATAL_INCONSISTENCY, reason=RuntimeReason.OWNERSHIP_CONFLICT))
        self.store.save_checkpoint(self.next_checkpoint(snapshot=halted, halted_at_ms=NOW_MS - 2), expected_sequence=current.sequence)
        current = self.store.get_checkpoint()
        sync = transition_runtime_state(current.snapshot, RuntimeEvent(RuntimeEventType.OPERATOR_REARMED))
        self.store.save_checkpoint(self.next_checkpoint(snapshot=sync, halted_at_ms=None, rearmed_at_ms=NOW_MS - 1), expected_sequence=current.sequence)
        self.broker.opens = (order(),)
        self.assert_state(self.run_round(), RuntimeState.ORDER_PENDING, "0")
        self.assertIs(self.store.get_action(ACTION_ID).phase, ActionPhase.UNKNOWN_OUTCOME)

    def test_recovery_tokens_decrement_before_reads_and_survive_restart(self):
        self.unknown()
        first = self.run_round()
        self.assertEqual((first.placement.remaining_reconciliation_rounds, first.placement.remaining_read_attempts), (4, 2))
        self.reopen()
        self.broker.store = self.store
        second = self.run_round()
        self.assertEqual((second.placement.remaining_reconciliation_rounds, second.placement.remaining_read_attempts), (3, 1))
        third = self.run_round()
        self.assert_state(third, RuntimeState.HALTED)
        self.assertIs(third.checkpoint.snapshot.reason, RuntimeReason.RECOVERY_EXHAUSTED)
        self.assertEqual(third.placement.remaining_read_attempts, 0)

    def test_expired_deadline_blocks_reads_and_halts(self):
        self.unknown()
        result = reconcile_startup(self.store, self.broker, utc_now=lambda: utc(HOUR + 600000), monotonic=lambda: 1.0)
        self.assert_state(result, RuntimeState.HALTED)
        self.assertEqual(self.broker.calls, [])

    def test_read_failure_is_not_successful_empty_state_and_does_not_retry(self):
        self.unknown()
        self.broker.errors["get_account_state"] = TimeoutError("synthetic-private-auth-response")
        result = self.run_round()
        self.assert_state(result, RuntimeState.UNCERTAIN)
        self.assertEqual(len(self.broker.calls), 1)
        self.assertNotIn("synthetic-private", repr(result))
        self.assertEqual(result.placement.remaining_read_attempts, 2)

    def test_all_broker_reads_occur_outside_real_sqlite_transactions(self):
        self.known(OrderStatus.PARTIALLY_FILLED, "0.05")
        self.broker.executions = (execution(),)
        self.assert_state(self.run_round(), RuntimeState.ORDER_PENDING)
        self.assertEqual(len(self.broker.calls), 5)
        self.assertFalse(self.store._connection.in_transaction)

    def test_restart_uses_both_public_enumeration_apis_and_exact_fill_filter(self):
        self.known(OrderStatus.PARTIALLY_FILLED, "0.05")
        self.broker.executions = (execution(),)
        self.run_round()
        self.reopen()
        self.broker.store = self.store
        self.broker.executions = ()
        with patch.object(self.store, "list_actions", wraps=self.store.list_actions) as actions, \
                patch.object(self.store, "list_fills", wraps=self.store.list_fills) as fills:
            self.assert_state(self.run_round(), RuntimeState.ORDER_PENDING, "0.04995")
            actions.assert_called()
            fills.assert_any_call()
            fills.assert_any_call(ACTION_ID)

    def test_observation_commit_failure_rolls_back_fill_id_and_quantity_together(self):
        self.unknown()
        self.broker.order = order(OrderStatus.PARTIALLY_FILLED, quantity="0.05")
        self.broker.opens = (self.broker.order,)
        self.broker.executions = (execution(),)
        original = self.store.record_observation

        def commit_fault(action, checkpoint, **kwargs):
            if kwargs.get("fills"):
                with patch.object(self.store, "_commit", side_effect=sqlite3.OperationalError("Injected failure")):
                    return original(action, checkpoint, **kwargs)
            return original(action, checkpoint, **kwargs)

        with patch.object(self.store, "record_observation", side_effect=commit_fault), self.assertRaises(RuntimeStoreError):
            self.run_round()
        self.reopen()
        self.assertEqual(self.store.list_fills(), ())
        self.assertIsNone(self.store.get_action(ACTION_ID).broker_order_id)
        self.assertEqual(self.store.get_checkpoint().snapshot.owned_base_quantity, D("0"))
        self.assertEqual(self.store.get_action(ACTION_ID).remaining_read_attempts, 2)

    def test_prepared_unsent_placement_is_abandoned_without_replaying_it(self):
        self.prepare()
        self.assert_state(self.run_round(), RuntimeState.FLAT, "0")
        self.assertIs(self.store.get_action(ACTION_ID).phase, ActionPhase.ABANDONED_UNSENT)
        self.assertEqual(self.store.get_action(ACTION_ID).attempt_count, 0)

    def test_naive_or_non_utc_observation_timestamp_halts(self):
        self.broker.account = replace(account(), broker_timestamp=datetime(2026, 10, 12))
        self.assert_state(self.run_round(), RuntimeState.HALTED)

    def test_stale_account_observation_remains_uncertain(self):
        self.broker.account = replace(account(), broker_timestamp=utc(0), fetched_at=utc(0))
        self.assert_state(self.run_round(), RuntimeState.UNCERTAIN)

    def test_wrong_demo_or_caller_account_label_halts(self):
        self.broker.account = replace(account(), broker_id="bybit-live")
        self.assert_state(self.run_round(), RuntimeState.HALTED)

    def test_absent_caller_label_does_not_fabricate_authenticated_account_identity(self):
        self.broker.account = replace(account(), account_id=None)
        self.assert_state(self.run_round(), RuntimeState.FLAT)

    def test_invalid_clock_input_fails_without_broker_access_or_state_change(self):
        before = self.store.get_checkpoint()
        with self.assertRaises(ReconciliationError):
            reconcile_startup(self.store, self.broker, utc_now=lambda: datetime(2026, 10, 12))
        self.assertEqual(self.store.get_checkpoint(), before)
        self.assertEqual(self.broker.calls, [])

    def test_result_is_immutable_and_contains_no_client_or_payload(self):
        result = self.run_round()
        self.assertFalse(hasattr(result, "__dict__"))
        with self.assertRaises(FrozenInstanceError):
            result.checkpoint = None
        self.assertFalse(hasattr(result, "broker"))
        self.assertFalse(hasattr(result, "raw_response"))

    def test_structural_boundary_has_no_mutation_private_sql_strategy_or_scheduler(self):
        source = inspect.getsource(module)
        tree = ast.parse(source)
        imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        imports.update(alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names)
        self.assertEqual(imports, {"collections.abc", "dataclasses", "datetime", "decimal", "math", "time",
                                   "exchange.account_state", "state", "store"})
        forbidden = {"_connection", "execute", "connect", "place_order", "place_market_order", "cancel_order",
                     "amend_order", "replace_order", "sleep", "getenv", "environ"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                self.assertNotIn(node.attr, forbidden)
            self.assertNotIsInstance(node, (ast.While, ast.AsyncFunctionDef, ast.Await))
        self.assertNotIn("BybitDemoOrderAdapter", source)
        self.assertNotIn("generate_ema_signals", source)

    def test_filled_sell_confirms_flat_only_from_exact_executions(self):
        self.sell()
        self.assert_state(self.run_round(), RuntimeState.FLAT, "0")
        self.assertEqual(len(self.store.list_fills()), 2)

    def test_filled_sell_with_rounding_remainder_remains_long(self):
        self.sell("0.09")
        self.assert_state(self.run_round(), RuntimeState.LONG, "0.01")

    def test_sell_base_fee_that_overspends_owned_inventory_is_fatal(self):
        self.sell()
        self.broker.executions = (replace(self.broker.executions[0], execution_fee=D("0.001"), fee_currency="BTC"),)
        self.assert_state(self.run_round(), RuntimeState.HALTED, "0.1")
        self.assertEqual(len(self.store.list_fills()), 1)

    def test_multiple_partial_executions_are_exactly_deduplicated(self):
        self.known(OrderStatus.PARTIALLY_FILLED, "0.05")
        self.broker.executions = (execution("one", quantity="0.02", fee="0.00002"),
                                  execution("two", quantity="0.03", fee="0.00003"))
        result = self.run_round()
        self.assert_state(result, RuntimeState.ORDER_PENDING, "0.04995")
        self.assertEqual(result.new_execution_ids, ("one", "two"))
        self.assertEqual(len(self.store.list_fills()), 2)

    def test_wrong_execution_link_is_fatal_even_when_broker_id_is_known(self):
        self.known(OrderStatus.PARTIALLY_FILLED, "0.05")
        self.broker.executions = (replace(execution(), order_link_id="manual-link"),)
        self.assert_state(self.run_round(), RuntimeState.HALTED)

    def test_exact_execution_read_cannot_return_another_order(self):
        self.known(OrderStatus.PARTIALLY_FILLED, "0.05")
        self.broker.exact_executions = (execution(order_id="wrong-order"),)
        self.assert_state(self.run_round(), RuntimeState.HALTED)

    def test_order_amount_above_authorization_is_fatal(self):
        self.known()
        self.broker.order = replace(order(), requested_quantity=D("99"), remaining_quantity=D("99"))
        self.assert_state(self.run_round(), RuntimeState.HALTED)

    def test_wrong_caller_account_binding_label_halts(self):
        self.broker.account = replace(account(), account_id="another-profile")
        self.assert_state(self.run_round(), RuntimeState.HALTED)

    def test_round_budget_exhaustion_is_durable_and_blocks_later_reads(self):
        action = self.unknown()
        current = self.store.get_checkpoint()
        self.store.record_observation(replace(action, remaining_reconciliation_rounds=1),
                                      self.next_checkpoint(), expected_sequence=current.sequence)
        result = self.run_round()
        self.assert_state(result, RuntimeState.HALTED)
        self.assertEqual(result.placement.remaining_reconciliation_rounds, 0)
        count = len(self.broker.calls)
        self.assertEqual(self.run_round().checkpoint, result.checkpoint)
        self.assertEqual(len(self.broker.calls), count)

    def test_recovery_budget_is_reserved_durably_before_first_broker_call(self):
        self.unknown()
        read = self.broker.get_account_state

        def inspect_budget():
            saved = self.store.get_action(ACTION_ID)
            self.assertEqual((saved.remaining_reconciliation_rounds, saved.remaining_read_attempts), (4, 2))
            self.assertIs(self.store.get_checkpoint().snapshot.state, RuntimeState.UNCERTAIN)
            return read()

        with patch.object(self.broker, "get_account_state", side_effect=inspect_budget):
            self.run_round()

    def test_elapsed_timeout_after_a_read_blocks_all_following_reads(self):
        self.unknown()
        ticks = iter((1.0, 1.0, 602.0))
        dates = iter((utc(), utc(), utc(NOW_MS + 601000)))
        result = reconcile_startup(self.store, self.broker, utc_now=lambda: next(dates), monotonic=lambda: next(ticks))
        self.assert_state(result, RuntimeState.HALTED)
        self.assertEqual(len(self.broker.calls), 1)
        self.assertIs(result.checkpoint.snapshot.reason, RuntimeReason.RECOVERY_EXHAUSTED)

    def test_control_clock_drift_halts_before_broker_reads(self):
        self.unknown()
        ticks = iter((1.0, 4.0))
        result = reconcile_startup(self.store, self.broker, utc_now=lambda: utc(), monotonic=lambda: next(ticks))
        self.assert_state(result, RuntimeState.HALTED)
        self.assertIs(result.checkpoint.snapshot.reason, RuntimeReason.INVALID_CONFIGURATION)
        self.assertEqual(self.broker.calls, [])

    def test_non_utc_aware_timestamp_is_rejected(self):
        self.broker.account = replace(account(), fetched_at=utc().astimezone(timezone(timedelta(hours=9))))
        self.assert_state(self.run_round(), RuntimeState.HALTED)

    def test_execution_before_original_decision_availability_is_fatal(self):
        self.known(OrderStatus.FILLED, "0.05")
        self.broker.executions = (replace(execution(), executed_at=utc(HOUR - 1)),)
        self.assert_state(self.run_round(), RuntimeState.HALTED)

    def test_late_execution_read_failure_does_not_commit_partial_fill_evidence(self):
        self.known(OrderStatus.PARTIALLY_FILLED, "0.05")
        self.broker.executions = (execution(),)
        read = self.broker.get_executions

        def fail_exact(order_id=None, symbol=None):
            if order_id is not None:
                raise TimeoutError("synthetic-private-sdk-response")
            return read(order_id, symbol)

        with patch.object(self.broker, "get_executions", side_effect=fail_exact):
            self.assert_state(self.run_round(), RuntimeState.UNCERTAIN)
        self.assertEqual(self.store.list_fills(), ())

    def test_malformed_normalized_response_is_fatal_not_empty_success(self):
        self.broker.account = {"raw": "not-a-normalized-model"}
        self.assert_state(self.run_round(), RuntimeState.HALTED)

    def test_crash_between_cancel_and_parent_settlement_keeps_pending_work_recoverable(self):
        self.known()
        self.cancel_control()
        self.broker.order = order(OrderStatus.FILLED, quantity="0.05")
        self.broker.executions = (execution(),)
        original = self.store.record_observation

        def fail_parent(action, checkpoint, **kwargs):
            if action.kind == JournalActionKind.ENTRY and action.phase == ActionPhase.TERMINAL_CONFIRMED:
                raise RuntimeStoreError("Injected interruption")
            return original(action, checkpoint, **kwargs)

        with patch.object(self.store, "record_observation", side_effect=fail_parent), self.assertRaises(RuntimeStoreError):
            self.run_round()
        self.reopen()
        self.broker.store = self.store
        self.assertIs(self.store.get_checkpoint().snapshot.state, RuntimeState.UNCERTAIN)
        self.assertEqual(self.store.get_checkpoint().snapshot.pending_action.logical_action_id, ACTION_ID)
        self.assertIs(self.store.get_action("e" * 64).phase, ActionPhase.TERMINAL_CONFIRMED)
        self.assertEqual(self.store.list_fills(), ())
        self.assert_state(self.run_round(), RuntimeState.LONG, "0.04995")

    def test_execution_discovery_retains_broker_id_even_if_order_is_not_yet_visible(self):
        self.unknown()
        self.broker.executions = (execution(),)
        self.broker.errors["get_order"] = BrokerOrderNotFoundError("Unobserved")
        result = self.run_round()
        self.assert_state(result, RuntimeState.UNCERTAIN, "0")
        self.assertEqual(result.placement.broker_order_id, "order-1")
        self.assertIs(result.placement.phase, ActionPhase.UNKNOWN_OUTCOME)
        self.assertIsNone(result.placement.acknowledgement_broker_ms)
        self.assertEqual(self.store.list_fills(), ())
        self.reopen()
        self.assertEqual(self.store.get_action(ACTION_ID).broker_order_id, "order-1")

    def test_unsafe_external_status_diagnostic_does_not_become_a_known_status(self):
        self.known(OrderStatus.UNKNOWN)
        self.broker.order = replace(self.broker.order, external_status="synthetic private response with spaces")
        result = self.run_round()
        self.assert_state(result, RuntimeState.UNCERTAIN)
        self.assertEqual(result.placement.order_status, "UNKNOWN")
        self.assertIsNone(result.placement.external_status)
        self.assertNotIn("synthetic private", repr(result))

    def test_prepared_cancellation_is_abandoned_unsent_without_losing_control_id(self):
        self.known()
        cancel = ActionRecord("e" * 64, JournalActionKind.CANCEL, "BTCUSDT", HOUR + 600000, 5, 3,
                              control_id="operator-unsent", parent_action_id=ACTION_ID, target_broker_order_id="order-1")
        current = self.store.get_checkpoint()
        self.store.prepare_cancellation(cancel, self.next_checkpoint(), expected_sequence=current.sequence)
        result = self.run_round()
        self.assert_state(result, RuntimeState.ORDER_PENDING)
        self.assertIs(result.cancellation.phase, ActionPhase.ABANDONED_UNSENT)
        self.assertEqual(result.cancellation.control_id, "operator-unsent")
        self.assertEqual(result.cancellation.attempt_count, 0)

    def test_each_read_failure_stops_the_round_without_an_empty_fallback(self):
        for operation in ("get_account_state", "get_open_orders", "get_order", "get_executions"):
            with self.subTest(operation=operation):
                case = ReconciliationTests()
                case.setUp()
                try:
                    case.known()
                    case.broker.errors[operation] = ConnectionError("synthetic-private-sdk-error")
                    result = case.run_round()
                    case.assert_state(result, RuntimeState.UNCERTAIN, "0")
                    self.assertEqual([name for name, _ in case.broker.calls].count(operation), 1)
                    self.assertEqual(case.store.list_fills(), ())
                    self.assertIsNone(result.placement.terminal_at_ms)
                finally:
                    case.doCleanups()

    def test_broker_normalized_snapshots_are_not_modified(self):
        self.known(OrderStatus.PARTIALLY_FILLED, "0.05")
        self.broker.executions = (execution(),)
        before = (self.broker.account, self.broker.opens, self.broker.order, self.broker.executions)
        self.assert_state(self.run_round(), RuntimeState.ORDER_PENDING)
        self.assertEqual((self.broker.account, self.broker.opens, self.broker.order, self.broker.executions), before)

    def test_terminal_order_in_open_only_collection_is_a_malformed_read(self):
        self.known(OrderStatus.FILLED, "0.05")
        self.broker.opens = (self.broker.order,)
        self.broker.executions = (execution(),)
        self.assert_state(self.run_round(), RuntimeState.HALTED)
        self.assertEqual(self.store.list_fills(), ())

    def test_timeout_during_calculation_cannot_commit_confirmed_exposure(self):
        self.known(OrderStatus.FILLED, "0.05")
        self.broker.executions = (execution(),)
        clocks = {"utc": NOW_MS, "elapsed": 1.0}
        evaluate = module._evaluate

        def expire_after_evaluation(*args):
            result = evaluate(*args)
            clocks["utc"] += 601000
            clocks["elapsed"] += 601.0
            return result

        with patch.object(module, "_evaluate", side_effect=expire_after_evaluation):
            result = reconcile_startup(self.store, self.broker, utc_now=lambda: utc(clocks["utc"]),
                                       monotonic=lambda: clocks["elapsed"])
        self.assert_state(result, RuntimeState.HALTED, "0")
        self.assertEqual(self.store.list_fills(), ())
        self.assertIs(result.placement.phase, ActionPhase.ACKNOWLEDGED)
        self.assertEqual(result.checkpoint.halted_at_ms, NOW_MS + 601000)

    def test_missing_optional_link_for_known_order_is_uncertain_not_a_conflicting_identity(self):
        for missing in ("open", "execution"):
            with self.subTest(missing=missing):
                case = ReconciliationTests()
                case.setUp()
                try:
                    case.known(OrderStatus.PARTIALLY_FILLED, "0.05")
                    if missing == "open":
                        case.broker.opens = (replace(case.broker.order, order_link_id=None),)
                    else:
                        case.broker.executions = (replace(execution(), order_link_id=None),)
                    result = case.run_round()
                    case.assert_state(result, RuntimeState.UNCERTAIN, "0")
                    self.assertEqual(result.placement.broker_order_id, "order-1")
                    self.assertEqual(case.store.list_fills(), ())
                finally:
                    case.doCleanups()


if __name__ == "__main__":
    unittest.main()
