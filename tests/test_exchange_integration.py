"""Stage 9.6: explicit cross-component sequences, never a trading runtime."""

import ast
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from dataclasses import FrozenInstanceError
from decimal import Decimal, localcontext
import inspect
from io import StringIO
import logging
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest
from unittest.mock import Mock, patch

from pybit.exceptions import FailedRequestError, InvalidRequestError
import requests

from trading_lab.exchange import (
    BrokerOrderNotFoundError, BybitDemoActionError, BybitDemoActionParseError,
    BybitDemoAmbiguousActionError, BybitDemoConfigurationError, BybitDemoCredentials,
    BybitDemoOrderAdapter, BybitDemoOrderRejectedError, BybitDemoReadError,
    BybitDemoReadOnlyAdapter, BybitDemoStateParseError, ExecutionState, OrderStatus,
    SpotMarketOrderRequest, create_bybit_demo_session,
    fetch_bybit_spot_instrument_rules, load_bybit_demo_credentials,
    normalize_spot_market_buy_quote_amount, normalize_spot_market_sell_base_quantity,
)
from trading_lab.exchange.bybit_spot_rules import BybitSpotOrderConstraintError
from tests.demo_broker_fixture import (
    ENVIRONMENT, PRIVATE_TEXT, SECRETS, IntegratedDemoSession, base_order,
    execution_response, fill, order_response, quote_order, with_private_extras,
)
from tests.test_bybit_demo_orders import ack_response
from tests.test_bybit_spot_rules import synthetic_response


def buy():
    return SpotMarketOrderRequest("BTCUSDT", "BUY", "12.34567899", "QUOTE", "caller-1")


def sell():
    return SpotMarketOrderRequest("BTCUSDT", "SELL", "0.1234569", "BASE", "caller-1")


class IntegrationCase(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(requests.Session, "send", side_effect=AssertionError("Offline only")))
        self.enterContext(patch.object(requests.Session, "request", side_effect=AssertionError("Offline only")))
        self.session = self.make_session()
        self.reads = BybitDemoReadOnlyAdapter(self.session)
        self.actions = BybitDemoOrderAdapter(self.session)

    def make_session(self):
        with patch("trading_lab.exchange.bybit_demo.HTTP", side_effect=IntegratedDemoSession):
            return create_bybit_demo_session(load_bybit_demo_credentials(ENVIRONMENT))

    def assert_private_absent(self, *values):
        for value in values:
            for secret in SECRETS:
                self.assertNotIn(secret, str(value))
                self.assertNotIn(secret, repr(value))


