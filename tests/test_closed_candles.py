"""Pure closure, contiguous coverage and freshness contracts; no internet."""

from dataclasses import FrozenInstanceError
from decimal import Decimal, localcontext
import unittest

from trading_lab.data.closed_candles import (
    INTERVAL_MS as HOUR, MAX_TIME_MS, ClosedCandlePrefix, MarketCandle,
    MarketCandlePage, MarketDataContinuityError, MarketDataInputError,
    MarketDataIntegrityError, StaleMarketDataError,
    validate_candle_freshness, validate_closed_prefix,
)


def candle(hour=0, **changes):
    values = dict(symbol="BTCUSDT", timeframe="60", candle_open_ms=hour * HOUR,
                  open=Decimal("100"), high=Decimal("110"), low=Decimal("90"),
                  close=Decimal("105"), volume=Decimal("2"))
    values.update(changes)
    return MarketCandle(**values)


def prefix(candles, server_ms, **kwargs):
    return validate_closed_prefix(candles, symbol="BTCUSDT", history_anchor_ms=0,
                                  server_time_ms=server_ms, **kwargs)


class ClosedCandleTests(unittest.TestCase):
    def test_one_ms_before_close_excludes_candle(self):
        result = prefix((candle(),), HOUR - 1)
        self.assertEqual(result.candles, ())
        self.assertEqual(result.end_ms, 0)
        self.assertIsNone(result.data_age_ms)

    def test_exact_close_boundary_includes_candle(self):
        self.assertEqual(prefix((candle(),), HOUR).candles, (candle(),))

    def test_one_ms_after_close_includes_candle(self):
        result = prefix((candle(),), HOUR + 1)
        self.assertEqual(result.candles, (candle(),))
        self.assertEqual(result.data_age_ms, 1)

    def test_forming_and_future_candles_are_excluded(self):
        self.assertEqual(prefix((candle(), candle(1), candle(2)), HOUR + 1).candles, (candle(),))

    def test_output_and_candles_are_immutable(self):
        result = prefix((candle(),), HOUR)
        for instance, field, value in ((result, "end_ms", 0), (result.candles[0], "close", Decimal("106"))):
            with self.assertRaises(FrozenInstanceError):
                setattr(instance, field, value)
        self.assertFalse(hasattr(result, "__dict__"))

    def test_requires_every_hour_not_just_latest(self):
        with self.assertRaises(MarketDataContinuityError):
            prefix((candle(), candle(2)), 3 * HOUR)

    def test_missing_anchor_fails(self):
        with self.assertRaises(MarketDataContinuityError):
            prefix((candle(1),), 2 * HOUR)

    def test_missing_latest_closed_candle_fails(self):
        with self.assertRaises(MarketDataContinuityError):
            prefix((candle(),), 2 * HOUR)

    def test_empty_required_history_fails(self):
        with self.assertRaises(MarketDataContinuityError):
            prefix((), HOUR)

    def test_unsorted_normalized_input_is_not_repaired(self):
        with self.assertRaises(MarketDataIntegrityError):
            prefix((candle(1), candle()), 2 * HOUR)

    def test_duplicate_normalized_input_is_not_repaired(self):
        with self.assertRaises(MarketDataIntegrityError):
            prefix((candle(), candle()), HOUR)

    def test_closed_candle_before_anchor_fails(self):
        with self.assertRaises(MarketDataIntegrityError):
            validate_closed_prefix((candle(), candle(1)), symbol="BTCUSDT",
                                   history_anchor_ms=HOUR, server_time_ms=2 * HOUR)

    def test_explicit_historical_range(self):
        result = prefix((candle(), candle(1)), 10 * HOUR, end_ms=2 * HOUR)
        self.assertEqual(result.end_ms, 2 * HOUR)
        self.assertEqual(result.data_age_ms, 8 * HOUR)

    def test_explicit_range_cannot_hide_extra_closed_candles(self):
        with self.assertRaises(MarketDataIntegrityError):
            prefix((candle(), candle(1)), 2 * HOUR, end_ms=HOUR)

    def test_invalid_explicit_times_fail(self):
        for value in (None, True, -1, 1.0, "3600000", MAX_TIME_MS + 1):
            with self.subTest(value=value), self.assertRaises(MarketDataInputError):
                prefix((candle(),), value)

    def test_invalid_range_boundaries_fail(self):
        for anchor, end in ((1, HOUR), (HOUR, 0), (0, HOUR + 1), (0, 2 * HOUR)):
            with self.subTest(anchor=anchor, end=end), self.assertRaises(MarketDataInputError):
                validate_closed_prefix((), symbol="BTCUSDT", history_anchor_ms=anchor,
                                       end_ms=end, server_time_ms=HOUR)

    def test_invalid_symbol_timeframe_and_context_fail(self):
        for symbol, timeframe in (("btcusdt", "60"), ("BTC/USDT", "60"), ("ＢＴＣ", "60"),
                                  ("BTCUSDT", "30"), ("BTCUSDT", 60)):
            with self.subTest(symbol=symbol, timeframe=timeframe), self.assertRaises(MarketDataInputError):
                MarketCandle(symbol, timeframe, 0, *([Decimal("1")] * 5))
        with self.assertRaises(MarketDataIntegrityError):
            prefix((candle(symbol="ETHUSDT"),), HOUR)

    def test_hourly_grid_and_time_range(self):
        for timestamp in (1, -HOUR, True, "0", MAX_TIME_MS):
            with self.subTest(timestamp=timestamp), self.assertRaises(MarketDataInputError):
                candle(candle_open_ms=timestamp)

    def test_nonpositive_prices_fail(self):
        for field in ("open", "high", "low", "close"):
            for value in (Decimal("0"), Decimal("-1")):
                with self.subTest(field=field, value=value), self.assertRaises(MarketDataIntegrityError):
                    candle(**{field: value})

    def test_volume_zero_is_valid_but_negative_fails(self):
        self.assertEqual(candle(volume=Decimal("0")).volume, Decimal("0"))
        with self.assertRaises(MarketDataIntegrityError):
            candle(volume=Decimal("-1"))

    def test_non_decimal_nonfinite_and_excessive_values_fail(self):
        for value in (100, 100.0, True, "100", Decimal("NaN"), Decimal("sNaN"),
                      Decimal("Infinity"), Decimal("-Infinity"), Decimal("1e-5000")):
            with self.subTest(value=str(value)), self.assertRaises(MarketDataIntegrityError):
                candle(open=value)

    def test_ohlc_bounds_fail_without_repair(self):
        for fields in (dict(high=Decimal("99")), dict(low=Decimal("106")), dict(close=Decimal("111")),
                       dict(high=Decimal("80"), low=Decimal("120"))):
            with self.subTest(fields=fields), self.assertRaises(MarketDataIntegrityError):
                candle(**fields)

    def test_exact_decimals_do_not_use_context_rounding(self):
        price = Decimal("100.123456789012345678901234567890123456789")
        with localcontext() as context:
            context.prec = 3
            record = candle(open=price, close=price)
            self.assertEqual(record.open.as_tuple(), price.as_tuple())

    def test_page_and_prefix_cannot_hold_mutable_sequences(self):
        with self.assertRaises(MarketDataIntegrityError):
            MarketCandlePage("BTCUSDT", "60", HOUR, [candle()])
        with self.assertRaises(MarketDataIntegrityError):
            ClosedCandlePrefix("BTCUSDT", "60", 0, HOUR, HOUR, HOUR, [candle()])

    def test_page_observation_must_not_predate_closure_authority(self):
        with self.assertRaises(MarketDataInputError):
            prefix((candle(),), HOUR, observed_at_ms=HOUR - 1)

    def test_age_uses_latest_page_time(self):
        result = prefix((candle(),), HOUR, observed_at_ms=HOUR + 50)
        self.assertEqual(result.server_time_ms, HOUR)
        self.assertEqual(result.data_age_ms, 50)

    def test_warmup_plus_eligible_row_history_without_strategy(self):
        source = tuple(candle(hour) for hour in range(51))
        self.assertEqual(prefix(source, 51 * HOUR).candles, source)

    def test_observation_matches_frozen_durable_candle_contract(self):
        # Constructing the durable record is pure: no lock/database is opened.
        from trading_lab.runtime.store import CandleRecord
        observation = candle()
        durable = CandleRecord(observation.symbol, observation.timeframe, observation.candle_open_ms,
                               "a" * 64, observation.open, observation.high, observation.low,
                               observation.close, observation.volume)
        for field in ("symbol", "timeframe", "candle_open_ms", "open", "high", "low", "close", "volume"):
            self.assertEqual(getattr(observation, field), getattr(durable, field))


