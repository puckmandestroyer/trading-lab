"""Synthetic, fully offline account/order/fill and mutation-boundary checks."""

import ast
from copy import deepcopy
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_UP, localcontext
import inspect
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest
from unittest.mock import patch

import requests

from trading_lab.exchange import (
    AccountState, BrokerOrderNotFoundError, BybitDemoReadError,
    BybitDemoReadOnlyAdapter, BybitDemoStateParseError, CurrencyBalance,
    ExecutionState, OrderState, OrderStatus, ReadOnlyBroker,
)


SERVER_TIME = 1760000000200


def wallet_response():
    return {
        "retCode": 0, "time": SERVER_TIME,
        "result": {"list": [{
            "accountType": "UNIFIED", "totalAvailableBalance": "900.125",
            "totalWalletBalance": "1000.125", "totalEquity": "1001.25",
            "coin": [
                {"coin": "USDT", "walletBalance": "800.125", "equity": "800.125", "locked": "100"},
                {"coin": "BTC", "walletBalance": "0.002", "equity": "0.002", "locked": "0"},
            ],
        }]},
    }


def order_record(order_id="order-1", status="New", filled="0"):
    return {
        "orderId": order_id, "symbol": "BTCUSDT", "side": "Sell",
        "orderType": "Market", "orderStatus": status, "marketUnit": "baseCoin",
        "isLeverage": "0", "qty": "2", "cumExecQty": filled,
        "cumExecValue": str(Decimal(filled) * 100),
        "avgPrice": "100" if Decimal(filled) > 0 else "",
        "price": "0", "triggerPrice": "0",
        "createdTime": "1760000000001", "updatedTime": "1760000000123",
    }


def order_response(records=(), cursor=""):
    return {
        "retCode": 0, "time": SERVER_TIME,
        "result": {"category": "spot", "list": list(records), "nextPageCursor": cursor},
    }


def execution_record(execution_id="fill-1", order_id="order-1"):
    return {
        "execId": execution_id, "orderId": order_id, "orderLinkId": "caller-1",
        "symbol": "BTCUSDT", "side": "Buy", "execType": "Trade",
        "execQty": "0.002", "execPrice": "50000.125", "execFee": "0.000002",
        "feeCurrency": "BTC", "execTime": "1760000000123",
    }


def execution_response(records=(), cursor=""):
    return order_response(records, cursor)


class FakeDemoSession:
    testnet = False
    demo = True
    endpoint = "https://api-demo.bybit.com"
    force_retry = False
    max_retries = 1
    retry_delay = 0
    log_requests = False

    def __init__(self):
        self.wallet = wallet_response()
        self.realtime = [order_response()]
        self.history = order_response()
        self.executions = [execution_response()]
        self.errors = {}
        self.calls = []
        self.mutations = 0

    def _invoke(self, method, kwargs, response):
        self.calls.append((method, kwargs))
        if method in self.errors:
            raise self.errors[method]
        return deepcopy(response)

    def get_wallet_balance(self, **kwargs):
        return self._invoke("get_wallet_balance", kwargs, self.wallet)

    def get_open_orders(self, **kwargs):
        response = self.realtime[0]
        if len(self.realtime) > 1:
            self.realtime = self.realtime[1:]
        return self._invoke("get_open_orders", kwargs, response)

    def get_order_history(self, **kwargs):
        return self._invoke("get_order_history", kwargs, self.history)

    def get_executions(self, **kwargs):
        response = self.executions[0]
        if len(self.executions) > 1:
            self.executions = self.executions[1:]
        return self._invoke("get_executions", kwargs, response)

    def _mutation(self, **kwargs):
        self.mutations += 1
        raise AssertionError("Mutation endpoints must never be reached")

    place_order = cancel_order = amend_order = cancel_all_orders = _mutation
    submit_order = create_order = replace_order = modify_order = _mutation
    batch_place_order = batch_cancel_order = batch_amend_order = _mutation

    def __repr__(self):
        raise AssertionError("Client repr must never be used")


class OfflineTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(requests.Session, "send", side_effect=AssertionError("No network")))
        self.enterContext(patch.object(requests.Session, "request", side_effect=AssertionError("No network")))
        self.session = FakeDemoSession()
        self.adapter = BybitDemoReadOnlyAdapter(self.session, account_id="research-demo")