class LifecycleIntegrationTests(IntegrationCase):
    def test_factory_credentials_and_adapter_construction_compose_without_io(self):
        self.assertEqual(self.session.calls, [])
        self.assertEqual((self.session.api_key, self.session.api_secret), SECRETS[:2])
        self.assertIs(self.session.demo, True)
        self.assertIs(self.session.testnet, False)
        self.assertEqual(self.session.endpoint, "https://api-demo.bybit.com")
        self.assertEqual((self.session.force_retry, self.session.max_retries,
                          self.session.retry_delay, self.session.log_requests), (False, 1, 0, False))

    def test_buy_authorization_normalization_acknowledgement_order_and_fills(self):
        rules = fetch_bybit_spot_instrument_rules(self.session, "BTCUSDT")
        normalized = normalize_spot_market_buy_quote_amount(rules, buy().authorized_amount)
        receipt = self.actions.place_market_order(buy())
        self.assertEqual(self.session.mutation_calls(), [("place_order", {
            "category": "spot", "symbol": "BTCUSDT", "side": "Buy", "orderType": "Market",
            "qty": normalized, "marketUnit": "quoteCoin", "isLeverage": 0, "orderLinkId": "caller-1",
        })])
        self.assertEqual(self.session.calls[-2][0], "get_instruments_info")
        self.assertEqual(receipt.submitted_amount, Decimal("12.3456789"))
        self.assertFalse(hasattr(receipt, "filled_quantity"))
        self.assertFalse(any(name in {"get_open_orders", "get_executions"} for name, _ in self.session.calls))
        self.session.realtime = [order_response([quote_order()])]
        self.session.executions = [execution_response([fill()])]
        state = self.reads.get_order(receipt.broker_order_id)
        (execution,) = self.reads.get_executions(receipt.broker_order_id, receipt.symbol)
        self.assertIs(state.status, OrderStatus.FILLED)
        self.assertEqual((state.quantity_unit, state.requested_quantity,
                          state.filled_quantity, state.remaining_quantity),
                         ("QUOTE", Decimal("12.3456789"), Decimal("12.3"), Decimal("0.0456789")))
        self.assertEqual(state.filled_base_quantity, Decimal("0.0015"))
        self.assertIsInstance(execution, ExecutionState)
        self.assertIsNot(receipt, execution)
        self.assertEqual(execution.broker_order_id, receipt.broker_order_id)
        self.assertEqual(execution.executed_quantity, Decimal("0.0015"))
        self.assertEqual((execution.execution_fee, execution.fee_currency), (Decimal("0.0000015"), "BTC"))
        self.assertEqual(len(self.session.mutation_calls()), 1)

    def test_sell_authorized_base_reaches_broker_and_separate_fill_read(self):
        rules = fetch_bybit_spot_instrument_rules(self.session, "BTCUSDT")
        normalized = normalize_spot_market_sell_base_quantity(rules, sell().authorized_amount)
        receipt = self.actions.place_market_order(sell())
        self.assertEqual(self.session.mutation_calls()[0][1], {
            "category": "spot", "symbol": "BTCUSDT", "side": "Sell", "orderType": "Market",
            "qty": normalized, "marketUnit": "baseCoin", "isLeverage": 0, "orderLinkId": "caller-1",
        })
        self.session.realtime = [order_response([base_order()])]
        self.session.executions = [execution_response([fill(side="Sell", quantity="0.123456",
                                                            price="1000", fee="0.123456", currency="USDT")])]
        state = self.reads.get_order(receipt.broker_order_id)
        (execution,) = self.reads.get_executions(receipt.broker_order_id, receipt.symbol)
        self.assertEqual((receipt.amount_unit, receipt.submitted_amount), ("BASE", Decimal("0.123456")))
        self.assertEqual((state.quantity_unit, state.remaining_quantity), ("BASE", Decimal("0")))
        self.assertEqual(execution.executed_quantity, receipt.submitted_amount)
        self.assertEqual(execution.fee_currency, "USDT")
        self.assertFalse(any(name == "get_wallet_balance" for name, _ in self.session.calls))

    def test_cancellation_receipt_does_not_choose_subsequent_order_status(self):
        cases = (("Cancelled", "0", "0", OrderStatus.CANCELLED),
                 ("Filled", "0.0015", "12.3", OrderStatus.FILLED),
                 ("PartiallyFilled", "0.001", "8.2", OrderStatus.PARTIALLY_FILLED),
                 ("FutureStatus", "0.001", "8.2", OrderStatus.UNKNOWN))
        for external, base, quote, expected in cases:
            with self.subTest(status=external):
                session = self.make_session()
                actions, reads = BybitDemoOrderAdapter(session), BybitDemoReadOnlyAdapter(session)
                placement = actions.place_market_order(buy())
                session.realtime = [order_response([quote_order("PartiallyFilled", filled_base="0.001", filled_quote="8.2")])]
                previous = reads.get_order(placement.broker_order_id)
                before = deepcopy(previous)
                cancellation = actions.cancel_order(placement.symbol, placement.broker_order_id)
                self.assertEqual(session.mutation_calls()[-1], ("cancel_order", {
                    "category": "spot", "symbol": "BTCUSDT", "orderId": placement.broker_order_id,
                }))
                self.assertFalse(hasattr(cancellation, "status"))
                self.assertEqual(previous, before)
                session.realtime = [order_response([quote_order(external, filled_base=base, filled_quote=quote)])]
                observed = reads.get_order(cancellation.broker_order_id)
                self.assertIs(observed.status, expected)
                self.assertIs(previous.status, OrderStatus.PARTIALLY_FILLED)
                self.assertFalse(hasattr(placement, "status"))

    def test_partial_quote_fill_multiple_executions_then_explicit_final_observation(self):
        receipt = self.actions.place_market_order(buy())
        self.session.realtime = [order_response([quote_order("PartiallyFilled", filled_base="0.001", filled_quote="8.2")])]
        partial = self.reads.get_order(receipt.broker_order_id)
        self.session.executions = [execution_response([
            fill("one", quantity="0.0004", fee="0.0000004"),
            fill("two", quantity="0.0006", fee="-0.0000001", currency=None),
        ])]
        executions = self.reads.get_executions(receipt.broker_order_id)
        self.assertEqual([x.broker_execution_id for x in executions], ["one", "two"])
        self.assertEqual([x.execution_fee for x in executions], [Decimal("0.0000004"), Decimal("-0.0000001")])
        self.assertIsNone(executions[1].fee_currency)
        self.assertIs(partial.status, OrderStatus.PARTIALLY_FILLED)
        self.session.realtime = [order_response([quote_order()])]
        self.assertIs(self.reads.get_order(receipt.broker_order_id).status, OrderStatus.FILLED)
        self.assertIs(partial.status, OrderStatus.PARTIALLY_FILLED)
        self.assertFalse(hasattr(receipt, "status"))
        self.assertEqual(len(self.session.mutation_calls()), 1)

    def test_partial_base_fill_can_later_be_cancelled_without_invented_remainder_fill(self):
        receipt = self.actions.place_market_order(sell())
        self.session.realtime = [order_response([base_order("PartiallyFilled", filled="0.1", quote="100")])]
        partial = self.reads.get_order(receipt.broker_order_id)
        self.actions.cancel_order(receipt.symbol, receipt.broker_order_id)
        self.session.realtime = [order_response([base_order("PartiallyFilledCanceled", filled="0.1", quote="100")])]
        observed = self.reads.get_order(receipt.broker_order_id)
        self.assertIs(observed.status, OrderStatus.CANCELLED)
        self.assertEqual(observed.remaining_quantity, Decimal("0.023456"))
        self.assertIs(partial.status, OrderStatus.PARTIALLY_FILLED)
        self.assertEqual(self.reads.get_executions(receipt.broker_order_id), ())

    def test_filled_order_and_empty_execution_window_do_not_fabricate_execution(self):
        receipt = self.actions.place_market_order(buy())
        self.session.realtime = [order_response([quote_order()])]
        self.assertIs(self.reads.get_order(receipt.broker_order_id).status, OrderStatus.FILLED)
        self.assertEqual(self.reads.get_executions(receipt.broker_order_id), ())
        self.assertFalse(hasattr(receipt, "execution_price"))

    def test_accepted_but_unobserved_order_remains_unknown_without_resend(self):
        receipt = self.actions.place_market_order(buy())
        with self.assertRaises(BrokerOrderNotFoundError):
            self.reads.get_order(receipt.broker_order_id)
        self.assertEqual([name for name, _ in self.session.calls],
                         ["get_instruments_info", "place_order", "get_open_orders", "get_order_history"])
        self.assertEqual(len(self.session.mutation_calls()), 1)
        self.assertFalse(hasattr(receipt, "status"))

    def test_accepted_order_can_be_observed_by_exact_id_history_fallback(self):
        receipt = self.actions.place_market_order(buy())
        self.session.history = order_response([quote_order()])
        state = self.reads.get_order(receipt.broker_order_id)
        self.assertIs(state.status, OrderStatus.FILLED)
        self.assertEqual(self.session.calls[-2:], [
            ("get_open_orders", {"category": "spot", "orderId": receipt.broker_order_id}),
            ("get_order_history", {"category": "spot", "orderId": receipt.broker_order_id}),
        ])
        self.assertEqual(len(self.session.mutation_calls()), 1)

    def test_paginated_open_orders_preserve_units_after_an_explicit_placement(self):
        receipt = self.actions.place_market_order(buy())
        first = quote_order("New", filled_base="0", filled_quote="0")
        second = base_order("New", filled="0", quote="0")
        second["orderId"] = "other-order"
        self.session.realtime = [order_response([first], "next"), order_response([second])]
        orders = self.reads.get_open_orders(receipt.symbol)
        self.assertEqual([x.broker_order_id for x in orders], [receipt.broker_order_id, "other-order"])
        self.assertEqual([x.quantity_unit for x in orders], ["QUOTE", "BASE"])
        self.assertEqual(self.session.calls[-1][1], {"category": "spot", "openOnly": 0,
                                                   "limit": 50, "symbol": "BTCUSDT", "cursor": "next"})
        self.assertEqual(len(self.session.mutation_calls()), 1)

    def test_unexpected_external_status_is_preserved_after_accepted_placement(self):
        receipt = self.actions.place_market_order(buy())
        self.session.realtime = [order_response([quote_order("UnexpectedStatus", filled_base="0", filled_quote="0")])]
        state = self.reads.get_order(receipt.broker_order_id)
        self.assertIs(state.status, OrderStatus.UNKNOWN)
        self.assertEqual(state.external_status, "UnexpectedStatus")

    def test_timeout_reset_and_sdk_failure_remain_single_attempt_ambiguity(self):
        for error in (requests.exceptions.ReadTimeout(PRIVATE_TEXT), ConnectionResetError(PRIVATE_TEXT),
                      FailedRequestError(PRIVATE_TEXT, PRIVATE_TEXT, 400, "offline", {"auth": PRIVATE_TEXT})):
            self.session.calls.clear()
            self.session.errors["place_order"] = error
            with self.subTest(kind=type(error).__name__), self.assertRaises(BybitDemoAmbiguousActionError) as caught:
                self.actions.place_market_order(buy())
            self.assert_private_absent(caught.exception)
            self.assertNotIsInstance(caught.exception, BybitDemoOrderRejectedError)
            self.assertEqual([name for name, _ in self.session.calls], ["get_instruments_info", "place_order"])
            self.assertEqual(self.session.mutation_calls()[0][1]["orderLinkId"], "caller-1")

    def test_explicit_later_read_can_observe_order_after_ambiguous_placement(self):
        self.session.errors["place_order"] = TimeoutError(PRIVATE_TEXT)
        with self.assertRaises(BybitDemoAmbiguousActionError):
            self.actions.place_market_order(buy())
        # Operator supplies a broker ID learned separately; no automatic lookup.
        self.session.realtime = [order_response([quote_order()])]
        state = self.reads.get_order("order-1")
        self.assertEqual(state.order_link_id, "caller-1")
        self.assertIs(state.status, OrderStatus.FILLED)
        self.assertEqual(len(self.session.mutation_calls()), 1)

    def test_confirmed_rejection_has_no_invented_state_or_wallet_change(self):
        account = self.reads.get_account_state()
        wallet = deepcopy(self.session.wallet)
        self.session.calls.clear()
        self.session.placement = {"retCode": 10001, "retMsg": PRIVATE_TEXT}
        with self.assertRaises(BybitDemoOrderRejectedError) as caught:
            self.actions.place_market_order(buy())
        self.assertEqual(caught.exception.ret_code, 10001)
        self.assert_private_absent(caught.exception)
        self.assertEqual([name for name, _ in self.session.calls], ["get_instruments_info", "place_order"])
        self.assertEqual(self.session.wallet, wallet)
        self.assertEqual(account.total_equity, Decimal("1001.25"))

    def test_sdk_confirmed_rejection_is_not_ambiguous(self):
        self.session.errors["place_order"] = InvalidRequestError(PRIVATE_TEXT, PRIVATE_TEXT, 10001, "offline", {"auth": PRIVATE_TEXT})
        with self.assertRaises(BybitDemoOrderRejectedError) as caught:
            self.actions.place_market_order(buy())
        self.assert_private_absent(caught.exception)
        self.assertEqual(len(self.session.mutation_calls()), 1)

    def test_malformed_placement_acknowledgement_never_creates_fill_or_retry(self):
        self.session.placement = {"retCode": 0, "result": {}, "time": 1760000000200}
        with self.assertRaises(BybitDemoActionParseError):
            self.actions.place_market_order(buy())
        self.assertEqual([name for name, _ in self.session.calls], ["get_instruments_info", "place_order"])

    def test_preflight_failures_prevent_mutation_through_composed_components(self):
        for case in ("not-trading", "malformed-rules", "buy-minimum", "sell-maximum", "invalid-amount", "unsafe-unit"):
            session = self.make_session()
            actions = BybitDemoOrderAdapter(session)
            request = buy()
            if case == "not-trading":
                session.instrument["result"]["list"][0]["status"] = "Settled"
            elif case == "malformed-rules":
                del session.instrument["result"]["list"][0]["lotSizeFilter"]["quotePrecision"]
            elif case == "buy-minimum":
                request = SpotMarketOrderRequest("BTCUSDT", "BUY", "1", "QUOTE", "caller-1")
            elif case == "sell-maximum":
                request = SpotMarketOrderRequest("BTCUSDT", "SELL", "100", "BASE", "caller-1")
            elif case == "invalid-amount":
                request = SpotMarketOrderRequest("BTCUSDT", "BUY", float("nan"), "QUOTE", "caller-1")
            else:
                request = SpotMarketOrderRequest("BTCUSDT", "BUY", "10", "BASE", "caller-1")
            with self.subTest(case=case), self.assertRaises((BybitDemoActionError, BybitSpotOrderConstraintError, ValueError)):
                actions.place_market_order(request)
            self.assertEqual(session.mutation_calls(), [])

    def test_read_wallet_changes_cannot_resize_fixed_authorization(self):
        request = buy()
        for balance in ("0", "1000000"):
            self.session.wallet["result"]["list"][0]["totalAvailableBalance"] = balance
            self.assertEqual(self.reads.get_account_state().available_balance, Decimal(balance))
            self.actions.place_market_order(request)
        self.assertEqual([params["qty"] for _, params in self.session.mutation_calls()], ["12.3456789"] * 2)
        self.assertEqual(request, buy())

    def test_fresh_metadata_rechecks_constraints_after_explicit_account_read(self):
        self.reads.get_account_state()
        self.actions.place_market_order(buy())
        self.session.instrument["result"]["list"][0]["lotSizeFilter"]["minOrderAmt"] = "100"
        with self.assertRaises(BybitSpotOrderConstraintError):
            self.actions.place_market_order(buy())
        self.assertEqual(len(self.session.mutation_calls()), 1)
        self.assertEqual(sum(name == "get_instruments_info" for name, _ in self.session.calls), 2)

    def test_tiny_decimal_context_preserves_authorization_and_order_dimensions(self):
        with localcontext() as context:
            context.prec = 2
            receipt = self.actions.place_market_order(buy())
            self.session.realtime = [order_response([quote_order()])]
            state = self.reads.get_order(receipt.broker_order_id)
        self.assertEqual(receipt.submitted_amount, Decimal("12.3456789"))
        self.assertEqual(state.remaining_quantity, Decimal("0.0456789"))

    def test_multiple_execution_pages_are_consumed_after_explicit_placement(self):
        receipt = self.actions.place_market_order(buy())
        self.session.executions = [execution_response([fill("one")], "next"), execution_response([fill("two")])]
        executions = self.reads.get_executions(receipt.broker_order_id, receipt.symbol)
        self.assertEqual([x.broker_execution_id for x in executions], ["one", "two"])
        self.assertEqual(self.session.calls[-1][1], {"category": "spot", "execType": "Trade", "limit": 100,
                                                   "orderId": "order-1", "symbol": "BTCUSDT", "cursor": "next"})
        self.assertEqual(len(self.session.mutation_calls()), 1)

    def test_late_fill_page_failure_preserves_acknowledgement_and_prior_order(self):
        receipt = self.actions.place_market_order(buy())
        self.session.realtime = [order_response([quote_order()])]
        previous = self.reads.get_order(receipt.broker_order_id)
        self.session.executions = [execution_response([fill()], "next"), {"retCode": 0, "result": None}]
        with self.assertRaises(BybitDemoStateParseError):
            self.reads.get_executions(receipt.broker_order_id)
        self.assertIs(previous.status, OrderStatus.FILLED)
        self.assertEqual(receipt.submitted_amount, Decimal("12.3456789"))
        with self.assertRaises(FrozenInstanceError):
            receipt.submitted_amount = Decimal("0")
        self.assertEqual(len(self.session.mutation_calls()), 1)