class FreshnessTests(unittest.TestCase):
    def check(self, server_ms, limit):
        return validate_candle_freshness(newest_closed_candle_open_ms=0,
                                        server_time_ms=server_ms, max_data_age_ms=limit)

    def test_fresh_closed_candle(self):
        self.assertEqual(self.check(HOUR + 20, 60), 20)

    def test_exact_allowed_age_is_accepted(self):
        self.assertEqual(self.check(HOUR + 60, 60), 60)

    def test_one_ms_beyond_allowed_age_is_stale(self):
        with self.assertRaises(StaleMarketDataError):
            self.check(HOUR + 61, 60)

    def test_server_before_close_is_invalid_not_fresh(self):
        with self.assertRaises(MarketDataInputError):
            self.check(HOUR - 1, 60)

    def test_zero_limit_requires_exact_boundary(self):
        self.assertEqual(self.check(HOUR, 0), 0)
        with self.assertRaises(StaleMarketDataError):
            self.check(HOUR + 1, 0)

    def test_invalid_freshness_limit_is_rejected(self):
        for value in (-1, True, 1.0, None, "60", MAX_TIME_MS + 1):
            with self.subTest(value=value), self.assertRaises(MarketDataInputError):
                self.check(HOUR, value)


if __name__ == "__main__":
    unittest.main()