class AccountTests(OfflineTests):
    def test_valid_account_normalizes_usd_aggregates_and_individual_coins(self):
        before = datetime.now(timezone.utc)
        state = self.adapter.get_account_state()
        after = datetime.now(timezone.utc)
        self.assertIsInstance(state, AccountState)
        self.assertEqual((state.broker_id, state.account_id, state.currency), ("bybit-demo", "research-demo", "USD"))
        self.assertEqual(state.available_balance, Decimal("900.125"))
        self.assertEqual(state.total_balance, Decimal("1000.125"))
        self.assertEqual(state.total_equity, Decimal("1001.25"))
        self.assertEqual(state.balances, (
            CurrencyBalance("USDT", Decimal("800.125"), Decimal("800.125"), Decimal("100")),
            CurrencyBalance("BTC", Decimal("0.002"), Decimal("0.002"), Decimal("0")),
        ))
        self.assertLessEqual(before, state.fetched_at)
        self.assertLessEqual(state.fetched_at, after)
        self.assertEqual(self.session.calls, [("get_wallet_balance", {"accountType": "UNIFIED"})])

    def test_account_and_nested_balances_are_immutable_and_slotted(self):
        state = self.adapter.get_account_state()
        for obj, field in ((state, "currency"), (state.balances[0], "currency")):
            self.assertFalse(hasattr(obj, "__dict__"))
            with self.assertRaises(FrozenInstanceError):
                setattr(obj, field, "OTHER")
        self.assertIs(type(state.balances), tuple)
        self.assertFalse(hasattr(state, "raw_response"))

    def test_deprecated_coin_availability_not_used_or_invented(self):
        coin = self.session.wallet["result"]["list"][0]["coin"][0]
        coin.update(availableToWithdraw="999999", free="999999")
        state = self.adapter.get_account_state()
        self.assertIsNone(state.balances[0].available_balance)
        self.assertEqual(state.available_balance, Decimal("900.125"))

    def test_blank_account_totals_stay_unavailable(self):
        account = self.session.wallet["result"]["list"][0]
        for field in ("totalAvailableBalance", "totalWalletBalance", "totalEquity"):
            account[field] = ""
        state = self.adapter.get_account_state()
        self.assertIsNone(state.available_balance)
        self.assertIsNone(state.total_balance)
        self.assertIsNone(state.total_equity)

    def test_optional_coin_equity_and_locked_balance_can_be_missing(self):
        coin = self.session.wallet["result"]["list"][0]["coin"][0]
        del coin["equity"]
        del coin["locked"]
        balance = self.adapter.get_account_state().balances[0]
        self.assertIsNone(balance.total_equity)
        self.assertIsNone(balance.locked_balance)

    def test_valid_empty_coin_list_does_not_invent_holdings(self):
        self.session.wallet["result"]["list"][0]["coin"] = []
        self.assertEqual(self.adapter.get_account_state().balances, ())

    def test_zero_account_totals_with_no_coin_rows_are_valid(self):
        account = self.session.wallet["result"]["list"][0]
        account.update(totalAvailableBalance="0", totalWalletBalance="0", totalEquity="0", coin=[])
        state = self.adapter.get_account_state()
        self.assertEqual((state.available_balance, state.total_balance, state.total_equity), (Decimal("0"),) * 3)
        self.assertEqual(state.balances, ())

    def test_reported_zero_coin_balances_remain_exact_zero(self):
        self.session.wallet["result"]["list"][0]["coin"] = [
            {"coin": "USDT", "walletBalance": "0", "equity": "0", "locked": "0"},
        ]
        balance = self.adapter.get_account_state().balances[0]
        self.assertEqual(balance, CurrencyBalance("USDT", Decimal("0"), Decimal("0"), Decimal("0")))
        self.assertIsNone(balance.available_balance)

    def test_unknown_extra_account_fields_are_ignored_without_payload_mutation(self):
        with patch("trading_lab.exchange.bybit_demo_read_only.datetime", wraps=datetime) as clock:
            clock.now.return_value = datetime(2026, 10, 9, tzinfo=timezone.utc)
            expected = self.adapter.get_account_state()
            self.session.wallet["unknown"] = {"nested": [1]}
            self.session.wallet["result"]["unknown"] = True
            account = self.session.wallet["result"]["list"][0]
            account["unknown"] = "ignored"
            account["coin"][0]["unknown"] = {"nested": [2]}
            before = deepcopy(self.session.wallet)
            self.assertEqual(self.adapter.get_account_state(), expected)
        self.assertEqual(self.session.wallet, before)

    def test_repeated_account_reads_are_deterministic_at_fixed_observation_time(self):
        before = deepcopy(self.session.wallet)
        with patch("trading_lab.exchange.bybit_demo_read_only.datetime", wraps=datetime) as clock:
            clock.now.return_value = datetime(2026, 10, 9, tzinfo=timezone.utc)
            first = self.adapter.get_account_state()
            second = self.adapter.get_account_state()
        self.assertEqual(first, second)
        self.assertIsNot(first, second)
        self.assertEqual(len(self.session.calls), 2)
        self.assertEqual(self.session.wallet, before)

    def test_negative_reported_account_and_coin_equity_preserved(self):
        account = self.session.wallet["result"]["list"][0]
        account["totalEquity"] = "-1.5"
        account["coin"][0]["equity"] = "-0.5"
        state = self.adapter.get_account_state()
        self.assertEqual(state.total_equity, Decimal("-1.5"))
        self.assertEqual(state.balances[0].total_equity, Decimal("-0.5"))

    def test_account_requires_one_unified_record(self):
        for records in ([], [{"accountType": "CONTRACT"}], [deepcopy(self.session.wallet["result"]["list"][0])] * 2):
            self.session.wallet["result"]["list"] = records
            with self.subTest(count=len(records)), self.assertRaises(BybitDemoStateParseError):
                self.adapter.get_account_state()

    def test_required_aggregate_fields_cannot_disappear(self):
        for field in ("totalAvailableBalance", "totalWalletBalance", "totalEquity"):
            self.session.wallet = wallet_response()
            del self.session.wallet["result"]["list"][0][field]
            with self.subTest(field=field), self.assertRaises(BybitDemoStateParseError):
                self.adapter.get_account_state()

    def test_invalid_coin_collection_and_duplicate_currency_rejected(self):
        for coins in (None, {}, [None], [{"coin": "USDT", "walletBalance": "1"}] * 2):
            self.session.wallet["result"]["list"][0]["coin"] = coins
            with self.subTest(type=type(coins).__name__), self.assertRaises(BybitDemoStateParseError):
                self.adapter.get_account_state()

    def test_invalid_coin_name_wallet_balance_or_locked_rejected(self):
        for field, value in (("coin", "usdt"), ("walletBalance", None), ("walletBalance", 1.0), ("locked", "-1")):
            self.session.wallet = wallet_response()
            self.session.wallet["result"]["list"][0]["coin"][0][field] = value
            with self.subTest(field=field), self.assertRaises(BybitDemoStateParseError):
                self.adapter.get_account_state()

    def test_money_is_exact_decimal_without_float_conversion(self):
        value = "1234567890123456789.1234567890123456789"
        self.session.wallet["result"]["list"][0]["totalEquity"] = value
        with localcontext() as context:
            context.prec = 2
            self.assertEqual(self.adapter.get_account_state().total_equity, Decimal(value))

    def test_account_input_and_previous_snapshot_preserved(self):
        original = deepcopy(self.session.wallet)
        first = self.adapter.get_account_state()
        self.assertEqual(self.session.wallet, original)
        self.session.wallet["result"]["list"][0]["totalEquity"] = "123"
        second = self.adapter.get_account_state()
        self.assertEqual(first.total_equity, Decimal("1001.25"))
        self.assertEqual(second.total_equity, Decimal("123"))
        self.assertIsNot(first, second)

    def test_account_timestamp_is_exact_utc_milliseconds(self):
        state = self.adapter.get_account_state()
        expected = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(milliseconds=SERVER_TIME)
        self.assertEqual(state.broker_timestamp, expected)
        self.assertEqual(state.broker_timestamp.microsecond, 200000)
        self.assertIs(state.fetched_at.tzinfo, timezone.utc)

    def test_missing_account_id_is_not_fabricated_uid(self):
        state = BybitDemoReadOnlyAdapter(self.session).get_account_state()
        self.assertIsNone(state.account_id)


