"""Offline proof of the adapter boundary, not a Stage 10.7 send workflow."""

from dataclasses import replace
import sqlite3
from unittest.mock import Mock, patch

import requests

from trading_lab.exchange.bybit_demo_orders import (
    BybitDemoActionError, BybitDemoConfigurationError, BybitDemoOrderAdapter,
)
from trading_lab.exchange.bybit_spot_rules import BybitSpotOrderConstraintError
from trading_lab.exchange.order_actions import SpotMarketOrderRequest
from trading_lab.runtime.planner import DecisionMode, plan_action
from trading_lab.runtime.store import ActionPhase, RuntimeStoreError
from tests.test_bybit_demo_orders import FakeActionSession, ack_response
from tests.test_runtime_planner import canonical, proposed_snapshot
from tests.test_runtime_store import HOUR, StoreCase, candle


class DurablePlacementBoundaryTests(StoreCase):
    def setUp(self):
        super().setUp()
        self.enterContext(patch.object(requests.Session, "send", side_effect=AssertionError("Offline only")))
        self.enterContext(patch.object(requests.Session, "request", side_effect=AssertionError("Offline only")))
        self.flat()
        current = self.store.get_checkpoint()
        self.store.save_checkpoint(self.next_checkpoint(last_reconciled_at_ms=HOUR, observed_at_ms=HOUR),
                                   expected_sequence=current.sequence)
        current = self.store.get_checkpoint()
        result = plan_action(self.config, current, canonical(), evaluated_at_ms=HOUR,
                             mode=DecisionMode.LIVE, action_history=self.store.list_actions())
        proposed = replace(current, sequence=current.sequence + 1, last_processed_candle_ms=0,
                           snapshot=proposed_snapshot(current.snapshot, result))
        self.store.commit_decision(candle(), result.decision, proposed,
                                   expected_sequence=current.sequence, action=result.action)
        self.action = result.action
        self.reopen()  # PREPARED must already exist on disk before adapter entry.
        self.session = FakeActionSession()
        self.session.placement = ack_response(link=self.action.order_link_id)
        self.adapter = BybitDemoOrderAdapter(self.session)
        self.request = SpotMarketOrderRequest(self.action.symbol, self.action.side,
                                              self.action.authorized_amount, self.action.amount_unit,
                                              self.action.order_link_id)

    def start_attempt(self):
        current = self.store.get_checkpoint()
        self.store.start_attempt(self.action.logical_action_id,
                                 replace(current, sequence=current.sequence + 1),
                                 expected_sequence=current.sequence)

    def assert_no_mutation(self):
        self.assertFalse(any(name in ("place_order", "cancel_order") for name, _ in self.session.calls))

    def test_attempt_is_committed_and_transaction_closed_before_fake_placement(self):
        current = self.store.get_checkpoint()
        callback = Mock(side_effect=self.start_attempt)
        original_place = self.session.place_order

        def place(**params):
            self.assertFalse(self.store._connection.in_transaction)
            action = self.store.get_action(self.action.logical_action_id)
            self.assertIs(action.phase, ActionPhase.ATTEMPT_STARTED)
            self.assertEqual(action.attempt_count, 1)
            self.assertIsNone(action.broker_order_id)
            self.assertIsNone(action.submitted_amount)
            # A separate connection sees the marker: this is committed SQLite
            # evidence, not merely the writer's uncommitted in-memory view.
            connection = sqlite3.connect(self.lock.database_path.as_uri() + "?mode=ro", uri=True)
            try:
                row = connection.execute(
                    "SELECT phase,attempt_count FROM actions WHERE logical_action_id=?",
                    (self.action.logical_action_id,),
                ).fetchone()
                self.assertEqual(row, ("ATTEMPT_STARTED", 1))
            finally:
                connection.close()
            return original_place(**params)

        with patch.object(self.session, "place_order", side_effect=place) as submit:
            receipt = self.adapter.place_market_order(self.request, before_submit=callback)
        callback.assert_called_once_with()
        submit.assert_called_once()
        self.assertEqual(receipt.order_link_id, self.action.order_link_id)
        self.assertEqual(self.store.get_checkpoint().snapshot, current.snapshot)
        self.reopen()
        saved = self.store.get_action(self.action.logical_action_id)
        self.assertIs(saved.phase, ActionPhase.ATTEMPT_STARTED)
        self.assertIsNone(saved.submitted_amount)  # Stage 9 never persists a receipt.

    def test_failed_attempt_commit_propagates_and_prevents_send(self):
        current = self.store.get_checkpoint()
        callback = Mock(side_effect=self.start_attempt)
        with patch.object(self.store, "_commit", side_effect=sqlite3.OperationalError("Synthetic commit fault")), \
             self.assertRaises(RuntimeStoreError):
            self.adapter.place_market_order(self.request, before_submit=callback)
        callback.assert_called_once_with()
        self.assert_no_mutation()
        self.assertEqual(self.store.get_checkpoint(), current)
        self.reopen()
        self.assertEqual(self.store.get_action(self.action.logical_action_id), self.action)
        self.assertIsNone(self.action.broker_order_id)

    def test_indeterminate_commit_prevents_send_and_preserves_attempt_on_reopen(self):
        original_commit = self.store._commit

        def commit_then_fail():
            original_commit()
            raise sqlite3.OperationalError("Synthetic post-commit fault")

        callback = Mock(side_effect=self.start_attempt)
        with patch.object(self.store, "_commit", side_effect=commit_then_fail), \
             self.assertRaises(RuntimeStoreError):
            self.adapter.place_market_order(self.request, before_submit=callback)
        callback.assert_called_once_with()
        self.assert_no_mutation()
        self.reopen()
        saved = self.store.get_action(self.action.logical_action_id)
        self.assertIs(saved.phase, ActionPhase.ATTEMPT_STARTED)
        self.assertEqual(saved.attempt_count, 1)
        self.assertIsNone(saved.broker_order_id)

    def test_safe_metadata_and_constraint_failures_leave_durable_prepared(self):
        current = self.store.get_checkpoint()
        for failure in ("metadata", "constraint"):
            self.session.errors.clear()
            if failure == "metadata":
                self.session.errors["get_instruments_info"] = TimeoutError("Synthetic metadata fault")
                error_type = BybitDemoActionError
            else:
                self.session.instrument["result"]["list"][0]["lotSizeFilter"]["minOrderAmt"] = "100"
                error_type = BybitSpotOrderConstraintError
            callback = Mock(side_effect=self.start_attempt)
            with self.subTest(failure=failure), self.assertRaises(error_type):
                self.adapter.place_market_order(self.request, before_submit=callback)
            callback.assert_not_called()
            self.assert_no_mutation()
            self.reopen()
            self.assertEqual(self.store.get_action(self.action.logical_action_id), self.action)
            self.assertEqual(self.store.get_checkpoint(), current)

    def test_post_callback_safety_refusal_retains_durable_attempt(self):
        def mark_then_change_session():
            self.start_attempt()
            self.session.demo = False

        callback = Mock(side_effect=mark_then_change_session)
        with self.assertRaises(BybitDemoConfigurationError):
            self.adapter.place_market_order(self.request, before_submit=callback)
        callback.assert_called_once_with()
        self.assert_no_mutation()
        self.reopen()
        saved = self.store.get_action(self.action.logical_action_id)
        self.assertIs(saved.phase, ActionPhase.ATTEMPT_STARTED)
        self.assertEqual(saved.attempt_count, 1)
        self.assertIsNone(saved.broker_order_id)
