"""Offline Stage 9.5 tests: authorized actions, receipts, uncertainty and scope."""

import ast
from copy import deepcopy
from dataclasses import FrozenInstanceError, fields, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_UP, localcontext
import inspect
import json
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest
from unittest.mock import Mock, patch

from pybit.exceptions import FailedRequestError, InvalidRequestError
import requests

import trading_lab.exchange as exchange
import trading_lab.exchange.bybit_demo_orders as actions
from trading_lab.exchange import (
    BybitDemoActionError, BybitDemoActionParseError,
    BybitDemoAmbiguousActionError, BybitDemoConfigurationError,
    BybitDemoCredentials, BybitDemoOrderAdapter, BybitDemoOrderRejectedError,
    BybitDemoReadOnlyAdapter, OrderCancellationAcknowledgement,
    OrderStatus, SpotMarketOrderAcknowledgement, SpotMarketOrderRequest,
    create_bybit_demo_session,
)
from trading_lab.exchange.bybit_spot_rules import BybitSpotOrderConstraintError
from tests.test_bybit_spot_rules import synthetic_response
from tests.test_bybit_demo_read_only import (
    FakeDemoSession as ReadSession, execution_record, execution_response,
    order_record, order_response,
)


SERVER_TIME = 1760000000200
PRIVATE_MARKER = "private-offline-marker"


def ack_response(order_id="order-1", link=""):
    return {"retCode": 0, "result": {"orderId": order_id, "orderLinkId": link}, "time": SERVER_TIME}


def buy_request(link=None, amount=Decimal("12.34567899")):
    return SpotMarketOrderRequest("BTCUSDT", "BUY", amount, "QUOTE", link)


def sell_request(amount=Decimal("0.1234569"), link=None):
    return SpotMarketOrderRequest("BTCUSDT", "SELL", amount, "BASE", link)


class FakeActionSession(ReadSession):
    """Approved mutation stubs record attempts; every other mutation still raises."""

    def __init__(self):
        super().__init__()
        self.instrument = synthetic_response()
        self.placement = ack_response()
        self.cancellation = ack_response()

    def get_instruments_info(self, **kwargs):
        return self._invoke("get_instruments_info", kwargs, self.instrument)

    def place_order(self, **kwargs):
        return self._invoke("place_order", kwargs, self.placement)

    def cancel_order(self, **kwargs):
        return self._invoke("cancel_order", kwargs, self.cancellation)


class OfflineTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(requests.Session, "send", side_effect=AssertionError("No live network")))
        self.enterContext(patch.object(requests.Session, "request", side_effect=AssertionError("No live network")))
        self.session = FakeActionSession()
        self.adapter = BybitDemoOrderAdapter(self.session)

    def mutation_calls(self, name="place_order"):
        return [params for method, params in self.session.calls if method == name]