class OrderTests(OfflineTests):
    def read_record(self, record):
        self.session.realtime = [order_response([record])]
        return self.adapter.get_order(record["orderId"])

    def test_one_open_order_normalized_and_exact_read_kwargs(self):
        self.session.realtime = [order_response([order_record()])]
        orders = self.adapter.get_open_orders()
        self.assertIs(type(orders), tuple)
        self.assertEqual(len(orders), 1)
        order = orders[0]
        self.assertIsInstance(order, OrderState)
        self.assertEqual((order.broker_order_id, order.symbol, order.side, order.order_type), ("order-1", "BTCUSDT", "SELL", "MARKET"))
        self.assertEqual((order.status, order.external_status, order.quantity_unit), (OrderStatus.OPEN, "New", "BASE"))
        self.assertEqual((order.requested_quantity, order.filled_quantity, order.remaining_quantity), (Decimal("2"), Decimal("0"), Decimal("2")))
        self.assertEqual(self.session.calls, [("get_open_orders", {"category": "spot", "openOnly": 0, "limit": 50})])

    def test_empty_open_orders_is_valid_empty_tuple(self):
        self.assertEqual(self.adapter.get_open_orders(), ())
        self.assertEqual(len(self.session.calls), 1)

    def test_multiple_open_orders_preserve_response_order(self):
        self.session.realtime = [order_response([order_record("first"), order_record("second")])]
        orders = self.adapter.get_open_orders()
        self.assertEqual([order.broker_order_id for order in orders], ["first", "second"])

    def test_partially_filled_order_preserves_filled_and_remaining(self):
        order = self.read_record(order_record(status="PartiallyFilled", filled="0.75"))
        self.assertEqual(order.status, OrderStatus.PARTIALLY_FILLED)
        self.assertEqual((order.filled_quantity, order.remaining_quantity), (Decimal("0.75"), Decimal("1.25")))
        self.assertEqual(order.average_fill_price, Decimal("100"))

    def test_fully_filled_base_order_has_no_unfilled_quantity(self):
        order = self.read_record(order_record(status="Filled", filled="2"))
        self.assertEqual(order.status, OrderStatus.FILLED)
        self.assertEqual(order.remaining_quantity, Decimal("0"))

    def test_cancelled_unfilled_order_is_not_filled(self):
        order = self.read_record(order_record(status="Cancelled"))
        self.assertEqual(order.status, OrderStatus.CANCELLED)
        self.assertEqual(order.remaining_quantity, Decimal("2"))

    def test_partial_cancellation_preserves_execution_and_unfilled_authorization(self):
        order = self.read_record(order_record(status="PartiallyFilledCanceled", filled="1"))
        self.assertEqual(order.status, OrderStatus.CANCELLED)
        self.assertEqual((order.filled_quantity, order.remaining_quantity), (Decimal("1"), Decimal("1")))

    def test_rejected_order_preserves_zero_fill(self):
        order = self.read_record(order_record(status="Rejected"))
        self.assertEqual(order.status, OrderStatus.REJECTED)
        self.assertEqual(order.filled_quantity, Decimal("0"))

    def test_all_supported_external_status_mappings(self):
        cases = {
            "New": (OrderStatus.OPEN, "0"), "Untriggered": (OrderStatus.NEW, "0"),
            "Triggered": (OrderStatus.NEW, "0"), "PartiallyFilled": (OrderStatus.PARTIALLY_FILLED, "1"),
            "Filled": (OrderStatus.FILLED, "2"), "Cancelled": (OrderStatus.CANCELLED, "0"),
            "PartiallyFilledCanceled": (OrderStatus.CANCELLED, "1"),
            "Deactivated": (OrderStatus.CANCELLED, "0"), "Rejected": (OrderStatus.REJECTED, "0"),
        }
        for external, (expected, filled) in cases.items():
            with self.subTest(status=external):
                order = self.read_record(order_record(status=external, filled=filled))
                self.assertIs(order.status, expected)
                self.assertEqual(order.external_status, external)

    def test_unknown_status_retained_and_not_reinterpreted(self):
        for external in ("FutureStatus", "Expired", "new"):
            with self.subTest(status=external):
                order = self.read_record(order_record(status=external, filled="1"))
                self.assertIs(order.status, OrderStatus.UNKNOWN)
                self.assertEqual(order.external_status, external)

    def test_unknown_open_result_not_silently_filtered(self):
        self.session.realtime = [order_response([order_record(status="FutureStatus")])]
        self.assertIs(self.adapter.get_open_orders()[0].status, OrderStatus.UNKNOWN)

    def test_missing_blank_or_zero_optional_average_fill_price(self):
        for value in (None, "", "0"):
            record = order_record(status="Filled", filled="2")
            record["avgPrice"] = value
            with self.subTest(value=value):
                self.assertIsNone(self.read_record(record).average_fill_price)
        record.pop("avgPrice")
        self.assertIsNone(self.read_record(record).average_fill_price)

    def test_observed_limit_and_stop_prices_do_not_create_orders(self):
        record = order_record()
        record.update(orderType="Limit", price="123.45", triggerPrice="120")
        record.pop("marketUnit")
        order = self.read_record(record)
        self.assertEqual((order.order_type, order.quantity_unit), ("LIMIT", "BASE"))
        self.assertEqual(order.limit_price, Decimal("123.45"))
        self.assertEqual(order.stop_price, Decimal("120"))
        self.assertEqual(self.session.mutations, 0)

    def test_market_price_is_not_used_as_limit_or_invented_fill(self):
        record = order_record()
        record["price"] = "99999"
        order = self.read_record(record)
        self.assertIsNone(order.limit_price)
        self.assertIsNone(order.average_fill_price)

    def test_quote_buy_preserves_dimension_and_separate_base_execution(self):
        record = order_record(status="PartiallyFilled", filled="1")
        record.update(side="Buy", marketUnit="quoteCoin", qty="200", cumExecValue="100")
        order = self.read_record(record)
        self.assertEqual(order.quantity_unit, "QUOTE")
        self.assertEqual((order.requested_quantity, order.filled_quantity, order.remaining_quantity), (Decimal("200"), Decimal("100"), Decimal("100")))
        self.assertEqual(order.filled_base_quantity, Decimal("1"))
        self.assertEqual(order.filled_quote_amount, Decimal("100"))

    def test_filled_quote_buy_can_leave_unused_budget_without_becoming_open(self):
        record = order_record(status="Filled", filled="1")
        record.update(side="Buy", marketUnit="quoteCoin", qty="101", cumExecValue="100")
        order = self.read_record(record)
        self.assertIs(order.status, OrderStatus.FILLED)
        self.assertEqual(order.remaining_quantity, Decimal("1"))

    def test_base_buy_is_observed_in_base_units(self):
        record = order_record(status="PartiallyFilled", filled="1")
        record["side"] = "Buy"
        self.assertEqual(self.read_record(record).quantity_unit, "BASE")

    def test_base_order_can_have_unavailable_quote_execution_value(self):
        record = order_record(status="Filled", filled="2")
        record.pop("cumExecValue")
        self.assertIsNone(self.read_record(record).filled_quote_amount)

    def test_missing_quote_execution_value_fails_without_base_subtraction(self):
        record = order_record()
        record.update(side="Buy", marketUnit="quoteCoin", qty="200")
        del record["cumExecValue"]
        with self.assertRaises(BybitDemoStateParseError):
            self.read_record(record)

    def test_missing_or_invalid_market_unit_rejected(self):
        for value in (None, "", "quote", {}, 1):
            record = order_record()
            record["marketUnit"] = value
            with self.subTest(value=value), self.assertRaises(BybitDemoStateParseError):
                self.read_record(record)

    def test_quote_sell_and_margin_order_rejected(self):
        for changes in ({"marketUnit": "quoteCoin"}, {"isLeverage": "1"}):
            record = order_record()
            record.update(changes)
            with self.subTest(changes=changes), self.assertRaises(BybitDemoStateParseError):
                self.read_record(record)

    def test_quantity_decimal_accuracy_and_low_context_remaining(self):
        record = order_record(status="PartiallyFilled", filled="1")
        record.update(qty="12345678901234567890.123456789", cumExecQty="1.000000001", cumExecValue="100.0000001")
        with localcontext() as context:
            context.prec = 2
            context.rounding = ROUND_UP
            order = self.read_record(record)
        self.assertEqual(order.requested_quantity, Decimal("12345678901234567890.123456789"))
        self.assertEqual(order.remaining_quantity, Decimal("12345678901234567889.123456788"))

    def test_creation_update_and_observation_timestamps_are_exact_utc(self):
        order = self.read_record(order_record())
        epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
        self.assertEqual(order.created_at, epoch + timedelta(milliseconds=1760000000001))
        self.assertEqual(order.updated_at, epoch + timedelta(milliseconds=1760000000123))
        self.assertEqual(order.broker_timestamp, epoch + timedelta(milliseconds=SERVER_TIME))
        self.assertIs(order.fetched_at.tzinfo, timezone.utc)

    def test_order_is_immutable_and_does_not_retain_raw_data(self):
        record = order_record()
        record["private_unused_field"] = {"mutable": [1]}
        order = self.read_record(record)
        self.assertFalse(hasattr(order, "__dict__"))
        with self.assertRaises(FrozenInstanceError):
            order.status = OrderStatus.FILLED
        self.assertNotIn("private_unused_field", order.__slots__)

    def test_empty_or_invalid_status_fails_explicitly(self):
        for value in (None, "", " ", 123, {}):
            record = order_record()
            record["orderStatus"] = value
            with self.subTest(value=value), self.assertRaises(BybitDemoStateParseError):
                self.read_record(record)

    def test_invalid_side_type_symbol_and_identity_rejected(self):
        for field, value in (("side", "buy"), ("orderType", "Unknown"), ("side", []), ("symbol", "btcusdt"), ("orderId", "")):
            record = order_record()
            record[field] = value
            with self.subTest(field=field), self.assertRaises(BybitDemoStateParseError):
                self.read_record(record)

    def test_zero_negative_nonfinite_and_nonstring_quantities_rejected(self):
        for field, values in (
            ("qty", ("0", "-1", "NaN", "Infinity", 2.0, True, None)),
            ("cumExecQty", ("-1", "sNaN", "-Infinity", 0.0, False, None)),
            ("cumExecValue", ("-1", "NaN", 0.0, True)),
        ):
            for value in values:
                record = order_record()
                record[field] = value
                with self.subTest(field=field, value=value), self.assertRaises(BybitDemoStateParseError):
                    self.read_record(record)

    def test_known_status_and_fill_contradictions_rejected(self):
        for status, filled in (("New", "1"), ("Rejected", "1"), ("PartiallyFilled", "0"), ("PartiallyFilled", "2"), ("Filled", "1"), ("Filled", "0"), ("FutureStatus", "3")):
            with self.subTest(status=status, filled=filled), self.assertRaises(BybitDemoStateParseError):
                self.read_record(order_record(status=status, filled=filled))

    def test_base_and_quote_execution_disagreement_rejected(self):
        for base, quote in (("0", "100"), ("1", "0")):
            record = order_record(status="FutureStatus", filled=base)
            record["cumExecValue"] = quote
            with self.subTest(base=base), self.assertRaises(BybitDemoStateParseError):
                self.read_record(record)

    def test_invalid_optional_price_and_missing_limit_price_rejected(self):
        for changes in ({"avgPrice": "NaN"}, {"triggerPrice": "-1"}, {"orderType": "Limit", "price": "0"}):
            record = order_record()
            record.update(changes)
            with self.subTest(changes=changes), self.assertRaises(BybitDemoStateParseError):
                self.read_record(record)

    def test_invalid_or_reversed_order_timestamp_rejected(self):
        for changes in ({"createdTime": "bad"}, {"createdTime": 1.0}, {"updatedTime": True}, {"updatedTime": "-1"}, {"updatedTime": "1760000000000"}, {"updatedTime": str(10**30)}):
            record = order_record()
            record.update(changes)
            with self.subTest(changes=changes), self.assertRaises(BybitDemoStateParseError):
                self.read_record(record)


