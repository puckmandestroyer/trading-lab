"""Offline Spot metadata and Decimal normalization tests; limits are synthetic."""

from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from decimal import Decimal, ROUND_UP, localcontext
from fractions import Fraction
import inspect
from pathlib import Path
import subprocess
import sys
import textwrap
from types import MappingProxyType
import unittest
from unittest.mock import Mock, patch

import numpy as np
import requests

import trading_lab.exchange as exchange
from trading_lab.exchange.bybit_spot_rules import (
    BybitSpotInstrumentError,
    BybitSpotInstrumentRules,
    BybitSpotOrderConstraintError,
    fetch_bybit_spot_instrument_rules,
    normalize_spot_market_buy_quote_amount,
    normalize_spot_market_sell_base_quantity,
)


def synthetic_response():
    # These fixture values are not permanent or queried live exchange limits.
    return {
        "retCode": 0,
        "result": {
            "category": "spot",
            "list": [{
                "symbol": "BTCUSDT", "baseCoin": "BTC", "quoteCoin": "USDT",
                "status": "Trading",
                "lotSizeFilter": {
                    "basePrecision": "0.000001", "quotePrecision": "0.0000001",
                    "minOrderAmt": "5", "maxMarketOrderQty": "41.5",
                },
                "priceFilter": {"tickSize": "0.1"},
            }],
        },
    }


def synthetic_rules():
    return BybitSpotInstrumentRules(
        symbol="BTCUSDT", base_coin="BTC", quote_coin="USDT", status="Trading",
        base_precision=Decimal("0.000001"), quote_precision=Decimal("0.0000001"),
        min_order_amount=Decimal("5"), max_market_order_quantity=Decimal("41.5"),
        tick_size=Decimal("0.1"),
    )


class OfflineTestCase(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(requests.Session, "send", side_effect=AssertionError("No network send")))
        self.enterContext(patch.object(requests.Session, "request", side_effect=AssertionError("No network request")))


