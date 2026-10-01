"""Offline checks for pagination, response errors, and raw snapshot integrity."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import pandas as pd
import requests

from trading_lab.data.market_data import (
    OHLCV_COLUMNS, download_ohlcv, load_ohlcv_csv, normalize_klines,
    save_ohlcv, validate_ohlcv,
)
from trading_lab.exchange.bybit_market_data import fetch_kline_page


START = pd.Timestamp("2025-01-01", tz="UTC")
END = START + pd.Timedelta(hours=4)


def candle(hour):
    timestamp = START + pd.Timedelta(hours=hour)
    return [str(timestamp.value // 1_000_000), "100", "110", "90", "105", "2", "210"]


class MarketDataTests(unittest.TestCase):
    def setUp(self):
        self.df = normalize_klines([candle(hour) for hour in range(4)])

    def test_normalization_sorts_and_converts_types(self):
        df = normalize_klines([candle(1), candle(0)])
        self.assertEqual(list(df.columns), OHLCV_COLUMNS)
        self.assertEqual(str(df.timestamp.dtype), "datetime64[ns, UTC]")
        self.assertTrue(df.timestamp.is_monotonic_increasing)
        self.assertTrue(all(str(df[column].dtype) == "float64" for column in OHLCV_COLUMNS[1:]))

    def test_identical_duplicates_warn_and_conflicting_duplicates_fail(self):
        with self.assertWarnsRegex(UserWarning, "Removed 1 identical"):
            df = normalize_klines([candle(0), candle(0)])
        self.assertEqual(len(df), 1)
        self.assertEqual(df.attrs["duplicate_rows_removed"], 1)
        changed = candle(0)
        changed[4] = "106"
        with self.assertRaisesRegex(ValueError, "Conflicting duplicate"):
            normalize_klines([candle(0), changed])

    def test_bad_numeric_and_fractional_timestamps_fail(self):
        bad = candle(0)
        bad[1] = "not-a-price"
        with self.assertRaisesRegex(ValueError, "Cannot normalize"):
            normalize_klines([bad])
        bad = candle(0)
        bad[0] += ".5"
        with self.assertRaisesRegex(ValueError, "Invalid millisecond"):
            normalize_klines([bad])

    def test_pagination_uses_oldest_timestamp_without_overlap(self):
        pages = [[candle(3), candle(2)], [candle(1), candle(0)]]
        with patch("trading_lab.data.market_data.fetch_kline_page", side_effect=pages) as fetch:
            with patch("trading_lab.data.market_data.time.sleep"):
                df = download_ohlcv(start=START, end=END, page_limit=2)
        self.assertEqual(len(df), 4)
        self.assertEqual(df.attrs["pages_downloaded"], 2)
        self.assertEqual(fetch.call_args_list[0].kwargs["end_ms"], END.value // 1_000_000 - 1)
        self.assertEqual(fetch.call_args_list[1].kwargs["end_ms"], int(candle(2)[0]) - 1)

    def test_short_pages_do_not_end_pagination_prematurely(self):
        pages = [[candle(3)], [candle(2), candle(1), candle(0)]]
        with patch("trading_lab.data.market_data.fetch_kline_page", side_effect=pages):
            with patch("trading_lab.data.market_data.time.sleep"):
                df = download_ohlcv(start=START, end=END)
        self.assertEqual(len(df), 4)

    def test_empty_or_incomplete_api_history_fails(self):
        for pages in ([[]], [[candle(3), candle(2)], []]):
            with self.subTest(pages=pages):
                with patch("trading_lab.data.market_data.fetch_kline_page", side_effect=pages):
                    with patch("trading_lab.data.market_data.time.sleep"):
                        with self.assertRaises(ValueError):
                            download_ohlcv(start=START, end=END)

    def test_out_of_range_page_fails_without_looping(self):
        with patch("trading_lab.data.market_data.fetch_kline_page", return_value=[candle(4)]):
            with self.assertRaisesRegex(RuntimeError, "outside the requested"):
                download_ohlcv(start=START, end=END)

    def test_internal_and_boundary_gaps_fail(self):
        for hours in ([0, 2, 3], [1, 2, 3], [0, 1, 2]):
            with self.subTest(hours=hours):
                df = normalize_klines([candle(hour) for hour in hours])
                with self.assertRaisesRegex(ValueError, "Missing candles: 1"):
                    validate_ohlcv(df, start=START, end=END)

    def test_invalid_values_report_rows_without_dropping_them(self):
        cases = [("high", 80), ("low", 120), ("volume", -1), ("open", 0),
                 ("close", float("nan")), ("volume", float("inf"))]
        for column, value in cases:
            with self.subTest(column=column, value=value):
                df = self.df.copy()
                df.loc[0, column] = value
                with self.assertRaisesRegex(ValueError, "OHLCV validation failed"):
                    validate_ohlcv(df)
                self.assertEqual(len(df), 4)

    def test_missing_columns_duplicates_and_unsorted_rows_fail(self):
        for df in (self.df.drop(columns="volume"), pd.concat([self.df, self.df.iloc[:1]]),
                   self.df.iloc[::-1]):
            with self.assertRaises(ValueError):
                validate_ohlcv(df)

    def test_misaligned_dates_unsupported_intervals_and_open_candles_fail(self):
        with self.assertRaisesRegex(ValueError, "align"):
            download_ohlcv(start=START + pd.Timedelta(minutes=1), end=END)
        with self.assertRaisesRegex(ValueError, "Unsupported interval"):
            download_ohlcv(start=START, end=END, interval="M")
        with self.assertRaisesRegex(ValueError, "currently open"):
            download_ohlcv(start=START, end=pd.Timestamp.now(tz="UTC").ceil("h") + pd.Timedelta(hours=1))

    def test_snapshot_round_trip_and_overwrite_protection(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshot.csv"
            save_ohlcv(self.df, path)
            original = path.read_bytes()
            loaded = load_ohlcv_csv(path, start=START, end=END)
            pd.testing.assert_frame_equal(self.df, loaded)
            with self.assertRaises(FileExistsError):
                save_ohlcv(self.df, path)
            self.assertEqual(path.read_bytes(), original)
            with self.assertRaisesRegex(ValueError, "Expected exactly"):
                save_ohlcv(self.df.assign(signal="BUY"), Path(directory) / "bad.csv")
            self.assertFalse((Path(directory) / "bad.csv").exists())

    def test_api_errors_and_malformed_responses_are_clear(self):
        session = Mock()
        response = session.get.return_value
        kwargs = dict(category="spot", symbol="BTCUSDT", interval="60", start_ms=0, end_ms=1)
        for payload in ({"retCode": 10001, "retMsg": "bad request"}, {},
                        {"retCode": 0, "result": {"symbol": "ETHUSDT", "category": "spot", "list": []}},
                        {"retCode": 0, "result": {"symbol": "BTCUSDT", "category": "spot", "list": [["0"]]}}):
            response.json.return_value = payload
            with self.assertRaises(RuntimeError):
                fetch_kline_page(session, **kwargs)
        response.json.side_effect = ValueError("bad JSON")
        with self.assertRaisesRegex(RuntimeError, "invalid JSON"):
            fetch_kline_page(session, **kwargs)
        session.get.side_effect = requests.Timeout("timed out")
        with self.assertRaisesRegex(RuntimeError, "request failed"):
            fetch_kline_page(session, **kwargs)


if __name__ == "__main__":
    unittest.main()