class CollectionAndLookupTests(OfflineTests):
    def test_symbol_filter_is_validated_and_passed(self):
        self.adapter.get_open_orders("BTCUSDT")
        self.assertEqual(self.session.calls[0][1], {"category": "spot", "openOnly": 0, "limit": 50, "symbol": "BTCUSDT"})
        self.session.calls.clear()
        for value in ("btcusdt", " BTCUSDT", "", 123):
            with self.subTest(value=value), self.assertRaises(BybitDemoStateParseError):
                self.adapter.get_open_orders(value)
        self.assertEqual(self.session.calls, [])

    def test_returned_filtered_symbol_must_match(self):
        self.session.realtime = [order_response([order_record()])]
        with self.assertRaises(BybitDemoStateParseError):
            self.adapter.get_open_orders("ETHUSDT")

    def test_open_orders_consume_all_pages(self):
        self.session.realtime = [order_response([order_record("first")], "next-1"), order_response([order_record("second")])]
        orders = self.adapter.get_open_orders()
        self.assertEqual([order.broker_order_id for order in orders], ["first", "second"])
        self.assertEqual(self.session.calls[1][1], {"category": "spot", "openOnly": 0, "limit": 50, "cursor": "next-1"})

    def test_duplicate_orders_fail_without_silent_deduplication(self):
        self.session.realtime = [order_response([order_record()], "next-1"), order_response([order_record()])]
        with self.assertRaises(BybitDemoStateParseError):
            self.adapter.get_open_orders()

    def test_repeated_cursor_or_empty_page_with_cursor_rejected(self):
        for responses in (
            [order_response([order_record("first")], "same"), order_response([order_record("second")], "same")],
            [order_response([], "next")],
        ):
            self.session.realtime = responses
            with self.subTest(pages=len(responses)), self.assertRaises(BybitDemoStateParseError):
                self.adapter.get_open_orders()

    def test_pagination_is_bounded_and_never_returns_truncated_success(self):
        self.session.realtime = [order_response([order_record(f"order-{i}")], f"cursor-{i}") for i in range(101)]
        with self.assertRaisesRegex(BybitDemoStateParseError, "100-page"):
            self.adapter.get_open_orders()
        self.assertEqual(len(self.session.calls), 100)

    def test_missing_or_invalid_cursor_rejected(self):
        for cursor in (None, 123, " next "):
            self.session.realtime = [order_response(cursor=cursor)]
            with self.subTest(cursor=cursor), self.assertRaises(BybitDemoStateParseError):
                self.adapter.get_open_orders()

    def test_closed_record_in_open_query_fails(self):
        self.session.realtime = [order_response([order_record(status="Filled", filled="2")])]
        with self.assertRaises(BybitDemoStateParseError):
            self.adapter.get_open_orders()

    def test_late_page_failure_does_not_mutate_previous_snapshot_or_cache_partial_state(self):
        self.session.realtime = [order_response([order_record()])]
        previous = self.adapter.get_open_orders()
        self.session.realtime = [order_response([order_record("second")], "next"), {"retCode": 0, "result": None}]
        with self.assertRaises(BybitDemoStateParseError):
            self.adapter.get_open_orders()
        self.assertEqual(previous[0].broker_order_id, "order-1")
        self.assertEqual(set(self.adapter.__slots__), {"_session", "_account_id"})
        self.session.realtime = [order_response()]
        self.assertEqual(self.adapter.get_open_orders(), ())

    def test_exact_id_lookup_returns_realtime_without_history(self):
        self.session.realtime = [order_response([order_record()])]
        self.adapter.get_order("order-1")
        self.assertEqual(self.session.calls, [("get_open_orders", {"category": "spot", "orderId": "order-1"})])

    def test_repeated_order_reads_are_deterministic_at_fixed_observation_time(self):
        self.session.realtime = [order_response([order_record()])]
        before = deepcopy(self.session.realtime)
        with patch("trading_lab.exchange.bybit_demo_read_only.datetime", wraps=datetime) as clock:
            clock.now.return_value = datetime(2026, 10, 9, tzinfo=timezone.utc)
            first_open = self.adapter.get_open_orders()
            second_open = self.adapter.get_open_orders()
            first_lookup = self.adapter.get_order("order-1")
            second_lookup = self.adapter.get_order("order-1")
        self.assertEqual(first_open, second_open)
        self.assertEqual(first_lookup, second_lookup)
        self.assertEqual(first_open[0], first_lookup)
        self.assertIsNot(first_open[0], second_open[0])
        self.assertIsNot(first_lookup, second_lookup)
        self.assertEqual(len(self.session.calls), 4)
        self.assertEqual(self.session.realtime, before)

    def test_valid_empty_realtime_falls_back_to_history(self):
        self.session.history = order_response([order_record(status="Filled", filled="2")])
        order = self.adapter.get_order("order-1")
        self.assertIs(order.status, OrderStatus.FILLED)
        self.assertEqual(self.session.calls, [
            ("get_open_orders", {"category": "spot", "orderId": "order-1"}),
            ("get_order_history", {"category": "spot", "orderId": "order-1"}),
        ])

    def test_absent_order_raises_unknown_outcome_not_fabricated_state(self):
        with self.assertRaises(BrokerOrderNotFoundError) as error:
            self.adapter.get_order("not-observed")
        self.assertIn("outcome remains unknown", str(error.exception))
        self.assertEqual(len(self.session.calls), 2)

    def test_invalid_requested_id_fails_before_read(self):
        for value in (None, "", " id ", 123):
            with self.subTest(value=value), self.assertRaises(BybitDemoStateParseError):
                self.adapter.get_order(value)
        self.assertEqual(self.session.calls, [])

    def test_multiple_or_mismatched_lookup_records_rejected(self):
        for records in ([order_record("other")], [order_record(), order_record("other")]):
            self.session.realtime = [order_response(records)]
            with self.subTest(count=len(records)), self.assertRaises(BybitDemoStateParseError):
                self.adapter.get_order("order-1")

    def test_history_identity_must_also_match(self):
        self.session.history = order_response([order_record("other")])
        with self.assertRaises(BybitDemoStateParseError):
            self.adapter.get_order("order-1")

    def test_malformed_realtime_does_not_trigger_history_fallback(self):
        self.session.realtime = [{"retCode": 0}]
        with self.assertRaises(BybitDemoStateParseError):
            self.adapter.get_order("order-1")
        self.assertEqual(len(self.session.calls), 1)