class InstrumentFetchTests(OfflineTestCase):
    def setUp(self):
        super().setUp()
        self.response = synthetic_response()
        self.record = self.response["result"]["list"][0]
        self.session = Mock(spec=["get_instruments_info"])
        self.session.get_instruments_info.return_value = self.response

    def assert_invalid_response(self):
        with self.assertRaises(BybitSpotInstrumentError):
            fetch_bybit_spot_instrument_rules(self.session, "BTCUSDT")
        self.session.get_instruments_info.assert_called_once_with(category="spot", symbol="BTCUSDT")

    def test_exact_call_and_exactly_one_call(self):
        fetch_bybit_spot_instrument_rules(self.session, "BTCUSDT")
        self.session.get_instruments_info.assert_called_once_with(category="spot", symbol="BTCUSDT")

    def test_all_normalized_fields_match_current_metadata(self):
        rules = fetch_bybit_spot_instrument_rules(self.session, "BTCUSDT")
        self.assertEqual(rules, synthetic_rules())

    def test_all_numeric_fields_are_decimal(self):
        rules = fetch_bybit_spot_instrument_rules(self.session, "BTCUSDT")
        for name in ("base_precision", "quote_precision", "min_order_amount", "max_market_order_quantity", "tick_size"):
            self.assertIs(type(getattr(rules, name)), Decimal)

    def test_rules_are_frozen(self):
        rules = fetch_bybit_spot_instrument_rules(self.session, "BTCUSDT")
        with self.assertRaises(FrozenInstanceError):
            rules.base_precision = Decimal("1")

    def test_rules_have_slots_and_only_normalized_fields(self):
        rules = fetch_bybit_spot_instrument_rules(self.session, "BTCUSDT")
        self.assertFalse(hasattr(rules, "__dict__"))
        self.assertEqual(set(rules.__slots__), {
            "symbol", "base_coin", "quote_coin", "status", "base_precision",
            "quote_precision", "min_order_amount", "max_market_order_quantity", "tick_size",
        })

    def test_other_uppercase_symbol_and_coin_pair_supported(self):
        self.record.update(symbol="ETHUSDC", baseCoin="ETH", quoteCoin="USDC")
        rules = fetch_bybit_spot_instrument_rules(self.session, "ETHUSDC")
        self.assertEqual((rules.symbol, rules.base_coin, rules.quote_coin), ("ETHUSDC", "ETH", "USDC"))
        self.session.get_instruments_info.assert_called_once_with(category="spot", symbol="ETHUSDC")

    def test_lowercase_symbol_rejected_before_client_call(self):
        with self.assertRaises(BybitSpotInstrumentError):
            fetch_bybit_spot_instrument_rules(self.session, "btcusdt")
        self.session.get_instruments_info.assert_not_called()

    def test_surrounding_whitespace_symbol_rejected_before_client_call(self):
        for symbol in (" BTCUSDT", "BTCUSDT\n", " btcusdt "):
            with self.subTest(symbol=symbol), self.assertRaises(BybitSpotInstrumentError):
                fetch_bybit_spot_instrument_rules(self.session, symbol)
        self.session.get_instruments_info.assert_not_called()

    def test_empty_or_whitespace_symbol_rejected_before_client_call(self):
        for symbol in ("", " ", "\t\n"):
            with self.subTest(symbol=symbol), self.assertRaises(BybitSpotInstrumentError):
                fetch_bybit_spot_instrument_rules(self.session, symbol)
        self.session.get_instruments_info.assert_not_called()

    def test_non_string_symbol_rejected_before_client_call(self):
        for symbol in (None, 123, True, b"BTCUSDT", []):
            with self.subTest(symbol=symbol), self.assertRaises(BybitSpotInstrumentError):
                fetch_bybit_spot_instrument_rules(self.session, symbol)
        self.session.get_instruments_info.assert_not_called()

    def test_missing_client_method_rejected(self):
        with self.assertRaisesRegex(TypeError, "get_instruments_info"):
            fetch_bybit_spot_instrument_rules(object(), "BTCUSDT")

    def test_non_callable_client_method_rejected(self):
        client = Mock(spec=["get_instruments_info"])
        client.get_instruments_info = None
        with self.assertRaises(TypeError):
            fetch_bybit_spot_instrument_rules(client, "BTCUSDT")

    def test_non_mapping_response_rejected(self):
        for value in (None, [], "response", 0):
            self.session.reset_mock()
            self.session.get_instruments_info.return_value = value
            with self.subTest(value=value):
                self.assert_invalid_response()

    def test_missing_retcode_rejected(self):
        del self.response["retCode"]
        self.assert_invalid_response()

    def test_nonzero_retcode_rejected(self):
        self.response["retCode"] = 10001
        self.assert_invalid_response()

    def test_malformed_retcode_rejected_including_bool(self):
        for value in (None, "0", False, True, 0.0, Decimal("0"), []):
            self.session.reset_mock()
            self.response["retCode"] = value
            with self.subTest(value=value):
                self.assert_invalid_response()

    def test_missing_result_rejected(self):
        del self.response["result"]
        self.assert_invalid_response()

    def test_non_mapping_result_rejected(self):
        for value in (None, [], "result"):
            self.session.reset_mock()
            self.response["result"] = value
            with self.subTest(value=value):
                self.assert_invalid_response()

    def test_missing_or_wrong_category_rejected(self):
        for value in (None, "linear", "Spot"):
            self.session.reset_mock()
            self.response["result"]["category"] = value
            with self.subTest(value=value):
                self.assert_invalid_response()

    def test_missing_list_rejected(self):
        del self.response["result"]["list"]
        self.assert_invalid_response()

    def test_non_list_collection_rejected(self):
        self.response["result"]["list"] = (self.record,)
        self.assert_invalid_response()

    def test_empty_list_rejected(self):
        self.response["result"]["list"] = []
        self.assert_invalid_response()

    def test_multiple_records_rejected_without_choosing_first(self):
        self.response["result"]["list"].append(deepcopy(self.record))
        self.assert_invalid_response()

    def test_non_mapping_record_rejected(self):
        self.response["result"]["list"] = [None]
        self.assert_invalid_response()

    def test_missing_or_mismatched_returned_symbol_rejected(self):
        for value in (None, "ETHUSDT", "btcusdt"):
            self.session.reset_mock()
            self.record["symbol"] = value
            with self.subTest(value=value):
                self.assert_invalid_response()

    def test_non_trading_or_missing_status_rejected(self):
        for value in (None, "PreLaunch", "Settled", "trading"):
            self.session.reset_mock()
            self.record["status"] = value
            with self.subTest(value=value):
                self.assert_invalid_response()

    def test_missing_base_coin_rejected(self):
        del self.record["baseCoin"]
        self.assert_invalid_response()

    def test_missing_quote_coin_rejected(self):
        del self.record["quoteCoin"]
        self.assert_invalid_response()

    def test_empty_or_invalid_coin_names_rejected(self):
        for name in ("baseCoin", "quoteCoin"):
            for value in ("", " ", None, 123):
                self.session.reset_mock()
                self.record.update(baseCoin="BTC", quoteCoin="USDT")
                self.record[name] = value
                with self.subTest(name=name, value=value):
                    self.assert_invalid_response()

    def test_missing_or_invalid_lot_size_filter_rejected(self):
        for value in (None, [], "filter"):
            self.session.reset_mock()
            self.record["lotSizeFilter"] = value
            with self.subTest(value=value):
                self.assert_invalid_response()

    def test_missing_or_invalid_price_filter_rejected(self):
        for value in (None, [], "filter"):
            self.session.reset_mock()
            self.record["priceFilter"] = value
            with self.subTest(value=value):
                self.assert_invalid_response()

    def test_each_required_current_numeric_field_missing_rejected(self):
        for filter_name, names in (
            ("lotSizeFilter", ("basePrecision", "quotePrecision", "minOrderAmt", "maxMarketOrderQty")),
            ("priceFilter", ("tickSize",)),
        ):
            for name in names:
                self.session.reset_mock()
                response = synthetic_response()
                del response["result"]["list"][0][filter_name][name]
                self.session.get_instruments_info.return_value = response
                with self.subTest(name=name):
                    self.assert_invalid_response()

    def test_invalid_decimal_metadata_rejected_for_every_numeric_field(self):
        for filter_name, names in (
            ("lotSizeFilter", ("basePrecision", "quotePrecision", "minOrderAmt", "maxMarketOrderQty")),
            ("priceFilter", ("tickSize",)),
        ):
            for name in names:
                for value in ("", "bad-decimal", "NaN", "sNaN", "Infinity", "-Infinity", "0", "-1", True, 1, 0.1, Decimal("1"), " 1 "):
                    self.session.reset_mock()
                    response = synthetic_response()
                    response["result"]["list"][0][filter_name][name] = value
                    self.session.get_instruments_info.return_value = response
                    with self.subTest(name=name, value=value):
                        self.assert_invalid_response()

    def test_decimal_metadata_preserves_digits_without_float_conversion(self):
        exact = "0.123456789012345678901234567890123456789"
        self.record["priceFilter"]["tickSize"] = exact
        rules = fetch_bybit_spot_instrument_rules(self.session, "BTCUSDT")
        self.assertEqual(rules.tick_size, Decimal(exact))

    def test_unknown_extra_fields_tolerated(self):
        self.response["unknown"] = {"ignored": True}
        self.response["result"]["nextPageCursor"] = "unused-cursor"
        self.record["unknown"] = []
        self.record["lotSizeFilter"]["maxLimitOrderQty"] = "not-a-market-rule"
        self.assertEqual(fetch_bybit_spot_instrument_rules(self.session, "BTCUSDT"), synthetic_rules())

    def test_contradictory_deprecated_fields_ignored(self):
        self.record["lotSizeFilter"].update(minOrderQty="999999", maxOrderQty="0.00000001", maxOrderAmt="1")
        rules = fetch_bybit_spot_instrument_rules(self.session, "BTCUSDT")
        self.assertEqual(rules, synthetic_rules())
        self.assertEqual(normalize_spot_market_buy_quote_amount(rules, "100"), "100")
        self.assertEqual(normalize_spot_market_sell_base_quantity(rules, "0.001"), "0.001")

    def test_deprecated_fields_do_not_replace_missing_current_fields(self):
        for missing in ("minOrderAmt", "maxMarketOrderQty"):
            self.session.reset_mock()
            response = synthetic_response()
            lot = response["result"]["list"][0]["lotSizeFilter"]
            lot.update(minOrderQty="1", maxOrderQty="100", maxOrderAmt="100")
            del lot[missing]
            self.session.get_instruments_info.return_value = response
            with self.subTest(missing=missing):
                self.assert_invalid_response()

    def test_dynamic_market_maximum_is_fetched_each_time(self):
        first_response = synthetic_response()
        second_response = synthetic_response()
        second_response["result"]["list"][0]["lotSizeFilter"]["maxMarketOrderQty"] = "20"
        self.session.get_instruments_info.side_effect = [first_response, second_response]
        first = fetch_bybit_spot_instrument_rules(self.session, "BTCUSDT")
        second = fetch_bybit_spot_instrument_rules(self.session, "BTCUSDT")
        self.assertEqual(first.max_market_order_quantity, Decimal("41.5"))
        self.assertEqual(second.max_market_order_quantity, Decimal("20"))
        self.assertEqual(self.session.get_instruments_info.call_count, 2)
        self.assertIsNot(first, second)

    def test_sdk_exception_propagates_unchanged_without_retry(self):
        expected = TimeoutError("synthetic transport error")
        self.session.get_instruments_info.side_effect = expected
        with self.assertRaises(TimeoutError) as error:
            fetch_bybit_spot_instrument_rules(self.session, "BTCUSDT")
        self.assertIs(error.exception, expected)
        self.session.get_instruments_info.assert_called_once_with(category="spot", symbol="BTCUSDT")

    def test_source_response_unchanged_on_success(self):
        before = deepcopy(self.response)
        fetch_bybit_spot_instrument_rules(self.session, "BTCUSDT")
        self.assertEqual(self.response, before)

    def test_source_response_unchanged_on_failure(self):
        self.record["lotSizeFilter"]["tickSize"] = "ignored"
        self.record["priceFilter"]["tickSize"] = "bad"
        before = deepcopy(self.response)
        self.assert_invalid_response()
        self.assertEqual(self.response, before)

    def test_read_only_mappings_are_accepted(self):
        self.record["lotSizeFilter"] = MappingProxyType(self.record["lotSizeFilter"])
        self.record["priceFilter"] = MappingProxyType(self.record["priceFilter"])
        self.response["result"]["list"] = [MappingProxyType(self.record)]
        self.response["result"] = MappingProxyType(self.response["result"])
        self.session.get_instruments_info.return_value = MappingProxyType(self.response)
        self.assertEqual(fetch_bybit_spot_instrument_rules(self.session, "BTCUSDT"), synthetic_rules())

    def test_errors_never_dump_response_or_client(self):
        class Client:
            def get_instruments_info(self, **kwargs):
                return {"retCode": 10001, "retMsg": "private-offline-marker"}

            def __repr__(self):
                raise AssertionError("Client repr must not be used")

        with patch("builtins.print") as output, patch("logging.getLogger") as logger:
            with self.assertRaises(BybitSpotInstrumentError) as error:
                fetch_bybit_spot_instrument_rules(Client(), "BTCUSDT")
            output.assert_not_called()
            logger.assert_not_called()
        self.assertNotIn("private-offline-marker", str(error.exception))

    def test_direct_rules_reject_invalid_numeric_fields(self):
        for name in ("base_precision", "quote_precision", "min_order_amount", "max_market_order_quantity", "tick_size"):
            for value in (0.1, True, Decimal("0"), Decimal("-1"), Decimal("NaN"), Decimal("Infinity")):
                with self.subTest(name=name, value=value), self.assertRaises(BybitSpotInstrumentError):
                    replace(synthetic_rules(), **{name: value})