class PlacementTests(OfflineTests):
    def test_buy_exact_safe_sdk_parameters_and_normalized_receipt(self):
        receipt = self.adapter.place_market_order(buy_request())
        self.assertEqual(self.session.calls, [
            ("get_instruments_info", {"category": "spot", "symbol": "BTCUSDT"}),
            ("place_order", {"category": "spot", "symbol": "BTCUSDT", "side": "Buy",
                             "orderType": "Market", "qty": "12.3456789",
                             "marketUnit": "quoteCoin", "isLeverage": 0}),
        ])
        self.assertIs(type(self.mutation_calls()[0]["isLeverage"]), int)
        self.assertIsInstance(receipt, SpotMarketOrderAcknowledgement)
        self.assertEqual((receipt.broker_id, receipt.broker_order_id, receipt.symbol), ("bybit-demo", "order-1", "BTCUSDT"))
        self.assertEqual((receipt.side, receipt.order_type, receipt.amount_unit, receipt.submitted_amount),
                         ("BUY", "MARKET", "QUOTE", Decimal("12.3456789")))

    def test_sell_exact_safe_sdk_parameters_and_base_receipt(self):
        receipt = self.adapter.place_market_order(sell_request())
        self.assertEqual(self.mutation_calls(), [{
            "category": "spot", "symbol": "BTCUSDT", "side": "Sell", "orderType": "Market",
            "qty": "0.123456", "marketUnit": "baseCoin", "isLeverage": 0,
        }])
        self.assertEqual((receipt.side, receipt.amount_unit, receipt.submitted_amount), ("SELL", "BASE", Decimal("0.123456")))

    def test_buy_delegates_to_existing_stage93_normalizer(self):
        original = actions.normalize_spot_market_buy_quote_amount
        with patch.object(actions, "normalize_spot_market_buy_quote_amount", wraps=original) as normalize:
            request = buy_request()
            self.adapter.place_market_order(request)
        normalize.assert_called_once()
        self.assertEqual(normalize.call_args.args[0].symbol, "BTCUSDT")
        self.assertIs(normalize.call_args.args[1], request.authorized_amount)

    def test_sell_delegates_to_existing_stage93_normalizer(self):
        original = actions.normalize_spot_market_sell_base_quantity
        with patch.object(actions, "normalize_spot_market_sell_base_quantity", wraps=original) as normalize:
            request = sell_request()
            self.adapter.place_market_order(request)
        normalize.assert_called_once()
        self.assertIs(normalize.call_args.args[1], request.authorized_amount)

    def test_placement_fetches_fresh_rules_using_existing_stage93_api(self):
        self.adapter.place_market_order(buy_request(amount="6"))
        self.session.instrument["result"]["list"][0]["lotSizeFilter"]["minOrderAmt"] = "7"
        with self.assertRaises(BybitSpotOrderConstraintError):
            self.adapter.place_market_order(buy_request(amount="6"))
        self.assertEqual(len(self.mutation_calls()), 1)
        self.assertEqual(sum(name == "get_instruments_info" for name, _ in self.session.calls), 2)

    def test_buy_below_minimum_is_not_increased_or_submitted(self):
        with self.assertRaises(BybitSpotOrderConstraintError):
            self.adapter.place_market_order(buy_request(amount="4.999"))
        self.assertEqual(self.mutation_calls(), [])

    def test_sell_above_maximum_is_not_clipped_split_or_submitted(self):
        with self.assertRaises(BybitSpotOrderConstraintError):
            self.adapter.place_market_order(sell_request(amount="83"))
        self.assertEqual(self.mutation_calls(), [])

    def test_sell_maximum_after_round_down_stays_stage93_behavior(self):
        receipt = self.adapter.place_market_order(sell_request(amount="41.5000009"))
        self.assertEqual(receipt.submitted_amount, Decimal("41.5"))
        self.assertEqual(len(self.mutation_calls()), 1)

    def test_round_down_does_not_depend_on_caller_decimal_context(self):
        with localcontext() as context:
            context.prec = 2
            context.rounding = ROUND_UP
            receipt = self.adapter.place_market_order(buy_request())
        self.assertEqual(receipt.submitted_amount, Decimal("12.3456789"))
        self.assertLessEqual(receipt.submitted_amount, buy_request().authorized_amount)

    def test_exact_int_decimal_and_string_authorizations_follow_stage93(self):
        for amount in (10, Decimal("10.000"), "1E+1"):
            self.session.calls.clear()
            with self.subTest(amount=amount):
                receipt = self.adapter.place_market_order(buy_request(amount=amount))
                self.assertEqual(receipt.submitted_amount, Decimal("10"))
                self.assertEqual(self.mutation_calls()[0]["qty"], "10")

    def test_invalid_amounts_never_reach_placement(self):
        for request in (buy_request, sell_request):
            for value in (True, 1.0, None, [], {}, "0", "-1", "NaN", "sNaN", "Infinity", " 10 "):
                self.session.calls.clear()
                with self.subTest(side=request.__name__, value=value), self.assertRaises(BybitSpotOrderConstraintError):
                    self.adapter.place_market_order(request(amount=value))
                self.assertEqual(self.mutation_calls(), [])

    def test_no_price_based_unit_conversion_or_wallet_sizing(self):
        self.session.wallet["result"]["list"][0]["totalAvailableBalance"] = "999999"
        self.adapter.place_market_order(buy_request(amount="10"))
        self.adapter.place_market_order(sell_request(amount="0.001"))
        self.assertEqual([p["qty"] for p in self.mutation_calls()], ["10", "0.001"])
        self.assertEqual({name for name, _ in self.session.calls}, {"get_instruments_info", "place_order"})

    def test_non_btc_symbol_uses_its_own_fetched_rules(self):
        self.session.instrument["result"]["list"][0].update(symbol="ETHUSDC", baseCoin="ETH", quoteCoin="USDC")
        self.adapter.place_market_order(replace(buy_request(), symbol="ETHUSDC"))
        self.assertEqual(self.session.calls[0][1]["symbol"], "ETHUSDC")
        self.assertEqual(self.mutation_calls()[0]["symbol"], "ETHUSDC")

    def test_metadata_parse_failure_prevents_submission(self):
        self.session.instrument = {"retCode": 0, "result": None}
        with self.assertRaisesRegex(BybitDemoActionError, "order not submitted"):
            self.adapter.place_market_order(buy_request())
        self.assertEqual(self.mutation_calls(), [])

    def test_metadata_transport_failure_is_safe_preflight_not_ambiguous_placement(self):
        self.session.errors["get_instruments_info"] = TimeoutError(PRIVATE_MARKER)
        with self.assertRaises(BybitDemoActionError) as error:
            self.adapter.place_market_order(buy_request())
        self.assertNotIsInstance(error.exception, BybitDemoAmbiguousActionError)
        self.assertNotIn(PRIVATE_MARKER, str(error.exception))
        self.assertTrue(error.exception.__suppress_context__)
        self.assertEqual(self.mutation_calls(), [])

    def test_invalid_symbol_side_and_unit_fail_before_any_request(self):
        changes = [{"symbol": v} for v in (None, "", "btcusdt", " BTCUSDT", [])]
        changes += [{"side": v} for v in (None, "Buy", "HOLD", [])]
        changes += [{"amount_unit": v} for v in (None, "BASE", [], "quoteCoin")]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.adapter.place_market_order(replace(buy_request(), **change))
        with self.assertRaises(ValueError):
            self.adapter.place_market_order(replace(sell_request(), amount_unit="QUOTE"))
        self.assertEqual(self.session.calls, [])

    def test_dict_or_raw_broker_request_is_not_accepted(self):
        for value in (None, {}, {"category": "linear", "qty": "1"}, "buy"):
            with self.subTest(value=value), self.assertRaises(TypeError):
                self.adapter.place_market_order(value)
        self.assertEqual(self.session.calls, [])