class OrderLinkTests(OfflineTests):
    def test_reported_caller_order_link_is_preserved(self):
        record = order_record()
        record["orderLinkId"] = "caller-1"
        self.session.realtime = [order_response([record])]
        self.assertEqual(self.adapter.get_order("order-1").order_link_id, "caller-1")

    def test_absent_blank_or_null_order_link_remains_none(self):
        for value in (None, ""):
            record = order_record()
            record["orderLinkId"] = value
            self.session.realtime = [order_response([record])]
            with self.subTest(value=value):
                self.assertIsNone(self.adapter.get_order("order-1").order_link_id)
        self.session.realtime = [order_response([order_record()])]
        self.assertIsNone(self.adapter.get_order("order-1").order_link_id)

    def test_malformed_order_link_is_rejected_without_repair(self):
        for value in (123, [], {}, " caller "):
            record = order_record()
            record["orderLinkId"] = value
            self.session.realtime = [order_response([record])]
            with self.subTest(value=value), self.assertRaises(BybitDemoStateParseError):
                self.adapter.get_order("order-1")


class ExecutionTests(OfflineTests):
    def test_valid_execution_normalizes_reported_fill_and_exact_request(self):
        self.session.executions = [execution_response([execution_record()])]
        before = datetime.now(timezone.utc)
        (fill,) = self.adapter.get_executions(order_id="order-1", symbol="BTCUSDT")
        after = datetime.now(timezone.utc)
        self.assertIsInstance(fill, ExecutionState)
        self.assertEqual((fill.broker_id, fill.account_id), ("bybit-demo", "research-demo"))
        self.assertEqual((fill.broker_execution_id, fill.broker_order_id, fill.order_link_id), ("fill-1", "order-1", "caller-1"))
        self.assertEqual((fill.symbol, fill.side), ("BTCUSDT", "BUY"))
        self.assertEqual(fill.executed_quantity, Decimal("0.002"))
        self.assertEqual(fill.execution_price, Decimal("50000.125"))
        self.assertEqual((fill.execution_fee, fill.fee_currency), (Decimal("0.000002"), "BTC"))
        self.assertLessEqual(before, fill.fetched_at)
        self.assertLessEqual(fill.fetched_at, after)
        self.assertEqual(self.session.calls, [("get_executions", {
            "category": "spot", "execType": "Trade", "limit": 100,
            "orderId": "order-1", "symbol": "BTCUSDT",
        })])

    def test_empty_executions_do_not_fabricate_fills_from_filled_order(self):
        self.session.history = order_response([order_record(status="Filled", filled="2")])
        self.assertEqual(self.adapter.get_executions("order-1"), ())
        self.assertEqual([name for name, _ in self.session.calls], ["get_executions"])

    def test_multiple_fills_per_order_preserve_broker_sequence(self):
        records = [execution_record("second"), execution_record("first")]
        self.session.executions = [execution_response(records)]
        fills = self.adapter.get_executions("order-1")
        self.assertEqual([fill.broker_execution_id for fill in fills], ["second", "first"])
        self.assertEqual([fill.broker_order_id for fill in fills], ["order-1", "order-1"])

    def test_unfiltered_execution_read_retains_multiple_order_identities(self):
        self.session.executions = [execution_response([execution_record("a", "one"), execution_record("b", "two")])]
        fills = self.adapter.get_executions()
        self.assertEqual([fill.broker_order_id for fill in fills], ["one", "two"])
        self.assertEqual(self.session.calls[0][1], {"category": "spot", "execType": "Trade", "limit": 100})

    def test_reported_sell_fee_currency_and_zero_fee_are_preserved(self):
        record = execution_record()
        record.update(side="Sell", execFee="0", feeCurrency="USDT")
        self.session.executions = [execution_response([record])]
        (fill,) = self.adapter.get_executions()
        self.assertEqual((fill.side, fill.execution_fee, fill.fee_currency), ("SELL", Decimal("0"), "USDT"))

    def test_signed_fee_rebate_keeps_reported_currency_without_conversion(self):
        record = execution_record()
        record.update(execFee="-0.012345678901234567890123456789", feeCurrency="USDT")
        self.session.executions = [execution_response([record])]
        (fill,) = self.adapter.get_executions()
        self.assertEqual(fill.execution_fee, Decimal("-0.012345678901234567890123456789"))
        self.assertEqual(fill.fee_currency, "USDT")

    def test_missing_blank_or_null_fee_currency_is_not_inferred(self):
        for value in (None, ""):
            record = execution_record()
            record["feeCurrency"] = value
            self.session.executions = [execution_response([record])]
            with self.subTest(value=value):
                (fill,) = self.adapter.get_executions()
                self.assertIsNone(fill.fee_currency)
                self.assertEqual(fill.execution_fee, Decimal("0.000002"))
        record = execution_record()
        del record["feeCurrency"]
        self.session.executions = [execution_response([record])]
        self.assertIsNone(self.adapter.get_executions()[0].fee_currency)

    def test_malformed_fee_currency_is_rejected(self):
        for value in (123, [], "btc", " BTC "):
            record = execution_record()
            record["feeCurrency"] = value
            self.session.executions = [execution_response([record])]
            with self.subTest(value=value), self.assertRaises(BybitDemoStateParseError):
                self.adapter.get_executions()

    def test_decimal_execution_fields_do_not_round_or_underflow(self):
        record = execution_record()
        record.update(execQty="1E-400", execPrice="12345.678901234567890123456789", execFee="1E-405")
        self.session.executions = [execution_response([record])]
        with localcontext() as context:
            context.prec = 2
            (fill,) = self.adapter.get_executions()
        self.assertEqual(fill.executed_quantity, Decimal("1E-400"))
        self.assertEqual(fill.execution_price, Decimal("12345.678901234567890123456789"))
        self.assertEqual(fill.execution_fee, Decimal("1E-405"))

    def test_missing_required_execution_fields_fail(self):
        for field in ("execId", "orderId", "symbol", "side", "execType", "execQty", "execPrice", "execFee", "execTime"):
            record = execution_record()
            del record[field]
            self.session.executions = [execution_response([record])]
            with self.subTest(field=field), self.assertRaises(BybitDemoStateParseError):
                self.adapter.get_executions()

    def test_malformed_or_nonfinite_execution_amounts_fail(self):
        for field in ("execQty", "execPrice", "execFee"):
            for value in (None, "", "bad", "NaN", "Infinity", "-Infinity", " 1", 1, 1.0, True, [], {}):
                record = execution_record()
                record[field] = value
                self.session.executions = [execution_response([record])]
                with self.subTest(field=field, value=value), self.assertRaises(BybitDemoStateParseError):
                    self.adapter.get_executions()

    def test_nonpositive_execution_quantity_or_price_fails(self):
        for field in ("execQty", "execPrice"):
            for value in ("0", "-0.1"):
                record = execution_record()
                record[field] = value
                self.session.executions = [execution_response([record])]
                with self.subTest(field=field, value=value), self.assertRaises(BybitDemoStateParseError):
                    self.adapter.get_executions()

    def test_malformed_execution_identities_and_side_fail(self):
        for field in ("execId", "orderId", "symbol", "side"):
            for value in (None, "", " value ", 1, []):
                record = execution_record()
                record[field] = value
                self.session.executions = [execution_response([record])]
                with self.subTest(field=field, value=value), self.assertRaises(BybitDemoStateParseError):
                    self.adapter.get_executions()

    def test_nontrade_and_reported_margin_execution_are_not_normalized_as_fills(self):
        for field, value in (("execType", "Funding"), ("execType", "FutureSpread"), ("execType", "FutureStatus"), ("isLeverage", "1")):
            record = execution_record()
            record[field] = value
            self.session.executions = [execution_response([record])]
            with self.subTest(field=field, value=value), self.assertRaises(BybitDemoStateParseError):
                self.adapter.get_executions()

    def test_execution_and_server_timestamps_are_aware_utc_and_millisecond_exact(self):
        self.session.executions = [execution_response([execution_record()])]
        (fill,) = self.adapter.get_executions()
        epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
        self.assertEqual(fill.executed_at, epoch + timedelta(milliseconds=1760000000123))
        self.assertEqual(fill.broker_timestamp, epoch + timedelta(milliseconds=SERVER_TIME))
        self.assertIs(fill.executed_at.tzinfo, timezone.utc)
        self.assertIs(fill.fetched_at.tzinfo, timezone.utc)

    def test_invalid_execution_or_server_timestamp_fails(self):
        for location in ("execTime", "time"):
            for value in (None, True, 1.0, "bad", "-1", str(10**30)):
                response = execution_response([execution_record()])
                target = response if location == "time" else response["result"]["list"][0]
                target[location] = value
                self.session.executions = [response]
                with self.subTest(location=location, value=value), self.assertRaises(BybitDemoStateParseError):
                    self.adapter.get_executions()

    def test_execution_objects_are_immutable_slotted_and_have_no_raw_payload(self):
        self.session.executions = [execution_response([execution_record()])]
        (fill,) = self.adapter.get_executions()
        self.assertFalse(hasattr(fill, "__dict__"))
        with self.assertRaises(FrozenInstanceError):
            fill.execution_fee = Decimal("0")
        self.assertFalse(hasattr(fill, "raw"))

    def test_execution_order_link_missing_or_blank_remains_none(self):
        for value in (None, ""):
            record = execution_record()
            record["orderLinkId"] = value
            self.session.executions = [execution_response([record])]
            self.assertIsNone(self.adapter.get_executions()[0].order_link_id)
        record = execution_record()
        del record["orderLinkId"]
        self.session.executions = [execution_response([record])]
        self.assertIsNone(self.adapter.get_executions()[0].order_link_id)

    def test_malformed_execution_order_link_fails(self):
        record = execution_record()
        record["orderLinkId"] = []
        self.session.executions = [execution_response([record])]
        with self.assertRaises(BybitDemoStateParseError):
            self.adapter.get_executions()

    def test_unknown_extra_execution_fields_are_tolerated_and_input_is_unmodified(self):
        record = execution_record()
        record["unknown"] = {"nested": [1]}
        response = execution_response([record])
        before = deepcopy(response)
        with patch.object(self.session, "get_executions", return_value=response):
            (fill,) = self.adapter.get_executions()
        self.assertEqual(fill.broker_execution_id, "fill-1")
        self.assertEqual(response, before)

    def test_repeated_execution_reads_are_deterministic_with_fixed_observation_clock(self):
        self.session.executions = [execution_response([execution_record()])]
        before = deepcopy(self.session.executions)
        with patch("trading_lab.exchange.bybit_demo_read_only.datetime", wraps=datetime) as clock:
            clock.now.return_value = datetime(2026, 10, 10, tzinfo=timezone.utc)
            first = self.adapter.get_executions()
            second = self.adapter.get_executions()
        self.assertEqual(first, second)
        self.assertIsNot(first[0], second[0])
        self.assertEqual(self.session.executions, before)
        self.assertEqual(len(self.session.calls), 2)

    def test_execution_response_shapes_and_category_are_validated(self):
        responses = [None, [], {}, {"retCode": "0"}, {"retCode": False},
                     {"retCode": 0, "result": []},
                     {"retCode": 0, "time": SERVER_TIME, "result": {"category": "spot", "list": [None]}}]
        wrong_category = execution_response()
        wrong_category["result"]["category"] = "linear"
        responses.append(wrong_category)
        for response in responses:
            self.session.executions = [response]
            with self.subTest(response_type=type(response).__name__), self.assertRaises(BybitDemoStateParseError):
                self.adapter.get_executions()

    def test_order_and_symbol_filters_validate_returned_execution_identity(self):
        for kwargs in ({"order_id": "other"}, {"symbol": "ETHUSDT"}, {"order_id": "order-1", "symbol": "ETHUSDT"}):
            self.session.executions = [execution_response([execution_record()])]
            with self.subTest(kwargs=kwargs), self.assertRaises(BybitDemoStateParseError):
                self.adapter.get_executions(**kwargs)

    def test_invalid_execution_filters_fail_before_any_request(self):
        for kwargs in ({"order_id": ""}, {"order_id": 1}, {"order_id": " id "}, {"symbol": "btcusdt"}, {"symbol": ""}, {"symbol": []}):
            with self.subTest(kwargs=kwargs), self.assertRaises(BybitDemoStateParseError):
                self.adapter.get_executions(**kwargs)
        self.assertEqual(self.session.calls, [])

    def test_execution_pagination_preserves_filters_and_all_fills(self):
        self.session.executions = [execution_response([execution_record("one")], "page-2"),
                                   execution_response([execution_record("two")])]
        fills = self.adapter.get_executions("order-1", "BTCUSDT")
        self.assertEqual([fill.broker_execution_id for fill in fills], ["one", "two"])
        expected = {"category": "spot", "execType": "Trade", "limit": 100, "orderId": "order-1", "symbol": "BTCUSDT"}
        self.assertEqual(self.session.calls, [("get_executions", expected), ("get_executions", {**expected, "cursor": "page-2"})])

    def test_duplicate_execution_ids_within_or_across_pages_fail(self):
        for pages in ([execution_response([execution_record(), execution_record()])],
                      [execution_response([execution_record()], "next"), execution_response([execution_record()])]):
            self.session.executions = pages
            with self.subTest(pages=len(pages)), self.assertRaises(BybitDemoStateParseError):
                self.adapter.get_executions()

    def test_missing_or_malformed_execution_pagination_cursor_fails(self):
        for value in (None, 123, [], " token "):
            response = execution_response()
            response["result"]["nextPageCursor"] = value
            self.session.executions = [response]
            with self.subTest(value=value), self.assertRaises(BybitDemoStateParseError):
                self.adapter.get_executions()
        response = execution_response()
        del response["result"]["nextPageCursor"]
        self.session.executions = [response]
        with self.assertRaises(BybitDemoStateParseError):
            self.adapter.get_executions()

    def test_empty_continuing_execution_page_and_repeated_cursor_fail(self):
        for pages in ([execution_response(cursor="next")],
                      [execution_response([execution_record("one")], "next"),
                       execution_response([execution_record("two")], "next")]):
            self.session.executions = pages
            with self.subTest(pages=len(pages)), self.assertRaises(BybitDemoStateParseError):
                self.adapter.get_executions()

    def test_execution_pagination_is_bounded_without_truncated_success(self):
        self.session.executions = [execution_response([execution_record(str(i))], f"next-{i}") for i in range(100)]
        with self.assertRaises(BybitDemoStateParseError):
            self.adapter.get_executions()
        self.assertEqual(len(self.session.calls), 100)

    def test_late_execution_parse_failure_preserves_prior_snapshots_and_raw_response(self):
        self.session.executions = [execution_response([execution_record()])]
        previous = self.adapter.get_executions()
        invalid = execution_record("two")
        invalid["execFee"] = "NaN"
        response = execution_response([execution_record("one"), invalid])
        before = deepcopy(response)
        with patch.object(self.session, "get_executions", return_value=response):
            with self.assertRaises(BybitDemoStateParseError):
                self.adapter.get_executions()
        self.assertEqual(response, before)
        self.assertEqual(previous[0].execution_fee, Decimal("0.000002"))
        self.assertEqual(self.session.mutations, 0)

    def test_api_error_fails_with_safe_context_without_raw_payload(self):
        self.session.executions = [{"retCode": 10001, "retMsg": "private-offline-marker"}]
        with self.assertRaises(BybitDemoReadError) as error:
            self.adapter.get_executions()
        self.assertIn("get_executions", str(error.exception))
        self.assertIn("10001", str(error.exception))
        self.assertNotIn("private-offline-marker", str(error.exception))
        self.assertEqual(len(self.session.calls), 1)

    def test_transport_error_does_not_retry_or_expose_private_exception_text(self):
        self.session.errors["get_executions"] = TimeoutError("private-offline-marker")
        with self.assertRaises(BybitDemoReadError) as error:
            self.adapter.get_executions()
        self.assertIn("get_executions", str(error.exception))
        self.assertIn("TimeoutError", str(error.exception))
        self.assertNotIn("private-offline-marker", str(error.exception))
        self.assertTrue(error.exception.__suppress_context__)
        self.assertEqual(len(self.session.calls), 1)

    def test_late_execution_api_failure_does_not_return_partial_fills(self):
        self.session.executions = [execution_response([execution_record()], "next"), {"retCode": 10001}]
        with self.assertRaises(BybitDemoReadError):
            self.adapter.get_executions()
        self.assertEqual(len(self.session.calls), 2)
        self.assertEqual(self.session.mutations, 0)