class BuyNormalizationTests(OfflineTestCase):
    def setUp(self):
        super().setUp()
        self.rules = synthetic_rules()

    def test_valid_decimal(self):
        self.assertEqual(normalize_spot_market_buy_quote_amount(self.rules, Decimal("12.349")), "12.349")

    def test_valid_integer(self):
        self.assertEqual(normalize_spot_market_buy_quote_amount(self.rules, 10), "10")

    def test_valid_decimal_string(self):
        self.assertEqual(normalize_spot_market_buy_quote_amount(self.rules, "12.3400"), "12.34")

    def test_quote_precision_exact_value_preserved(self):
        self.assertEqual(normalize_spot_market_buy_quote_amount(self.rules, "12.3456789"), "12.3456789")

    def test_rounds_down_using_quote_precision(self):
        self.assertEqual(normalize_spot_market_buy_quote_amount(self.rules, "12.34567899"), "12.3456789")

    def test_synthetic_cent_step_never_rounds_up(self):
        rules = replace(self.rules, quote_precision=Decimal("0.01"))
        self.assertEqual(normalize_spot_market_buy_quote_amount(rules, Decimal("12.349")), "12.34")

    def test_uses_quote_precision_not_base_precision_or_tick(self):
        rules = replace(self.rules, base_precision=Decimal("1"), tick_size=Decimal("100"))
        self.assertEqual(normalize_spot_market_buy_quote_amount(rules, "5.12345679"), "5.1234567")

    def test_plain_string_removes_trailing_zeros_and_plus_sign(self):
        for amount, expected in (("+5.000", "5"), ("12.3400", "12.34"), ("500.000", "500")):
            with self.subTest(amount=amount):
                self.assertEqual(normalize_spot_market_buy_quote_amount(self.rules, amount), expected)

    def test_scientific_input_emits_plain_decimal(self):
        rules = replace(self.rules, min_order_amount=Decimal("0.000001"))
        self.assertEqual(normalize_spot_market_buy_quote_amount(rules, "1E-5"), "0.00001")

    def test_exact_minimum_accepted(self):
        self.assertEqual(normalize_spot_market_buy_quote_amount(self.rules, Decimal("5")), "5")

    def test_below_minimum_rejected_without_rounding_up(self):
        with self.assertRaises(BybitSpotOrderConstraintError):
            normalize_spot_market_buy_quote_amount(self.rules, "4.999")

    def test_rounding_below_minimum_rejected(self):
        rules = replace(self.rules, quote_precision=Decimal("0.01"), min_order_amount=Decimal("5.005"))
        with self.assertRaises(BybitSpotOrderConstraintError):
            normalize_spot_market_buy_quote_amount(rules, "5.009")

    def test_base_market_maximum_not_applied_to_quote_amount(self):
        rules = replace(self.rules, max_market_order_quantity=Decimal("0.01"))
        self.assertEqual(normalize_spot_market_buy_quote_amount(rules, "1000000"), "1000000")

    def test_zero_after_rounding_rejected(self):
        with self.assertRaisesRegex(BybitSpotOrderConstraintError, "zero"):
            normalize_spot_market_buy_quote_amount(self.rules, "0.00000001")

    def test_zero_negative_and_nonfinite_rejected(self):
        for value in (Decimal("0"), Decimal("-0"), -1, "-1", "NaN", Decimal("sNaN"), "Infinity", "-Infinity"):
            with self.subTest(value=value), self.assertRaises(BybitSpotOrderConstraintError):
                normalize_spot_market_buy_quote_amount(self.rules, value)

    def test_binary_float_bool_and_other_nonexact_types_rejected(self):
        for value in (10.0, np.float64(10), np.float32(10), True, False, np.bool_(True), 10 + 0j, None, [], {}, np.array([10]), b"10", Fraction(10)):
            with self.subTest(type=type(value).__name__), self.assertRaises(BybitSpotOrderConstraintError):
                normalize_spot_market_buy_quote_amount(self.rules, value)

    def test_empty_whitespace_and_malformed_strings_rejected(self):
        for value in ("", " ", " 10", "10\n", "bad", "1.2.3"):
            with self.subTest(value=value), self.assertRaises(BybitSpotOrderConstraintError):
                normalize_spot_market_buy_quote_amount(self.rules, value)

    def test_integral_numpy_scalar_accepted_exactly(self):
        self.assertEqual(normalize_spot_market_buy_quote_amount(self.rules, np.int64(10)), "10")

    def test_generic_non_power_of_ten_step_is_exact(self):
        rules = replace(self.rules, quote_precision=Decimal("0.025"))
        self.assertEqual(normalize_spot_market_buy_quote_amount(rules, "12.349"), "12.325")

    def test_low_decimal_context_cannot_increase_amount(self):
        rules = replace(self.rules, quote_precision=Decimal("0.01"))
        amount = Decimal("123456789012345678901234567890.019")
        with localcontext() as context:
            context.prec = 2
            context.rounding = ROUND_UP
            self.assertEqual(normalize_spot_market_buy_quote_amount(rules, amount), "123456789012345678901234567890.01")

    def test_rules_and_input_preserved_on_success_and_failure(self):
        before = replace(self.rules)
        amount = Decimal("12.34567899")
        original_tuple = amount.as_tuple()
        normalize_spot_market_buy_quote_amount(self.rules, amount)
        with self.assertRaises(BybitSpotOrderConstraintError):
            normalize_spot_market_buy_quote_amount(self.rules, "4")
        self.assertEqual(self.rules, before)
        self.assertEqual(amount.as_tuple(), original_tuple)

    def test_repeated_call_is_deterministic(self):
        outputs = [normalize_spot_market_buy_quote_amount(self.rules, "12.34567899") for _ in range(3)]
        self.assertEqual(outputs, ["12.3456789"] * 3)

    def test_normalized_amount_never_exceeds_authorization_and_is_step_multiple(self):
        rules = replace(self.rules, quote_precision=Decimal("0.025"))
        for value in ("5", "5.0249", "12.349", "999999.999"):
            with self.subTest(value=value):
                result = Decimal(normalize_spot_market_buy_quote_amount(rules, value))
                self.assertLessEqual(result, Decimal(value))
                self.assertEqual((Fraction(result) / Fraction(rules.quote_precision)).denominator, 1)

    def test_wrong_rule_type_rejected(self):
        with self.assertRaises(TypeError):
            normalize_spot_market_buy_quote_amount({}, "10")


