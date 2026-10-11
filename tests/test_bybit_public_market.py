"""Offline public response, transport and atomic pagination boundary tests."""

import ast
from copy import deepcopy
from decimal import Decimal, localcontext
import inspect
import unittest
from unittest.mock import patch

import requests

import trading_lab.data.closed_candles as pure
import trading_lab.exchange.bybit_public_market as module
from trading_lab.data.closed_candles import (
    INTERVAL_MS as HOUR, MAX_TIME_MS, MarketDataContinuityError,
    MarketDataInputError, MarketDataIntegrityError, MarketDataResponseError,
    MarketDataTransportError, StaleMarketDataError,
)
from trading_lab.exchange.bybit_public_market import (
    BybitPublicMarketReader, normalize_public_klines, normalize_server_time,
)


def time_payload(ms=4 * HOUR, *, remainder_ns=0):
    return {"retCode": 0, "result": {"timeSecond": str(ms // 1000),
            "timeNano": str(ms * 1_000_000 + remainder_ns)}, "time": ms}


def row(hour=0):
    return [str(hour * HOUR), "100", "110", "90", "105", "2", "210"]


def klines(hours=(3, 2, 1, 0), *, observed_ms=4 * HOUR):
    return {"retCode": 0, "result": {"category": "spot", "symbol": "BTCUSDT",
            "list": [row(hour) for hour in hours]}, "time": observed_ms}


class Response:
    def __init__(self, payload, status=200):
        self.payload, self.status_code = payload, status

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return deepcopy(self.payload)


class PublicSession:
    """Only GET exists: private/mutation methods are deliberately unavailable."""
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []
        self.closed = False
        self.trust_env = True
        self.auth = "must-be-cleared"

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    def get(self, url, **kwargs):
        self.calls.append((url, deepcopy(kwargs)))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response if isinstance(response, Response) else Response(response)


class ServerTimeTests(unittest.TestCase):
    def test_valid_seconds_nanoseconds_and_milliseconds(self):
        ms = 1_688_639_403_423
        self.assertEqual(normalize_server_time(time_payload(ms, remainder_ns=213947)), ms)

    def test_nanosecond_floor_does_not_close_one_ms_early(self):
        self.assertEqual(normalize_server_time(time_payload(HOUR - 1, remainder_ns=999999)), HOUR - 1)

    def test_zero_time_is_not_fabricated_missing_time(self):
        self.assertEqual(normalize_server_time(time_payload(0)), 0)

    def test_missing_time_fields_fail(self):
        for field in ("timeSecond", "timeNano"):
            payload = time_payload()
            del payload["result"][field]
            with self.subTest(field=field), self.assertRaises(MarketDataResponseError):
                normalize_server_time(payload)
        payload = time_payload()
        del payload["time"]
        with self.assertRaises(MarketDataResponseError):
            normalize_server_time(payload)

    def test_invalid_integer_string_semantics_fail(self):
        for value in (None, True, 1, 1.0, "1.5", "NaN", "Infinity", "-1", "+1", " 1", "１", "9" * 400):
            for field in ("timeNano", "timeSecond"):
                payload = time_payload()
                payload["result"][field] = value
                with self.subTest(field=field, value=str(value)), self.assertRaises(MarketDataResponseError):
                    normalize_server_time(payload)

    def test_out_of_range_server_time_fails(self):
        with self.assertRaises(MarketDataResponseError):
            normalize_server_time(time_payload(MAX_TIME_MS + 1))

    def test_seconds_contradiction_fails(self):
        payload = time_payload()
        payload["result"]["timeSecond"] = "1"
        with self.assertRaises(MarketDataResponseError):
            normalize_server_time(payload)

    def test_millisecond_contradiction_fails(self):
        payload = time_payload()
        payload["time"] += 1
        with self.assertRaises(MarketDataResponseError):
            normalize_server_time(payload)

    def test_invalid_envelope_time_fails(self):
        for value in (None, True, -1, "3600000", 1.0, MAX_TIME_MS + 1):
            payload = time_payload()
            payload["time"] = value
            with self.subTest(value=value), self.assertRaises(MarketDataResponseError):
                normalize_server_time(payload)

    def test_malformed_success_shape_fails(self):
        for payload in (None, [], {}, {"retCode": False, "result": {}},
                        {"retCode": "0", "result": {}}, {"retCode": 0.0, "result": {}},
                        {"retCode": 0}, {"retCode": 0, "result": []}):
            with self.subTest(payload=payload), self.assertRaises(MarketDataResponseError):
                normalize_server_time(payload)

    def test_bybit_rejection_is_explicit_and_safe(self):
        with self.assertRaises(MarketDataTransportError) as caught:
            normalize_server_time({"retCode": 10001, "retMsg": "sensitive sentinel"})
        self.assertNotIn("sentinel", str(caught.exception))

    def test_source_response_is_preserved(self):
        payload = time_payload()
        before = deepcopy(payload)
        normalize_server_time(payload)
        self.assertEqual(payload, before)


class KlineNormalizationTests(unittest.TestCase):
    def normalize(self, payload):
        return normalize_public_klines(payload, symbol="BTCUSDT")

    def test_valid_newest_first_becomes_ascending_exact_records(self):
        page = self.normalize(klines())
        self.assertEqual([c.candle_open_ms for c in page.candles], [0, HOUR, 2 * HOUR, 3 * HOUR])
        self.assertEqual(page.candles[0].close, Decimal("105"))
        self.assertEqual(page.observed_at_ms, 4 * HOUR)

    def test_exact_duplicates_deduplicate(self):
        self.assertEqual(len(self.normalize(klines((1, 0, 1))).candles), 2)

    def test_equal_decimal_values_with_different_scale_are_identical(self):
        payload = klines((0, 0))
        payload["result"]["list"][1][1] = "100.000"
        self.assertEqual(len(self.normalize(payload).candles), 1)

    def test_conflicting_duplicate_fails(self):
        payload = klines((0, 0))
        payload["result"]["list"][1][4] = "106"
        with self.assertRaises(MarketDataIntegrityError):
            self.normalize(payload)

    def test_turnover_is_validated_but_not_an_ohlcv_field(self):
        payload = klines((0, 0))
        payload["result"]["list"][1][6] = "211"
        self.assertEqual(len(self.normalize(payload).candles), 1)
        self.assertFalse(hasattr(self.normalize(payload).candles[0], "turnover"))
        payload["result"]["list"][1][6] = "-1"
        with self.assertRaises(MarketDataIntegrityError):
            self.normalize(payload)

    def test_non_hourly_timestamp_fails(self):
        payload = klines((0,))
        payload["result"]["list"][0][0] = "1"
        with self.assertRaises(MarketDataResponseError):
            self.normalize(payload)

    def test_malformed_timestamp_strings_fail(self):
        for value in (None, True, 0, "1.1", "-1", " 0", "０", "9" * 40):
            payload = klines((0,))
            payload["result"]["list"][0][0] = value
            with self.subTest(value=value), self.assertRaises(MarketDataResponseError):
                self.normalize(payload)

    def test_wrong_symbol_category_and_optional_interval_fail(self):
        for field, value in (("symbol", "ETHUSDT"), ("category", "linear"), ("interval", "30"), ("interval", 60)):
            payload = klines()
            payload["result"][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(MarketDataResponseError):
                self.normalize(payload)

    def test_matching_optional_interval_echo_is_accepted(self):
        payload = klines()
        payload["result"]["interval"] = "60"
        self.assertEqual(len(self.normalize(payload).candles), 4)

    def test_reusable_symbol_context(self):
        payload = klines((0,))
        payload["result"]["symbol"] = "ETHUSDT"
        self.assertEqual(normalize_public_klines(payload, symbol="ETHUSDT").candles[0].symbol, "ETHUSDT")

    def test_bad_row_structure_fails(self):
        for value in (None, {}, row()[:6], row() + ["extra"], tuple(row())):
            payload = klines((0,))
            payload["result"]["list"] = [value]
            with self.subTest(value=value), self.assertRaises(MarketDataResponseError):
                self.normalize(payload)

    def test_missing_or_invalid_list_fails_but_documented_empty_page_parses(self):
        self.assertEqual(self.normalize(klines(())).candles, ())
        for value in (None, {}, "", [row()] * 1001):
            payload = klines(())
            payload["result"]["list"] = value
            with self.subTest(kind=type(value)), self.assertRaises(MarketDataResponseError):
                self.normalize(payload)

    def test_missing_page_time_fails(self):
        payload = klines()
        del payload["time"]
        with self.assertRaises(MarketDataResponseError):
            self.normalize(payload)

    def test_invalid_decimal_strings_fail(self):
        for value in (None, True, 100, 100.0, "NaN", "sNaN", "Infinity", "1e2", " 100", "+100", "100.", "１", "x", "9" * 4097):
            payload = klines((0,))
            payload["result"]["list"][0][1] = value
            with self.subTest(value=str(value)), self.assertRaises(MarketDataResponseError):
                self.normalize(payload)

    def test_invalid_prices_volume_and_bounds_fail(self):
        for index, value in ((1, "0"), (1, "-1"), (2, "80"), (3, "120"), (4, "111"), (5, "-1")):
            payload = klines((0,))
            payload["result"]["list"][0][index] = value
            with self.subTest(index=index, value=value), self.assertRaises(MarketDataIntegrityError):
                self.normalize(payload)

    def test_exact_precision_is_preserved_under_small_decimal_context(self):
        payload = klines((0,))
        price = "100.123456789012345678901234567890123456789"
        payload["result"]["list"][0][1] = price
        with localcontext() as context:
            context.prec = 2
            self.assertEqual(self.normalize(payload).candles[0].open.as_tuple(), Decimal(price).as_tuple())

    def test_response_is_not_modified(self):
        payload = klines((1, 0, 1))
        before = deepcopy(payload)
        self.normalize(payload)
        self.assertEqual(payload, before)


class PublicReaderTests(unittest.TestCase):
    def read(self, responses, **kwargs):
        self.session = PublicSession(responses)
        with patch.object(module.requests, "Session", return_value=self.session):
            return BybitPublicMarketReader().get_closed_candles(
                symbol="BTCUSDT", history_anchor_ms=0, max_data_age_ms=kwargs.pop("max_data_age_ms", 60), **kwargs)

    def test_single_page_full_history(self):
        result = self.read([time_payload(), klines()])
        self.assertEqual(len(result.candles), 4)
        self.assertEqual(result.data_age_ms, 0)
        self.assertTrue(self.session.closed)

    def test_authoritative_server_time_only_public_get(self):
        session = PublicSession([time_payload()])
        with patch.object(module.requests, "Session", return_value=session):
            self.assertEqual(BybitPublicMarketReader(timeout_seconds=3).get_server_time(), 4 * HOUR)
        self.assertEqual(session.calls, [(module.SERVER_TIME_URL, dict(params=None, timeout=3, allow_redirects=False))])
        self.assertFalse(session.trust_env)
        self.assertIsNone(session.auth)

    def test_get_parameters_are_explicit_spot_hourly_and_bounded(self):
        self.read([time_payload(), klines()], page_limit=4, max_pages=1)
        url, kwargs = self.session.calls[1]
        self.assertEqual(url, module.KLINE_URL)
        self.assertEqual(kwargs, dict(params={"category": "spot", "symbol": "BTCUSDT", "interval": "60",
                                             "start": 0, "end": 4 * HOUR, "limit": 4}, timeout=10.0, allow_redirects=False))

    def test_multipage_anchor_coverage(self):
        result = self.read([time_payload(), klines((3, 2)), klines((1, 0))], page_limit=2)
        self.assertEqual(len(result.candles), 4)
        self.assertEqual(self.session.calls[2][1]["params"]["end"], 2 * HOUR - 1)

    def test_short_page_does_not_terminate_early(self):
        self.assertEqual(len(self.read([time_payload(), klines((3,)), klines((2, 1, 0))]).candles), 4)

    def test_exact_overlap_is_deduplicated_across_pages(self):
        result = self.read([time_payload(), klines((3, 2)), klines((2, 1)), klines((1, 0))], page_limit=2)
        self.assertEqual(len(result.candles), 4)

    def test_conflicting_overlap_fails(self):
        conflict = klines((2, 1))
        conflict["result"]["list"][0][4] = "106"
        with self.assertRaises(MarketDataIntegrityError):
            self.read([time_payload(), klines((3, 2)), conflict], page_limit=2)

    def test_repeated_page_fails_without_another_read(self):
        with self.assertRaises(MarketDataContinuityError):
            self.read([time_payload(), klines((3, 2)), klines((3, 2))], page_limit=2)
        self.assertEqual(len(self.session.calls), 3)

    def test_page_budget_is_enforced(self):
        with self.assertRaises(MarketDataContinuityError):
            self.read([time_payload(), klines((3,)), klines((2,))], page_limit=2, max_pages=2)
        self.assertEqual(len(self.session.calls), 3)

    def test_unreachable_anchor_capacity_fails_before_kline_read(self):
        with self.assertRaises(MarketDataInputError):
            self.read([time_payload()], page_limit=2, max_pages=1)
        self.assertEqual(len(self.session.calls), 1)

    def test_transport_failure_after_page_success_returns_no_partial_result(self):
        with self.assertRaises(MarketDataTransportError):
            self.read([time_payload(), klines((3, 2)), requests.Timeout("sensitive sentinel")], page_limit=2)
        self.assertTrue(self.session.closed)

    def test_parse_failure_after_page_success_returns_no_partial_result(self):
        with self.assertRaises(MarketDataResponseError):
            self.read([time_payload(), klines((3, 2)), {}], page_limit=2)

    def test_empty_page_is_incomplete_coverage(self):
        with self.assertRaises(MarketDataContinuityError):
            self.read([time_payload(), klines((3, 2)), klines(())], page_limit=2)

    def test_missing_hour_missing_anchor_missing_latest_fail(self):
        for hours in ((3, 1, 0), (3, 2, 1), (2, 1, 0)):
            responses = [time_payload(), klines(hours)]
            if 0 not in hours:
                responses.append(klines(()))
            with self.subTest(hours=hours), self.assertRaises(MarketDataContinuityError):
                self.read(responses)

    def test_exact_anchor_inclusion(self):
        session = PublicSession([time_payload(), klines((3, 2))])
        with patch.object(module.requests, "Session", return_value=session):
            result = BybitPublicMarketReader().get_closed_candles(symbol="BTCUSDT", history_anchor_ms=2 * HOUR, max_data_age_ms=60)
        self.assertEqual([c.candle_open_ms for c in result.candles], [2 * HOUR, 3 * HOUR])

    def test_explicit_range_uses_exclusive_end(self):
        result = self.read([time_payload(), klines((1, 0))], end_ms=2 * HOUR, max_data_age_ms=2 * HOUR)
        self.assertEqual(result.end_ms, 2 * HOUR)
        self.assertEqual(self.session.calls[1][1]["params"]["end"], 2 * HOUR - 1)

    def test_current_forming_candle_is_not_delivered(self):
        result = self.read([time_payload(), klines((4, 3, 2, 1, 0))])
        self.assertEqual(len(result.candles), 4)
        self.assertEqual(result.candles[-1].candle_open_ms, 3 * HOUR)

    def test_boundary_does_not_advance_during_pagination(self):
        result = self.read([time_payload(4 * HOUR - 1), klines((3, 2, 1, 0), observed_ms=4 * HOUR)], max_data_age_ms=HOUR)
        self.assertEqual(len(result.candles), 3)
        self.assertEqual(result.server_time_ms, 4 * HOUR - 1)
        self.assertEqual(result.data_age_ms, HOUR)

    def test_stale_at_capture_is_rejected(self):
        with self.assertRaises(StaleMarketDataError):
            self.read([time_payload(4 * HOUR + 61), klines(observed_ms=4 * HOUR + 61)])

    def test_stale_due_to_elapsed_pagination_is_rejected(self):
        with self.assertRaises(StaleMarketDataError):
            self.read([time_payload(), klines((3, 2)), klines((1, 0), observed_ms=4 * HOUR + 61)], page_limit=2)

    def test_exact_freshness_limit_and_one_ms_later(self):
        self.assertEqual(self.read([time_payload(), klines(observed_ms=4 * HOUR + 60)]).data_age_ms, 60)
        with self.assertRaises(StaleMarketDataError):
            self.read([time_payload(), klines(observed_ms=4 * HOUR + 61)])

    def test_page_time_before_authority_fails(self):
        with self.assertRaises(MarketDataIntegrityError):
            self.read([time_payload(), klines(observed_ms=4 * HOUR - 1)])

    def test_regressing_page_observations_fail(self):
        with self.assertRaises(MarketDataIntegrityError):
            self.read([time_payload(), klines((3, 2), observed_ms=4 * HOUR + 20),
                       klines((1, 0), observed_ms=4 * HOUR + 10)], page_limit=2)

    def test_unseen_out_of_range_page_fails(self):
        for pages in ([klines((5, 0))], [klines((3, 2)), klines((4, 1, 0))]):
            with self.subTest(pages=pages), self.assertRaises(MarketDataIntegrityError):
                self.read([time_payload(), *pages])

    def test_page_cannot_exceed_requested_raw_row_limit(self):
        with self.assertRaises(MarketDataResponseError):
            self.read([time_payload(), klines((3, 2, 2))], page_limit=2)

    def test_invalid_input_blocks_transport(self):
        for kwargs in (dict(timeframe="30"), dict(end_ms=0), dict(end_ms=1), dict(page_limit=True),
                       dict(page_limit=1001), dict(max_pages=0), dict(max_pages=101), dict(max_data_age_ms=-1)):
            with self.subTest(kwargs=kwargs), self.assertRaises(MarketDataInputError):
                self.read([], **kwargs)
            self.assertEqual(self.session.calls, [])

    def test_future_range_and_unavailable_history_fail(self):
        for responses, kwargs, error in (([time_payload()], dict(end_ms=5 * HOUR), MarketDataInputError),
                                         ([time_payload(0)], {}, MarketDataContinuityError)):
            with self.subTest(kwargs=kwargs), self.assertRaises(error):
                self.read(responses, **kwargs)

    def test_bad_server_time_blocks_kline_requests(self):
        with self.assertRaises(MarketDataResponseError):
            self.read([{}])
        self.assertEqual(len(self.session.calls), 1)

    def test_transport_and_json_failures_have_safe_diagnostics(self):
        for response, error in ((requests.Timeout("sensitive sentinel"), MarketDataTransportError),
                                 (requests.ConnectionError("sensitive sentinel"), MarketDataTransportError),
                                 (Response(ValueError("sensitive sentinel")), MarketDataResponseError),
                                 (Response({"retMsg": "sensitive sentinel"}, status=500), MarketDataTransportError)):
            with self.subTest(kind=type(response)), self.assertRaises(error) as caught:
                self.read([response])
            self.assertNotIn("sentinel", str(caught.exception))
            self.assertTrue(caught.exception.__suppress_context__ or caught.exception.__context__ is None)

    def test_http_redirects_are_refused_without_following(self):
        with self.assertRaises(MarketDataTransportError):
            self.read([Response({}, status=302)])
        self.assertEqual(len(self.session.calls), 1)
        self.assertFalse(self.session.calls[0][1]["allow_redirects"])

    def test_invalid_timeout_parameters(self):
        for value in (True, None, "10", 0, -1, 31, float("nan"), float("inf"), 10**400):
            with self.subTest(value=str(value)), self.assertRaises(MarketDataInputError):
                BybitPublicMarketReader(timeout_seconds=value)

    def test_no_retry_or_resend_after_failure(self):
        with self.assertRaises(MarketDataTransportError):
            self.read([requests.Timeout("failed")])
        self.assertEqual(len(self.session.calls), 1)
        self.assertTrue(self.session.closed)

    def test_no_auth_credentials_private_reads_or_mutation(self):
        with patch("os.getenv", side_effect=AssertionError("environment read")), \
                patch("trading_lab.exchange.create_bybit_demo_session", side_effect=AssertionError("authenticated session")), \
                patch("requests.adapters.HTTPAdapter.send", side_effect=AssertionError("internet forbidden")):
            self.read([time_payload(), klines()])
        self.assertFalse(self.session.trust_env)
        self.assertIsNone(self.session.auth)
        self.assertEqual([url for url, _ in self.session.calls], [module.SERVER_TIME_URL, module.KLINE_URL])
        self.assertEqual([name for name in vars(BybitPublicMarketReader) if not name.startswith("_")],
                         ["get_server_time", "get_closed_candles"])

    def test_structural_boundary_has_no_runtime_strategy_or_storage_path(self):
        for target in (module, pure):
            tree = ast.parse(inspect.getsource(target))
            imports = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
            imports += [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
            for name in imports:
                parts = name.split(".")
                self.assertTrue(set(parts).isdisjoint({"runtime", "strategies", "backtest", "sqlite3", "time", "os"}), name)
                self.assertFalse(any(part.startswith("bybit_demo") for part in parts), name)
            calls = {node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
                     for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, (ast.Name, ast.Attribute))}
            self.assertTrue(calls.isdisjoint({"place_order", "cancel_order", "get_wallet_balance", "get_open_orders",
                                              "transition_runtime_state", "sleep", "commit", "execute", "connect", "open", "generate_ema_signals"}))
            self.assertFalse(any(isinstance(node, ast.While) for node in ast.walk(tree)))


if __name__ == "__main__":
    unittest.main()