class OrderLinkTests(OfflineTests):
    def test_optional_caller_link_is_forwarded_unchanged_for_buy_and_sell(self):
        link = "Caller-1_ABC"
        self.session.placement = ack_response(link=link)
        for request in (buy_request(link), sell_request(link=link)):
            receipt = self.adapter.place_market_order(request)
            self.assertEqual(receipt.order_link_id, link)
            self.assertEqual(self.mutation_calls()[-1]["orderLinkId"], link)

    def test_omitted_link_is_not_generated_or_forwarded(self):
        receipt = self.adapter.place_market_order(buy_request())
        self.assertIsNone(receipt.order_link_id)
        self.assertNotIn("orderLinkId", self.mutation_calls()[0])

    def test_documented_maximum_length_and_character_format(self):
        link = "aB9_-" * 7 + "Z"
        self.assertEqual(len(link), 36)
        self.session.placement = ack_response(link=link)
        self.assertEqual(self.adapter.place_market_order(buy_request(link)).order_link_id, link)

    def test_invalid_links_fail_before_metadata_or_mutation(self):
        for value in ("", "x" * 37, " caller", "caller ", "two words", "id/1", "é", "编号", "1\n", [], 123, True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.adapter.place_market_order(buy_request(value))
        self.assertEqual(self.session.calls, [])

    def test_mismatched_link_is_unknown_outcome_without_second_placement(self):
        self.session.placement = ack_response(link="different")
        with self.assertRaises(BybitDemoActionParseError):
            self.adapter.place_market_order(buy_request("original"))
        self.assertEqual(len(self.mutation_calls()), 1)
        self.assertEqual(self.mutation_calls()[0]["orderLinkId"], "original")

    def test_missing_link_echo_when_caller_provided_it_is_rejected(self):
        self.session.placement["result"].pop("orderLinkId")
        with self.assertRaises(BybitDemoActionParseError):
            self.adapter.place_market_order(buy_request("caller"))
        self.assertEqual(len(self.mutation_calls()), 1)

    def test_unrequested_broker_link_is_not_silently_accepted(self):
        self.session.placement = ack_response(link="unexpected")
        with self.assertRaises(BybitDemoActionParseError):
            self.adapter.place_market_order(buy_request())

    def test_absent_blank_or_null_echo_is_clean_when_link_not_requested(self):
        for value in (None, ""):
            self.session.placement = ack_response(link=value)
            self.assertIsNone(self.adapter.place_market_order(buy_request()).order_link_id)
        self.session.placement["result"].pop("orderLinkId")
        self.assertIsNone(self.adapter.place_market_order(buy_request()).order_link_id)


class AcknowledgementTests(OfflineTests):
    def test_request_and_receipts_are_frozen_slotted_and_payload_free(self):
        request = buy_request()
        placement = self.adapter.place_market_order(request)
        cancellation = self.adapter.cancel_order("BTCUSDT", "order-1")
        for value, name in ((request, "side"), (placement, "side"), (cancellation, "symbol")):
            self.assertFalse(hasattr(value, "__dict__"))
            with self.assertRaises(FrozenInstanceError):
                setattr(value, name, "OTHER")
            for field in ("status", "filled_quantity", "fill_price", "execution_fee", "realized_pnl", "raw_response", "session"):
                self.assertFalse(hasattr(value, field))

    def test_broker_and_local_observation_times_are_distinct_aware_utc(self):
        before = datetime.now(timezone.utc)
        receipt = self.adapter.place_market_order(buy_request())
        after = datetime.now(timezone.utc)
        self.assertEqual(receipt.broker_timestamp, datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(milliseconds=SERVER_TIME))
        self.assertLessEqual(before, receipt.fetched_at)
        self.assertLessEqual(receipt.fetched_at, after)
        self.assertIs(receipt.fetched_at.tzinfo, timezone.utc)

    def test_integer_string_server_time_is_normalized_without_float(self):
        self.session.placement["time"] = str(SERVER_TIME)
        receipt = self.adapter.place_market_order(buy_request())
        self.assertEqual(receipt.broker_timestamp.microsecond, 200000)

    def test_missing_or_invalid_broker_id_fails_without_resend(self):
        for value in (None, "", " ", " id ", 1, [], {}):
            self.session.calls.clear()
            self.session.placement = ack_response(order_id=value)
            with self.subTest(value=value), self.assertRaises(BybitDemoActionParseError):
                self.adapter.place_market_order(buy_request())
            self.assertEqual(len(self.mutation_calls()), 1)

    def test_malformed_retcode_result_and_response_fail_without_resend(self):
        responses = [None, [], {}, {"retCode": False}, {"retCode": "0"}, {"retCode": 0.0},
                     {"retCode": 0}, {"retCode": 0, "result": []}, {"retCode": 0, "result": {}}]
        for response in responses:
            self.session.calls.clear()
            self.session.placement = response
            with self.subTest(response=response), self.assertRaises(BybitDemoActionParseError):
                self.adapter.place_market_order(buy_request())
            self.assertEqual(len(self.mutation_calls()), 1)

    def test_nonzero_broker_code_is_confirmed_rejection_and_safe(self):
        self.session.placement = {"retCode": 10001, "retMsg": PRIVATE_MARKER, "private": PRIVATE_MARKER}
        with self.assertRaises(BybitDemoOrderRejectedError) as error:
            self.adapter.place_market_order(buy_request())
        self.assertEqual((error.exception.operation, error.exception.ret_code), ("place_order", 10001))
        self.assertNotIn(PRIVATE_MARKER, str(error.exception))
        self.assertNotIsInstance(error.exception, BybitDemoAmbiguousActionError)
        self.assertEqual(len(self.mutation_calls()), 1)

    def test_invalid_or_missing_time_is_untrustworthy_not_rejection(self):
        for value in (None, True, 1.0, -1, "-1", "bad", " 1", "١", str(10**30), "9" * 5000):
            self.session.calls.clear()
            self.session.placement = ack_response()
            self.session.placement["time"] = value
            with self.subTest(type=type(value).__name__), self.assertRaises(BybitDemoActionParseError):
                self.adapter.place_market_order(buy_request())
            self.assertEqual(len(self.mutation_calls()), 1)

    def test_optional_symbol_and_category_echoes_must_match(self):
        for field, value in (("symbol", "ETHUSDT"), ("category", "linear"), ("symbol", None)):
            self.session.placement = ack_response()
            self.session.placement["result"][field] = value
            with self.subTest(field=field), self.assertRaises(BybitDemoActionParseError):
                self.adapter.place_market_order(buy_request())

    def test_matched_optional_echoes_and_extra_fields_do_not_become_state(self):
        self.session.placement["result"].update(category="spot", symbol="BTCUSDT", orderStatus="Filled", avgPrice="999", cumExecQty="123")
        receipt = self.adapter.place_market_order(buy_request())
        self.assertFalse(hasattr(receipt, "status"))
        self.assertFalse(hasattr(receipt, "average_fill_price"))

    def test_original_request_and_raw_response_preserved_on_success_and_failure(self):
        request = buy_request()
        request_before = replace(request)
        for invalid in (False, True):
            response = ack_response()
            if invalid:
                response["time"] = None
            before = deepcopy(response)
            with patch.object(self.session, "place_order", return_value=response):
                if invalid:
                    with self.assertRaises(BybitDemoActionParseError):
                        self.adapter.place_market_order(request)
                else:
                    self.adapter.place_market_order(request)
            self.assertEqual(response, before)
            self.assertEqual(request, request_before)


class AmbiguityTests(OfflineTests):
    def assert_ambiguous_once(self, error, *, cancel=False):
        method = "cancel_order" if cancel else "place_order"
        self.session.errors[method] = error
        if not cancel:
            self.session.placement = ack_response(link="caller-original")
        with self.assertRaises(BybitDemoAmbiguousActionError) as caught:
            if cancel:
                self.adapter.cancel_order("BTCUSDT", "order-1")
            else:
                self.adapter.place_market_order(buy_request("caller-original"))
        self.assertEqual(len(self.mutation_calls(method)), 1)
        self.assertNotIsInstance(caught.exception, BybitDemoOrderRejectedError)
        self.assertNotIn(PRIVATE_MARKER, str(caught.exception))
        self.assertTrue(caught.exception.__suppress_context__)
        self.assertIn("outcome unknown", str(caught.exception))
        if not cancel:
            self.assertEqual(self.mutation_calls()[0]["orderLinkId"], "caller-original")
        self.assertFalse(any(name.startswith("get_") and name != "get_instruments_info" for name, _ in self.session.calls))

    def test_timeout_has_one_placement_attempt_no_replacement_link(self):
        self.assert_ambiguous_once(requests.exceptions.ReadTimeout(PRIVATE_MARKER))

    def test_connection_reset_has_one_placement_attempt(self):
        self.assert_ambiguous_once(ConnectionResetError(PRIVATE_MARKER))

    def test_generic_sdk_failure_has_one_placement_attempt(self):
        self.assert_ambiguous_once(RuntimeError(PRIVATE_MARKER))

    def test_sdk_failed_request_is_not_misclassified_as_broker_rejection(self):
        self.assert_ambiguous_once(FailedRequestError(PRIVATE_MARKER, PRIVATE_MARKER, 400, "offline", {"secret": PRIVATE_MARKER}))

    def test_sdk_invalid_request_with_broker_code_is_safe_confirmed_rejection(self):
        self.session.errors["place_order"] = InvalidRequestError(PRIVATE_MARKER, PRIVATE_MARKER, 10001, "offline", {"secret": PRIVATE_MARKER})
        with self.assertRaises(BybitDemoOrderRejectedError) as error:
            self.adapter.place_market_order(buy_request())
        self.assertEqual(error.exception.ret_code, 10001)
        self.assertNotIn(PRIVATE_MARKER, str(error.exception))
        self.assertTrue(error.exception.__suppress_context__)
        self.assertEqual(len(self.mutation_calls()), 1)

    def test_malformed_sdk_error_code_does_not_fabricate_rejection(self):
        for code in (True, "10001", 0, None):
            self.session.calls.clear()
            self.assert_ambiguous_once(InvalidRequestError(PRIVATE_MARKER, PRIVATE_MARKER, code, "offline", None))

    def test_cancel_timeout_has_one_attempt_no_followup_read(self):
        self.assert_ambiguous_once(requests.exceptions.ReadTimeout(PRIVATE_MARKER), cancel=True)

    def test_cancel_connection_reset_has_one_attempt(self):
        self.assert_ambiguous_once(ConnectionResetError(PRIVATE_MARKER), cancel=True)

    def test_cancel_generic_sdk_failure_has_one_attempt(self):
        self.assert_ambiguous_once(RuntimeError(PRIVATE_MARKER), cancel=True)


class CancellationTests(OfflineTests):
    def test_exact_id_cancellation_and_separate_receipt(self):
        receipt = self.adapter.cancel_order("BTCUSDT", "order-1")
        self.assertEqual(self.session.calls, [("cancel_order", {"category": "spot", "symbol": "BTCUSDT", "orderId": "order-1"})])
        self.assertIsInstance(receipt, OrderCancellationAcknowledgement)
        self.assertEqual((receipt.broker_id, receipt.broker_order_id, receipt.symbol), ("bybit-demo", "order-1", "BTCUSDT"))
        self.assertFalse(hasattr(receipt, "status"))
        self.assertFalse(hasattr(receipt, "submitted_amount"))

    def test_cancel_reported_link_is_preserved_without_sending_a_link_identifier(self):
        self.session.cancellation = ack_response(link="caller-1")
        receipt = self.adapter.cancel_order("BTCUSDT", "order-1")
        self.assertEqual(receipt.order_link_id, "caller-1")
        self.assertNotIn("orderLinkId", self.mutation_calls("cancel_order")[0])

    def test_cancel_invalid_arguments_fail_before_any_call(self):
        for symbol, order_id in (("", "order-1"), ("btcusdt", "order-1"), ([], "order-1"), ("BTCUSDT", None), ("BTCUSDT", ""), ("BTCUSDT", " id "), ("BTCUSDT", [])):
            with self.subTest(symbol=symbol, order_id=order_id), self.assertRaises(ValueError):
                self.adapter.cancel_order(symbol, order_id)
        self.assertEqual(self.session.calls, [])

    def test_cancel_symbol_only_or_link_only_is_not_an_api(self):
        with self.assertRaises(TypeError):
            self.adapter.cancel_order("BTCUSDT")
        with self.assertRaises(TypeError):
            self.adapter.cancel_order("BTCUSDT", order_link_id="caller")
        self.assertEqual(self.session.calls, [])

    def test_cancel_missing_mismatched_or_malformed_id_is_unknown_without_retry(self):
        for value in (None, "", [], "other-order"):
            self.session.calls.clear()
            self.session.cancellation = ack_response(order_id=value)
            with self.subTest(value=value), self.assertRaises(BybitDemoActionParseError):
                self.adapter.cancel_order("BTCUSDT", "order-1")
            self.assertEqual(len(self.mutation_calls("cancel_order")), 1)

    def test_cancel_malformed_response_is_never_success(self):
        for response in (None, [], {}, {"retCode": False}, {"retCode": 0, "result": []}, {"retCode": 0, "result": {"orderId": "order-1"}}):
            self.session.calls.clear()
            self.session.cancellation = response
            with self.subTest(response=response), self.assertRaises(BybitDemoActionParseError):
                self.adapter.cancel_order("BTCUSDT", "order-1")
            self.assertEqual(len(self.mutation_calls("cancel_order")), 1)

    def test_cancel_already_filled_broker_rejection_is_surfaced_once(self):
        self.session.cancellation = {"retCode": 110001, "retMsg": PRIVATE_MARKER}
        with self.assertRaises(BybitDemoOrderRejectedError) as error:
            self.adapter.cancel_order("BTCUSDT", "order-1")
        self.assertEqual((error.exception.operation, error.exception.ret_code), ("cancel_order", 110001))
        self.assertNotIn(PRIVATE_MARKER, str(error.exception))
        self.assertEqual(len(self.mutation_calls("cancel_order")), 1)

    def test_cancel_sdk_broker_rejection_is_distinct_from_transport(self):
        self.session.errors["cancel_order"] = InvalidRequestError(PRIVATE_MARKER, PRIVATE_MARKER, 110001, "offline", None)
        with self.assertRaises(BybitDemoOrderRejectedError):
            self.adapter.cancel_order("BTCUSDT", "order-1")
        self.assertEqual(len(self.mutation_calls("cancel_order")), 1)

    def test_cancel_does_not_mutate_previous_partial_order_or_infer_terminal_state(self):
        self.session.realtime = [order_response([order_record(status="PartiallyFilled", filled="1")])]
        reads = BybitDemoReadOnlyAdapter(self.session)
        previous = reads.get_order("order-1")
        self.session.calls.clear()
        self.adapter.cancel_order("BTCUSDT", "order-1")
        self.assertIs(previous.status, OrderStatus.PARTIALLY_FILLED)
        self.assertEqual(previous.filled_quantity, Decimal("1"))
        self.assertEqual([name for name, _ in self.session.calls], ["cancel_order"])
        # Only a later explicit observation may show a concurrent fill instead.
        self.session.realtime = [order_response([order_record(status="Filled", filled="2")])]
        observed = reads.get_order("order-1")
        self.assertIs(observed.status, OrderStatus.FILLED)
        self.assertIs(previous.status, OrderStatus.PARTIALLY_FILLED)

    def test_cancel_timestamps_are_aware_utc(self):
        receipt = self.adapter.cancel_order("BTCUSDT", "order-1")
        self.assertEqual(receipt.broker_timestamp, datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(milliseconds=SERVER_TIME))
        self.assertIs(receipt.fetched_at.tzinfo, timezone.utc)

    def test_cancel_raw_response_is_not_modified(self):
        response = ack_response()
        before = deepcopy(response)
        with patch.object(self.session, "cancel_order", return_value=response):
            self.adapter.cancel_order("BTCUSDT", "order-1")
        self.assertEqual(response, before)


class SafetyAndArchitectureTests(OfflineTests):
    def unsafe_settings(self):
        return (("demo", False), ("demo", 1), ("testnet", True), ("testnet", 0),
                ("endpoint", "https://api.bybit.com"), ("endpoint", "https://api-testnet.bybit.com"),
                ("endpoint", "https://api-demo.bybit.com/"), ("force_retry", True),
                ("max_retries", 2), ("max_retries", 1.0), ("max_retries", True),
                ("retry_delay", 1), ("log_requests", True), ("log_requests", 0))

    def test_unsafe_or_missing_demo_session_rejected_at_construction(self):
        for field, value in self.unsafe_settings():
            session = FakeActionSession()
            setattr(session, field, value)
            with self.subTest(field=field, value=value), self.assertRaises(BybitDemoConfigurationError):
                BybitDemoOrderAdapter(session)
            self.assertEqual(session.calls, [])
        with self.assertRaises(BybitDemoConfigurationError):
            BybitDemoOrderAdapter(object())

    def test_safety_settings_rechecked_before_each_place_and_cancel(self):
        for field, value in self.unsafe_settings():
            for cancel in (False, True):
                session = FakeActionSession()
                adapter = BybitDemoOrderAdapter(session)
                setattr(session, field, value)
                with self.subTest(field=field, cancel=cancel), self.assertRaises(BybitDemoConfigurationError):
                    if cancel:
                        adapter.cancel_order("BTCUSDT", "order-1")
                    else:
                        adapter.place_market_order(buy_request())
                self.assertEqual(session.calls, [])

    def test_session_routing_changed_during_metadata_is_rejected_before_mutation(self):
        def fetch(**kwargs):
            self.session.demo = False
            return synthetic_response()
        with patch.object(self.session, "get_instruments_info", side_effect=fetch):
            with self.assertRaises(BybitDemoConfigurationError):
                self.adapter.place_market_order(buy_request())
        self.assertEqual(self.mutation_calls(), [])

    def test_missing_required_sdk_methods_fail_without_construction_io(self):
        for name in ("place_order", "cancel_order", "get_instruments_info"):
            session = FakeActionSession()
            setattr(session, name, None)
            with self.subTest(name=name), self.assertRaises(TypeError):
                BybitDemoOrderAdapter(session)
            self.assertEqual(session.calls, [])

    def test_constructor_has_no_requests_or_unsafe_repr(self):
        self.assertEqual(self.session.calls, [])
        self.assertIn("BybitDemoOrderAdapter", repr(self.adapter))
        self.assertNotIn("FakeActionSession", repr(self.adapter))
        self.assertEqual(self.adapter.__slots__, ("_session",))

    def test_only_two_public_actions_and_no_parameter_passthrough(self):
        methods = {name for name, value in inspect.getmembers(BybitDemoOrderAdapter, inspect.isfunction) if not name.startswith("_")}
        self.assertEqual(methods, {"place_market_order", "cancel_order"})
        self.assertEqual(list(inspect.signature(BybitDemoOrderAdapter).parameters), ["session"])
        self.assertEqual(list(inspect.signature(BybitDemoOrderAdapter.place_market_order).parameters), ["self", "request"])
        self.assertEqual(list(inspect.signature(BybitDemoOrderAdapter.cancel_order).parameters), ["self", "symbol", "order_id"])
        for name in ("session", "client", "amend_order", "cancel_all_orders", "replace_order", "place_batch_order"):
            self.assertFalse(hasattr(self.adapter, name))

    def test_closed_mutation_allowlist_rejects_every_other_sdk_operation(self):
        self.assertEqual(actions._MUTATION_METHODS, frozenset({"place_order", "cancel_order"}))
        for method in ("amend_order", "cancel_all_orders", "replace_order", "place_batch_order", "cancel_batch_order", "transfer", "set_leverage", "get_wallet_balance"):
            with self.subTest(method=method), self.assertRaises(BybitDemoActionError):
                self.adapter._mutate(method)
        self.assertEqual(self.session.calls, [])
        self.assertEqual(self.session.mutations, 0)

    def test_no_limit_conditional_derivative_or_arbitrary_placement_parameters(self):
        for name, value in (("category", "linear"), ("orderType", "Limit"), ("triggerPrice", "100"), ("isLeverage", 1), ("takeProfit", "200")):
            with self.subTest(name=name), self.assertRaises(TypeError):
                self.adapter.place_market_order(buy_request(), **{name: value})
        self.assertEqual(self.session.calls, [])

    def test_explicit_placement_then_explicit_read_is_only_lifecycle_composition(self):
        reads = BybitDemoReadOnlyAdapter(self.session)
        receipt = self.adapter.place_market_order(buy_request(amount="100"))
        self.assertEqual([name for name, _ in self.session.calls], ["get_instruments_info", "place_order"])
        record = order_record(status="Filled", filled="0.002")
        record.update(side="Buy", marketUnit="quoteCoin", qty="100", cumExecValue="99.9")
        self.session.realtime = [order_response([record])]
        self.session.executions = [execution_response([execution_record()])]
        state = reads.get_order(receipt.broker_order_id)
        fills = reads.get_executions(receipt.broker_order_id)
        self.assertIs(state.status, OrderStatus.FILLED)
        self.assertEqual(state.remaining_quantity, Decimal("0.1"))
        self.assertEqual(len(fills), 1)
        self.assertFalse(hasattr(receipt, "status"))

    def test_read_adapter_stays_read_only_even_when_sharing_action_capable_session(self):
        reads = BybitDemoReadOnlyAdapter(self.session)
        reads.get_account_state()
        reads.get_open_orders()
        self.session.history = order_response([order_record()])
        reads.get_order("order-1")
        reads.get_executions()
        self.assertEqual(self.mutation_calls(), [])
        self.assertEqual(self.mutation_calls("cancel_order"), [])
        self.assertFalse(hasattr(reads, "place_market_order"))
        self.assertFalse(hasattr(reads, "cancel_order"))

    def test_actions_do_not_write_wallet_snapshots_or_local_state(self):
        reads = BybitDemoReadOnlyAdapter(self.session)
        account = reads.get_account_state()
        before = deepcopy(self.session.wallet)
        self.session.calls.clear()
        self.adapter.place_market_order(buy_request())
        self.adapter.cancel_order("BTCUSDT", "order-1")
        self.assertEqual(self.session.wallet, before)
        self.assertEqual(account.total_equity, Decimal("1001.25"))
        self.assertEqual(set(self.adapter.__slots__), {"_session"})

    def test_broker_independent_models_have_only_reviewed_fields(self):
        import trading_lab.exchange.order_actions as models
        source = inspect.getsource(models)
        tree = ast.parse(source)
        imports = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        imports += [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
        for name in ("bybit", "pybit", "requests", "strategy", "backtest"):
            self.assertFalse(any(name in module for module in imports))
        self.assertEqual([f.name for f in fields(SpotMarketOrderRequest)], ["symbol", "side", "authorized_amount", "amount_unit", "order_link_id"])
        self.assertEqual([f.name for f in fields(SpotMarketOrderAcknowledgement)], ["broker_id", "broker_order_id", "order_link_id", "symbol", "side", "order_type", "submitted_amount", "amount_unit", "broker_timestamp", "fetched_at"])
        self.assertEqual([f.name for f in fields(OrderCancellationAcknowledgement)], ["broker_id", "broker_order_id", "order_link_id", "symbol", "broker_timestamp", "fetched_at"])

    def test_source_has_no_runtime_core_wiring_or_extra_mutation_dispatch(self):
        source = inspect.getsource(actions)
        tree = ast.parse(source)
        self.assertFalse(any(isinstance(node, (ast.While, ast.AsyncFunctionDef)) for node in ast.walk(tree)))
        for name in ("os.environ", "sleep(", "HTTP(", "api_key", "api_secret", "get_wallet_balance", "set_leverage", "amend_order", "cancel_all_orders", "place_batch_order", "cancel_batch_order", "transfer"):
            self.assertNotIn(name, source)
        imports = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        self.assertFalse(any(any(layer in name for layer in ("strategy", "strategies", "backtest", "risk", "execution", "database")) for name in imports))
        # The only dynamic SDK dispatch is constrained by the closed allowlist.
        dispatch = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "getattr" and ast.unparse(node.args[0]) == "self._session"]
        self.assertEqual(len(dispatch), 1)

    def test_no_print_logging_or_client_repr_in_normal_actions(self):
        with patch("builtins.print") as output, patch("logging.getLogger") as logger:
            self.adapter.place_market_order(buy_request())
            self.adapter.cancel_order("BTCUSDT", "order-1")
        output.assert_not_called()
        logger.assert_not_called()

    def test_new_explicit_package_exports_preserve_existing_wildcard_contract(self):
        for name in ("SpotMarketOrderRequest", "SpotMarketOrderAcknowledgement", "OrderCancellationAcknowledgement", "BybitDemoOrderAdapter", "BybitDemoActionError", "BybitDemoActionParseError", "BybitDemoAmbiguousActionError", "BybitDemoOrderRejectedError"):
            self.assertIs(getattr(exchange, name), globals()[name])
        self.assertEqual(set(exchange.__all__), {"BybitDemoConfigurationError", "BybitDemoCredentials", "load_bybit_demo_credentials", "create_bybit_demo_session"})

    def test_fresh_imports_do_not_read_environment_construct_sessions_or_call_api(self):
        script = textwrap.dedent("""
            import importlib, os
            from unittest.mock import patch
            import requests, pybit.unified_trading
            class NoEnvironment(dict):
                def get(self, *args): raise AssertionError('No environment reads')
                def __getitem__(self, name): raise AssertionError('No environment reads')
            with patch('os.environ', NoEnvironment()), \
                 patch('pybit.unified_trading.HTTP', side_effect=AssertionError('No sessions')), \
                 patch.object(requests.Session, 'send', side_effect=AssertionError('No network')), \
                 patch.object(requests.Session, 'request', side_effect=AssertionError('No network')):
                for name in ('trading_lab.exchange', 'trading_lab.exchange.order_actions', 'trading_lab.exchange.bybit_demo_orders'):
                    importlib.import_module(name)
        """)
        src = Path(__file__).resolve().parents[1] / "src"
        result = subprocess.run([sys.executable, "-c", script], env={"PYTHONPATH": str(src), "PYTHONDONTWRITEBYTECODE": "1"}, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")


class PinnedSDKTests(OfflineTests):
    def session_with_metadata(self):
        session = create_bybit_demo_session(BybitDemoCredentials("offline-action-key", "offline-action-secret"))
        self.addCleanup(session.client.close)
        self.enterContext(patch.object(session, "get_instruments_info", return_value=synthetic_response()))
        return session

    def test_actual_pybit_signatures_and_http_post_paths_offline(self):
        session = self.session_with_metadata()
        for method in (session.place_order, session.cancel_order):
            self.assertEqual(list(inspect.signature(method).parameters), ["kwargs"])
        calls = []
        def submit(**kwargs):
            calls.append(kwargs)
            return ack_response()
        adapter = BybitDemoOrderAdapter(session)
        with patch.object(session, "_submit_request", side_effect=submit):
            adapter.place_market_order(buy_request())
            adapter.place_market_order(sell_request())
            adapter.cancel_order("BTCUSDT", "order-1")
        self.assertEqual([call["path"] for call in calls], ["https://api-demo.bybit.com/v5/order/create"] * 2 + ["https://api-demo.bybit.com/v5/order/cancel"])
        for call in calls:
            self.assertEqual(call["method"], "POST")
            self.assertIs(call["auth"], True)
            self.assertEqual(call["query"]["category"], "spot")
        self.assertEqual(calls[0]["query"]["marketUnit"], "quoteCoin")
        self.assertEqual(calls[1]["query"]["marketUnit"], "baseCoin")
        self.assertEqual(calls[2]["query"], {"category": "spot", "symbol": "BTCUSDT", "orderId": "order-1"})

    def test_sdk_transport_failure_has_one_actual_send_for_place_and_cancel(self):
        session = self.session_with_metadata()
        adapter = BybitDemoOrderAdapter(session)
        for cancel in (False, True):
            with patch.object(session.client, "send", side_effect=requests.exceptions.ReadTimeout(PRIVATE_MARKER)) as send:
                with self.subTest(cancel=cancel), self.assertRaises(BybitDemoAmbiguousActionError):
                    if cancel:
                        adapter.cancel_order("BTCUSDT", "order-1")
                    else:
                        adapter.place_market_order(buy_request())
                send.assert_called_once()

    def test_sdk_returned_retcode_is_confirmed_rejection_without_raw_error_leak(self):
        session = self.session_with_metadata()
        response = Mock(status_code=200, headers={"private": PRIVATE_MARKER})
        response.json.return_value = {"retCode": 10001, "retMsg": PRIVATE_MARKER}
        adapter = BybitDemoOrderAdapter(session)
        for cancel in (False, True):
            with patch.object(session.client, "send", return_value=response) as send:
                with self.subTest(cancel=cancel), self.assertRaises(BybitDemoOrderRejectedError) as error:
                    if cancel:
                        adapter.cancel_order("BTCUSDT", "order-1")
                    else:
                        adapter.place_market_order(buy_request())
                self.assertEqual(error.exception.ret_code, 10001)
                self.assertNotIn(PRIVATE_MARKER, str(error.exception))
                send.assert_called_once()

    def test_sdk_retryable_code_exhausts_single_attempt_without_resend(self):
        session = self.session_with_metadata()
        response = Mock(status_code=200, headers={})
        response.json.return_value = {"retCode": 10002, "retMsg": "offline receive-window error"}
        with patch.object(session.client, "send", return_value=response) as send, patch("pybit._http_manager.time.sleep") as sleep, patch.object(session.logger, "error"):
            with self.assertRaises(BybitDemoAmbiguousActionError):
                BybitDemoOrderAdapter(session).place_market_order(buy_request())
            send.assert_called_once()
            sleep.assert_called_once_with(0)

    def test_sdk_malformed_json_is_ambiguous_without_resend(self):
        session = self.session_with_metadata()
        response = Mock(status_code=200, headers={})
        response.json.side_effect = json.JSONDecodeError("offline malformed response", "", 0)
        with patch.object(session.client, "send", return_value=response) as send:
            with self.assertRaises(BybitDemoAmbiguousActionError):
                BybitDemoOrderAdapter(session).place_market_order(buy_request())
            send.assert_called_once()


if __name__ == "__main__":
    unittest.main()