class SellNormalizationTests(OfflineTestCase):
    def setUp(self):
        super().setUp()
        self.rules = synthetic_rules()

    def test_valid_decimal(self):
        self.assertEqual(normalize_spot_market_sell_base_quantity(self.rules, Decimal("0.123456")), "0.123456")

    def test_valid_integer(self):
        self.assertEqual(normalize_spot_market_sell_base_quantity(self.rules, 10), "10")

    def test_valid_decimal_string(self):
        self.assertEqual(normalize_spot_market_sell_base_quantity(self.rules, "0.123400"), "0.1234")

    def test_uses_base_precision_not_quote_precision_or_tick(self):
        rules = replace(self.rules, quote_precision=Decimal("1"), tick_size=Decimal("100"))
        self.assertEqual(normalize_spot_market_sell_base_quantity(rules, "0.1234569"), "0.123456")

    def test_rounding_never_increases_quantity(self):
        self.assertEqual(normalize_spot_market_sell_base_quantity(self.rules, "0.9999999"), "0.999999")

    def test_exact_market_maximum_accepted(self):
        self.assertEqual(normalize_spot_market_sell_base_quantity(self.rules, "41.5"), "41.5")

    def test_above_market_maximum_rejected_without_clipping_or_splitting(self):
        for value in ("41.500001", "83", "100"):
            with self.subTest(value=value), self.assertRaisesRegex(BybitSpotOrderConstraintError, "maxMarketOrderQty"):
                normalize_spot_market_sell_base_quantity(self.rules, value)

    def test_market_maximum_applied_after_precision_rounding(self):
        self.assertEqual(normalize_spot_market_sell_base_quantity(self.rules, "41.5000009"), "41.5")

    def test_quote_minimum_not_treated_as_base_quantity_minimum(self):
        rules = replace(self.rules, min_order_amount=Decimal("1000000"))
        self.assertEqual(normalize_spot_market_sell_base_quantity(rules, "0.00001"), "0.00001")

    def test_plain_canonical_output_including_scientific_input(self):
        for value, expected in (("+5.000", "5"), ("12.3400", "12.34"), ("1E-5", "0.00001")):
            with self.subTest(value=value):
                self.assertEqual(normalize_spot_market_sell_base_quantity(self.rules, value), expected)

    def test_zero_after_rounding_rejected(self):
        with self.assertRaisesRegex(BybitSpotOrderConstraintError, "zero"):
            normalize_spot_market_sell_base_quantity(self.rules, "0.0000001")

    def test_zero_negative_and_nonfinite_rejected(self):
        for value in (0, "-0", Decimal("-1"), Decimal("NaN"), Decimal("sNaN"), "Infinity", "-Infinity"):
            with self.subTest(value=value), self.assertRaises(BybitSpotOrderConstraintError):
                normalize_spot_market_sell_base_quantity(self.rules, value)

    def test_binary_float_bool_and_other_nonexact_types_rejected(self):
        for value in (1.0, np.float64(1), np.float32(1), True, np.bool_(True), 1 + 0j, None, [1], (1,), np.array(1), b"1", Fraction(1)):
            with self.subTest(type=type(value).__name__), self.assertRaises(BybitSpotOrderConstraintError):
                normalize_spot_market_sell_base_quantity(self.rules, value)

    def test_empty_whitespace_and_malformed_strings_rejected(self):
        for value in ("", " ", " 1", "1\n", "bad", "1.2.3"):
            with self.subTest(value=value), self.assertRaises(BybitSpotOrderConstraintError):
                normalize_spot_market_sell_base_quantity(self.rules, value)

    def test_integral_numpy_scalar_accepted_exactly(self):
        self.assertEqual(normalize_spot_market_sell_base_quantity(self.rules, np.int64(1)), "1")

    def test_generic_step_and_integer_step_supported(self):
        for step, amount, expected in (("0.025", "1.249", "1.225"), ("5", "12.9", "10"), ("0.0000010", "0.000019", "0.000019")):
            with self.subTest(step=step):
                rules = replace(self.rules, base_precision=Decimal(step))
                self.assertEqual(normalize_spot_market_sell_base_quantity(rules, amount), expected)

    def test_low_decimal_context_cannot_increase_quantity(self):
        rules = replace(self.rules, base_precision=Decimal("0.00000000000000000001"))
        with localcontext() as context:
            context.prec = 2
            context.rounding = ROUND_UP
            self.assertEqual(normalize_spot_market_sell_base_quantity(rules, "1.999999999999999999999"), "1.99999999999999999999")

    def test_rules_and_input_preserved_on_success_and_failure(self):
        before = replace(self.rules)
        quantity = Decimal("0.1234569")
        original_tuple = quantity.as_tuple()
        normalize_spot_market_sell_base_quantity(self.rules, quantity)
        with self.assertRaises(BybitSpotOrderConstraintError):
            normalize_spot_market_sell_base_quantity(self.rules, "100")
        self.assertEqual(self.rules, before)
        self.assertEqual(quantity.as_tuple(), original_tuple)

    def test_repeated_call_is_deterministic(self):
        outputs = [normalize_spot_market_sell_base_quantity(self.rules, "0.1234569") for _ in range(3)]
        self.assertEqual(outputs, ["0.123456"] * 3)

    def test_normalized_quantity_never_exceeds_authorization_and_is_step_multiple(self):
        rules = replace(self.rules, base_precision=Decimal("0.025"))
        for value in ("0.025", "0.0499", "12.349", "41.509"):
            with self.subTest(value=value):
                result = Decimal(normalize_spot_market_sell_base_quantity(rules, value))
                self.assertLessEqual(result, Decimal(value))
                self.assertEqual((Fraction(result) / Fraction(rules.base_precision)).denominator, 1)

    def test_wrong_rule_type_rejected(self):
        with self.assertRaises(TypeError):
            normalize_spot_market_sell_base_quantity({}, "1")