class SafetyIntegrationTests(IntegrationCase):
    def test_shared_session_unsafe_settings_block_every_authenticated_read_and_action(self):
        settings = (("testnet", True), ("demo", False), ("endpoint", "https://api.bybit.com"),
                    ("endpoint", "https://unexpected.invalid"), ("force_retry", True),
                    ("max_retries", 2), ("retry_delay", 1), ("log_requests", True),
                    ("testnet", 0), ("demo", 1), ("max_retries", True), ("max_retries", None),
                    ("endpoint", None), ("log_requests", 0))
        for field, value in settings:
            session = self.make_session()
            reads, actions = BybitDemoReadOnlyAdapter(session), BybitDemoOrderAdapter(session)
            setattr(session, field, value)
            operations = (reads.get_account_state, reads.get_open_orders,
                          lambda: reads.get_order("order-1"), reads.get_executions,
                          lambda: actions.place_market_order(buy()),
                          lambda: actions.cancel_order("BTCUSDT", "order-1"))
            for operation in operations:
                with self.subTest(field=field, value=value), self.assertRaises((BybitDemoReadError, BybitDemoConfigurationError)):
                    operation()
            self.assertEqual(session.calls, [])

    def test_routing_change_during_preflight_blocks_mutation_after_successful_read(self):
        self.reads.get_account_state()
        def metadata(**kwargs):
            self.session.endpoint = "https://api.bybit.com"
            return synthetic_response()
        with patch.object(self.session, "get_instruments_info", side_effect=metadata):
            with self.assertRaises(BybitDemoConfigurationError):
                self.actions.place_market_order(buy())
        self.assertEqual(self.session.mutation_calls(), [])
        with self.assertRaises(BybitDemoReadError):
            self.reads.get_executions()

    def test_routing_change_between_fill_pages_fails_without_partial_success(self):
        receipt = self.actions.place_market_order(buy())
        def page(**kwargs):
            self.session.demo = False
            return execution_response([fill()], "next")
        with patch.object(self.session, "get_executions", side_effect=page) as fetch:
            with self.assertRaises(BybitDemoReadError):
                self.reads.get_executions(receipt.broker_order_id)
            fetch.assert_called_once()
        self.assertEqual(len(self.session.mutation_calls()), 1)

    def test_read_and_mutation_dispatch_allowlists_remain_exact(self):
        import trading_lab.exchange.bybit_demo_orders as actions
        import trading_lab.exchange.bybit_demo_read_only as reads
        self.assertEqual(actions._MUTATION_METHODS, frozenset({"place_order", "cancel_order"}))
        self.assertEqual(reads._READ_METHODS, frozenset({"get_wallet_balance", "get_open_orders", "get_order_history", "get_executions"}))
        forbidden = ("amend_order", "replace_order", "place_batch_order", "cancel_batch_order",
                     "cancel_all_orders", "transfer", "set_leverage", "withdraw", "set_account_type")
        for name in forbidden:
            with self.subTest(method=name), self.assertRaises(BybitDemoActionError):
                self.actions._mutate(name)
            with self.assertRaises(BybitDemoReadError):
                self.reads._read(name)
        self.assertEqual(self.session.calls, [])

    def test_all_exchange_sources_have_no_runtime_or_strategy_backtest_coupling(self):
        directory = Path(__file__).resolve().parents[1] / "src/trading_lab/exchange"
        forbidden = {"amend_order", "replace_order", "place_batch_order", "cancel_batch_order",
                     "cancel_all_orders", "transfer", "set_leverage", "withdraw", "set_account_type"}
        for path in directory.glob("*.py"):
            tree = ast.parse(path.read_text())
            imports = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
            imports += [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
            self.assertFalse(any(any(part in name.split(".") for part in
                                    ("strategies", "backtest", "risk", "execution", "database", "asyncio", "schedule")) for name in imports), path.name)
            self.assertFalse(any(isinstance(n, (ast.While, ast.AsyncFunctionDef)) for n in ast.walk(tree)), path.name)
            self.assertFalse(any(isinstance(n, ast.Attribute) and n.attr in forbidden for n in ast.walk(tree)), path.name)
            for n in ast.walk(tree):
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "_mutate":
                    self.assertIsInstance(n.args[0], ast.Constant)
                    self.assertIn(n.args[0].value, {"place_order", "cancel_order"})
        self.assertEqual({name for name, value in inspect.getmembers(BybitDemoReadOnlyAdapter, inspect.isfunction) if not name.startswith("_")},
                         {"get_account_state", "get_open_orders", "get_order", "get_executions"})

    def test_fresh_exchange_and_smoke_imports_do_not_read_credentials_or_construct_clients(self):
        script = textwrap.dedent('''
            import importlib, os
            from unittest.mock import patch
            import requests, pybit.unified_trading
            class NoEnvironment(dict):
                def get(self, *args): raise AssertionError('No credentials on import')
                def __getitem__(self, *args): raise AssertionError('No credentials on import')
            with patch('os.environ', NoEnvironment()), \
                 patch('pybit.unified_trading.HTTP', side_effect=AssertionError('No clients')), \
                 patch.object(requests.Session, 'send', side_effect=AssertionError('No network')), \
                 patch.object(requests.Session, 'request', side_effect=AssertionError('No network')):
                for name in ('trading_lab.exchange', 'trading_lab.exchange.bybit_demo',
                             'trading_lab.exchange.bybit_spot_rules', 'trading_lab.exchange.account_state',
                             'trading_lab.exchange.bybit_demo_read_only', 'trading_lab.exchange.order_actions',
                             'trading_lab.exchange.bybit_demo_orders', 'trading_lab.exchange.bybit_market_data',
                             'scripts.bybit_demo_smoke'):
                    importlib.import_module(name)
        ''')
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run([sys.executable, "-c", script], cwd=root,
                                env={"PYTHONPATH": str(root / "src"), "PYTHONDONTWRITEBYTECODE": "1"},
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((result.stdout, result.stderr), ("", ""))

    def test_raw_authenticated_extras_do_not_escape_returned_models(self):
        self.session.wallet = with_private_extras(self.session.wallet)
        self.session.placement = with_private_extras(self.session.placement)
        self.session.cancellation = with_private_extras(self.session.cancellation)
        self.session.realtime = [with_private_extras(order_response([quote_order()]))]
        self.session.executions = [with_private_extras(execution_response([fill()]))]
        output, errors = StringIO(), StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            account = self.reads.get_account_state()
            receipt = self.actions.place_market_order(buy())
            cancellation = self.actions.cancel_order(receipt.symbol, receipt.broker_order_id)
            state = self.reads.get_order(receipt.broker_order_id)
            executions = self.reads.get_executions(receipt.broker_order_id)
        self.assert_private_absent(load_bybit_demo_credentials(ENVIRONMENT), account, receipt, cancellation,
                                   state, executions, self.actions, self.reads, output.getvalue(), errors.getvalue())

    def test_authenticated_sdk_exception_text_is_suppressed_across_reads_and_actions(self):
        for method, operation in (
            ("get_wallet_balance", self.reads.get_account_state),
            ("get_open_orders", self.reads.get_open_orders),
            ("get_executions", self.reads.get_executions),
            ("place_order", lambda: self.actions.place_market_order(buy())),
            ("cancel_order", lambda: self.actions.cancel_order("BTCUSDT", "order-1")),
        ):
            self.session.errors = {method: RuntimeError(PRIVATE_TEXT)}
            output, errors = StringIO(), StringIO()
            with redirect_stdout(output), redirect_stderr(errors), self.assertRaises((BybitDemoReadError, BybitDemoAmbiguousActionError)) as caught:
                operation()
            self.assertTrue(caught.exception.__suppress_context__)
            self.assert_private_absent(caught.exception, output.getvalue(), errors.getvalue())

    def test_metadata_sdk_error_is_sanitized_before_any_action(self):
        self.session.errors["get_instruments_info"] = RuntimeError(PRIVATE_TEXT)
        with self.assertRaises(BybitDemoActionError) as caught:
            self.actions.place_market_order(buy())
        self.assert_private_absent(caught.exception)
        self.assertEqual(self.session.mutation_calls(), [])


class SDKDiagnosticIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(requests.Session, "send", side_effect=AssertionError("Offline only")))
        self.enterContext(patch.object(requests.Session, "request", side_effect=AssertionError("Offline only")))

    def test_actual_sdk_retryable_error_diagnostics_cannot_expose_private_message(self):
        # Request logging=False does NOT mute pybit's raw retMsg error logs.
        # Exercise the real SDK handler, rather than mocking logger.error itself.
        session = create_bybit_demo_session(BybitDemoCredentials(*SECRETS[:2]))
        self.addCleanup(session.client.close)
        self.addCleanup(session.logger.setLevel, session.logger.level)
        session.logger.setLevel(logging.DEBUG)
        response = Mock(status_code=200, headers={"Authorization": SECRETS[3]}, url="https://api-demo.bybit.com")
        response.json.return_value = {"retCode": 10002, "retMsg": PRIVATE_TEXT}
        reads, actions = BybitDemoReadOnlyAdapter(session), BybitDemoOrderAdapter(session)
        operations = (reads.get_account_state, lambda: actions.place_market_order(buy()),
                      lambda: actions.cancel_order("BTCUSDT", "order-1"))
        for operation in operations:
            logs, output, errors = StringIO(), StringIO(), StringIO()
            with patch.object(session, "get_instruments_info", return_value=synthetic_response()), \
                 patch.object(session.client, "send", return_value=response) as send, \
                 patch.object(session.logger, "handlers", [logging.StreamHandler(logs)]), \
                 patch("pybit._http_manager.time.sleep"), redirect_stdout(output), redirect_stderr(errors):
                with self.assertRaises((BybitDemoReadError, BybitDemoAmbiguousActionError)) as caught:
                    operation()
                send.assert_called_once()
            for secret in SECRETS:
                self.assertNotIn(secret, str(caught.exception))
                self.assertNotIn(secret, repr(caught.exception))
                self.assertNotIn(secret, logs.getvalue() + output.getvalue() + errors.getvalue())
            self.assertEqual(logs.getvalue(), "")

    def test_actual_sdk_http_failure_debug_response_is_not_logged(self):
        session = create_bybit_demo_session(BybitDemoCredentials(*SECRETS[:2]))
        self.addCleanup(session.client.close)
        response = Mock(status_code=403, headers={"Authorization": SECRETS[3]}, text=PRIVATE_TEXT)
        logs = StringIO()
        self.addCleanup(session.logger.setLevel, session.logger.level)
        session.logger.setLevel(logging.DEBUG)
        with patch.object(session.client, "send", return_value=response) as send, \
             patch.object(session.logger, "handlers", [logging.StreamHandler(logs)]):
            with self.assertRaises(BybitDemoReadError) as caught:
                BybitDemoReadOnlyAdapter(session).get_account_state()
        self.assertEqual(logs.getvalue(), "")
        send.assert_called_once()
        for secret in SECRETS:
            self.assertNotIn(secret, str(caught.exception))

    def test_diagnostic_suppression_is_per_client_not_a_global_logger_change(self):
        shared = logging.getLogger("pybit._http_manager")
        before = (shared.disabled, shared.level, shared.propagate, tuple(shared.handlers))
        # pybit itself adds shared handlers when root has none. Supply a handler
        # to isolate our per-client muting from that unchanged SDK setup behavior.
        with patch.object(logging.getLogger(), "handlers", [logging.NullHandler()]):
            first = create_bybit_demo_session(BybitDemoCredentials(*SECRETS[:2]))
            second = create_bybit_demo_session(BybitDemoCredentials(*SECRETS[:2]))
        self.addCleanup(first.client.close)
        self.addCleanup(second.client.close)
        self.assertIsNot(first.logger, shared)
        self.assertIsNot(first.logger, second.logger)
        self.assertIs(first.logger.disabled, True)
        self.assertIs(second.logger.disabled, True)
        self.assertEqual((shared.disabled, shared.level, shared.propagate, tuple(shared.handlers)), before)


if __name__ == "__main__":
    unittest.main()