class FailureAndSafetyTests(OfflineTests):
    def test_direct_response_payloads_remain_unchanged_after_late_parse_failure(self):
        wallet = wallet_response()
        wallet["result"]["list"][0]["coin"][1]["walletBalance"] = "NaN"
        invalid_order = order_record("second")
        invalid_order["updatedTime"] = "bad"
        orders = order_response([order_record("first"), invalid_order])
        wallet_before, orders_before = deepcopy(wallet), deepcopy(orders)
        # Return the original payloads, so the fake's defensive copies cannot
        # hide accidental parser writes to caller-owned response objects.
        with patch.object(self.session, "get_wallet_balance", return_value=wallet):
            with self.assertRaises(BybitDemoStateParseError):
                self.adapter.get_account_state()
        with patch.object(self.session, "get_open_orders", return_value=orders):
            with self.assertRaises(BybitDemoStateParseError):
                self.adapter.get_open_orders()
        self.assertEqual(wallet, wallet_before)
        self.assertEqual(orders, orders_before)
        self.assertEqual(self.session.mutations, 0)

    def test_malformed_response_shapes_rejected_for_account_and_orders(self):
        for response in (None, [], {}, {"retCode": "0"}, {"retCode": False}, {"retCode": 0, "result": []}, {"retCode": 0, "time": SERVER_TIME, "result": {"list": [None]}}):
            self.session.wallet = response
            self.session.realtime = [response]
            with self.subTest(response_type=type(response).__name__):
                with self.assertRaises(BybitDemoStateParseError):
                    self.adapter.get_account_state()
                with self.assertRaises(BybitDemoStateParseError):
                    self.adapter.get_open_orders()

    def test_wrong_order_category_rejected(self):
        response = order_response()
        response["result"]["category"] = "linear"
        self.session.realtime = [response]
        with self.assertRaises(BybitDemoStateParseError):
            self.adapter.get_open_orders()

    def test_api_error_retcode_explicit_and_raw_response_not_exposed(self):
        self.session.wallet = {"retCode": 10001, "retMsg": "private-offline-marker"}
        with self.assertRaises(BybitDemoReadError) as error:
            self.adapter.get_account_state()
        self.assertIn("get_wallet_balance", str(error.exception))
        self.assertIn("10001", str(error.exception))
        self.assertNotIn("private-offline-marker", str(error.exception))

    def test_network_errors_have_safe_operation_and_type_without_secret_text(self):
        self.session.errors["get_wallet_balance"] = TimeoutError("private-offline-marker")
        with self.assertRaises(BybitDemoReadError) as error:
            self.adapter.get_account_state()
        self.assertIn("get_wallet_balance", str(error.exception))
        self.assertIn("TimeoutError", str(error.exception))
        self.assertNotIn("private-offline-marker", str(error.exception))
        self.assertTrue(error.exception.__suppress_context__)
        self.assertEqual(len(self.session.calls), 1)

    def test_order_network_failure_does_not_retry_or_query_history(self):
        self.session.errors["get_open_orders"] = ConnectionError("offline")
        with self.assertRaises(BybitDemoReadError):
            self.adapter.get_order("order-1")
        self.assertEqual([name for name, _ in self.session.calls], ["get_open_orders"])

    def test_history_network_failure_is_not_empty_success(self):
        self.session.errors["get_order_history"] = TimeoutError("offline")
        with self.assertRaises(BybitDemoReadError):
            self.adapter.get_order("order-1")
        self.assertEqual(len(self.session.calls), 2)

    def test_invalid_server_time_rejected(self):
        for value in (None, True, 1.0, "bad", "-1", str(10**30)):
            self.session.wallet = wallet_response()
            self.session.wallet["time"] = value
            with self.subTest(value=value), self.assertRaises(BybitDemoStateParseError):
                self.adapter.get_account_state()

    def test_invalid_monetary_fields_never_fabricate_balance(self):
        for value in ("bad", "NaN", "Infinity", " 1", 1.0, True, [], {}):
            self.session.wallet = wallet_response()
            self.session.wallet["result"]["list"][0]["totalAvailableBalance"] = value
            with self.subTest(value=value), self.assertRaises(BybitDemoStateParseError):
                self.adapter.get_account_state()

    def test_constructor_rejects_real_testnet_ambiguous_and_unsafe_clients(self):
        for field, value in (("demo", False), ("testnet", True), ("demo", 1), ("endpoint", "https://api.bybit.com"), ("force_retry", True), ("max_retries", 3), ("max_retries", True), ("retry_delay", 2), ("log_requests", True)):
            session = FakeDemoSession()
            setattr(session, field, value)
            with self.subTest(field=field), self.assertRaises(BybitDemoReadError):
                BybitDemoReadOnlyAdapter(session)
            self.assertEqual(session.calls, [])
        with self.assertRaises(BybitDemoReadError):
            BybitDemoReadOnlyAdapter(object())

    def test_changed_demo_endpoint_is_rejected_before_each_read(self):
        self.session.endpoint = "https://api.bybit.com"
        for operation in (self.adapter.get_account_state, self.adapter.get_open_orders, lambda: self.adapter.get_order("order-1"), self.adapter.get_executions):
            with self.assertRaises(BybitDemoReadError):
                operation()
        self.assertEqual(self.session.calls, [])

    def test_missing_or_non_callable_read_method_rejected_at_construction(self):
        for method in ("get_wallet_balance", "get_open_orders", "get_order_history", "get_executions"):
            session = FakeDemoSession()
            setattr(session, method, None)
            with self.subTest(method=method), self.assertRaises(TypeError):
                BybitDemoReadOnlyAdapter(session)

    def test_constructor_performs_no_requests_and_repr_has_no_client(self):
        adapter = BybitDemoReadOnlyAdapter(self.session)
        self.assertEqual(self.session.calls, [])
        self.assertIn("BybitDemoReadOnlyAdapter", repr(adapter))
        self.assertNotIn("FakeDemoSession", repr(adapter))

    def test_normal_reads_never_call_mutation_endpoints_or_change_broker_payloads(self):
        self.session.realtime = [order_response([order_record()])]
        self.session.executions = [execution_response([execution_record()])]
        wallet_before, orders_before = deepcopy(self.session.wallet), deepcopy(self.session.realtime)
        fills_before = deepcopy(self.session.executions)
        with patch("builtins.print") as output, patch("logging.getLogger") as logger:
            self.adapter.get_account_state()
            self.adapter.get_open_orders()
            self.adapter.get_order("order-1")
            self.adapter.get_executions()
            output.assert_not_called()
            logger.assert_not_called()
        self.assertEqual(self.session.mutations, 0)
        self.assertEqual(self.session.wallet, wallet_before)
        self.assertEqual(self.session.realtime, orders_before)
        self.assertEqual(self.session.executions, fills_before)
        self.assertTrue(all(name in {"get_wallet_balance", "get_open_orders", "get_order_history", "get_executions"} for name, _ in self.session.calls))

    def test_no_public_mutation_methods_or_session_exposure(self):
        public_methods = {name for name, value in inspect.getmembers(BybitDemoReadOnlyAdapter, inspect.isfunction) if not name.startswith("_")}
        self.assertEqual(public_methods, {"get_account_state", "get_open_orders", "get_order", "get_executions"})
        for name in ("submit_order", "create_order", "place_order", "cancel_order", "amend_order", "replace_order", "modify_order", "batch_place_order", "batch_cancel_order", "batch_amend_order", "session", "client"):
            self.assertFalse(hasattr(self.adapter, name))

    def test_private_dispatch_cannot_reach_any_mutation_name(self):
        for name in ("place_order", "cancel_order", "amend_order", "cancel_all_orders", "submit_order", "create_order", "replace_order", "modify_order", "batch_place_order", "batch_cancel_order", "batch_amend_order"):
            with self.subTest(name=name), self.assertRaises(BybitDemoReadError):
                self.adapter._read(name)
        self.assertEqual(self.session.mutations, 0)
        self.assertEqual(self.session.calls, [])

    def test_source_guard_locks_read_allowlist_and_has_no_mutation_path(self):
        import trading_lab.exchange.bybit_demo_read_only as module
        self.assertEqual(module._READ_METHODS, frozenset({"get_wallet_balance", "get_open_orders", "get_order_history", "get_executions"}))
        forbidden = {"submit_order", "create_order", "place_order", "cancel_order", "cancel_all_orders", "amend_order", "replace_order", "modify_order", "batch_place_order", "batch_cancel_order", "batch_amend_order"}
        source = inspect.getsource(module)
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.Attribute)):
                self.assertNotIn(node.name if isinstance(node, ast.FunctionDef) else node.attr, forbidden)
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                self.assertNotIn(node.value, forbidden)
        self.assertNotIn("os.environ", source)
        self.assertNotIn("api_key", source)
        self.assertNotIn("api_secret", source)
        self.assertNotIn("HTTP(", source)

    def test_model_module_is_broker_independent_and_protocol_read_only(self):
        import trading_lab.exchange.account_state as module
        source = inspect.getsource(module)
        self.assertNotIn("bybit", source.lower())
        self.assertNotIn("requests", source)
        methods = {name for name, value in inspect.getmembers(ReadOnlyBroker, inspect.isfunction) if not name.startswith("_")}
        self.assertEqual(methods, {"get_account_state", "get_open_orders", "get_order", "get_executions"})
        self.assertEqual({status.value for status in OrderStatus}, {"NEW", "OPEN", "PARTIALLY_FILLED", "FILLED", "CANCELLED", "REJECTED", "EXPIRED", "UNKNOWN"})

    def test_real_sdk_read_paths_are_get_only_without_network(self):
        from trading_lab.exchange import BybitDemoCredentials, create_bybit_demo_session
        session = create_bybit_demo_session(BybitDemoCredentials("offline-read-key", "offline-read-secret"))
        calls = []

        def sdk_read(**kwargs):
            calls.append(kwargs)
            if kwargs["path"].endswith("/v5/account/wallet-balance"):
                return wallet_response()
            if kwargs["path"].endswith("/v5/order/realtime"):
                return order_response()
            if kwargs["path"].endswith("/v5/order/history"):
                return order_response([order_record(status="Filled", filled="2")])
            if kwargs["path"].endswith("/v5/execution/list"):
                return execution_response([execution_record()])
            raise AssertionError("Unexpected SDK endpoint")

        try:
            with patch.object(session, "_submit_request", side_effect=sdk_read):
                adapter = BybitDemoReadOnlyAdapter(session)
                adapter.get_account_state()
                adapter.get_open_orders()
                adapter.get_order("order-1")
                adapter.get_executions("order-1")
            self.assertEqual(len(calls), 5)
            for call in calls:
                self.assertEqual(call["method"], "GET")
                self.assertTrue(call["path"].startswith("https://api-demo.bybit.com/"))
                self.assertIs(call["auth"], True)
            self.assertEqual(calls[-1]["query"], {"category": "spot", "execType": "Trade", "limit": 100, "orderId": "order-1"})
        finally:
            session.client.close()

    def test_imports_do_not_read_environment_create_sessions_or_call_network(self):
        script = textwrap.dedent("""
            import importlib
            import os
            from unittest.mock import patch
            import requests
            import pybit.unified_trading

            class NoEnvironmentReads(dict):
                def get(self, *args):
                    raise AssertionError('No environment reads')
                def __getitem__(self, name):
                    raise AssertionError('No environment reads')

            with patch('os.environ', NoEnvironmentReads()):
                with patch('pybit.unified_trading.HTTP', side_effect=AssertionError('No client construction')):
                    with patch.object(requests.Session, 'request', side_effect=AssertionError('No network')):
                        with patch.object(requests.Session, 'send', side_effect=AssertionError('No network')):
                            for name in ('trading_lab.exchange', 'trading_lab.exchange.account_state', 'trading_lab.exchange.bybit_demo_read_only'):
                                importlib.import_module(name)
        """)
        src = Path(__file__).resolve().parents[1] / "src"
        result = subprocess.run([sys.executable, "-c", script], env={"PYTHONPATH": str(src), "PYTHONDONTWRITEBYTECODE": "1"}, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