class PackageSafetyTests(OfflineTestCase):
    def test_six_new_apis_available_by_explicit_package_import(self):
        names = {
            "BybitSpotInstrumentError": BybitSpotInstrumentError,
            "BybitSpotOrderConstraintError": BybitSpotOrderConstraintError,
            "BybitSpotInstrumentRules": BybitSpotInstrumentRules,
            "fetch_bybit_spot_instrument_rules": fetch_bybit_spot_instrument_rules,
            "normalize_spot_market_buy_quote_amount": normalize_spot_market_buy_quote_amount,
            "normalize_spot_market_sell_base_quantity": normalize_spot_market_sell_base_quantity,
        }
        for name, expected in names.items():
            namespace = {}
            exec(f"from trading_lab.exchange import {name}", namespace)
            self.assertIs(namespace[name], expected)
            self.assertIs(getattr(exchange, name), expected)

    def test_public_signatures_have_only_reviewed_parameters(self):
        for function, names in (
            (fetch_bybit_spot_instrument_rules, ["session", "symbol"]),
            (normalize_spot_market_buy_quote_amount, ["rules", "amount"]),
            (normalize_spot_market_sell_base_quantity, ["rules", "quantity"]),
        ):
            self.assertEqual(list(inspect.signature(function).parameters), names)

    def assert_fresh_import_safe(self, module_name):
        script = textwrap.dedent("""
            import importlib
            import os
            from unittest.mock import patch
            import requests
            import pybit.unified_trading

            class NoEnvironmentReads(dict):
                def get(self, name, default=None):
                    raise AssertionError('Import must not read environment')
                def __getitem__(self, name):
                    raise AssertionError('Import must not read environment')

            with patch('os.environ', NoEnvironmentReads()):
                with patch.object(pybit.unified_trading.HTTP, 'get_instruments_info', side_effect=AssertionError('No metadata request')) as fetch:
                    with patch('pybit.unified_trading.HTTP', side_effect=AssertionError('No client construction')) as constructor:
                        with patch.object(requests.Session, 'send', side_effect=AssertionError('No network send')) as send:
                            with patch.object(requests.Session, 'request', side_effect=AssertionError('No request')) as request:
                                importlib.import_module(MODULE_NAME)
                                fetch.assert_not_called()
                                constructor.assert_not_called()
                                send.assert_not_called()
                                request.assert_not_called()
        """).replace("MODULE_NAME", repr(module_name))
        src = Path(__file__).resolve().parents[1] / "src"
        result = subprocess.run(
            [sys.executable, "-c", script],
            env={"PYTHONPATH": str(src), "PYTHONDONTWRITEBYTECODE": "1"},
            capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_package_import_requires_no_environment_client_network_or_metadata(self):
        self.assert_fresh_import_safe("trading_lab.exchange")

    def test_rules_module_import_requires_no_environment_client_network_or_metadata(self):
        self.assert_fresh_import_safe("trading_lab.exchange.bybit_spot_rules")


if __name__ == "__main__":
    unittest.main()
