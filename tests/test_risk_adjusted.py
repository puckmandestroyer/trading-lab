"""Decision 009's portfolio-clock returns, formulas, validation, and integration."""

from datetime import datetime, timezone
from pathlib import Path
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from trading_lab.analytics.risk_adjusted import (
    calculate_time_based_returns,
    summarize_risk_adjusted_performance,
)
from trading_lab.analytics.benchmark import (
    calculate_gross_buy_and_hold_benchmark,
    calculate_net_buy_and_hold_benchmark,
)
from trading_lab.analytics.equity import (
    calculate_gross_mark_to_market_equity,
    calculate_net_mark_to_market_equity,
)
from trading_lab.backtest.performance import calculate_trade_results
from trading_lab.backtest.costs import calculate_trade_results_with_costs
from trading_lab.backtest.pipeline import run_ema_execution_pipeline
from trading_lab.backtest.trades import build_trade_ledger
from trading_lab.data.market_data import load_ohlcv_csv


START = pd.Timestamp('2025-01-01', tz='UTC')
HOUR = pd.Timedelta(hours=1)
RETURN_COLUMNS = ['observation', 'period_start_time', 'period_end_time', 'starting_equity', 'ending_equity', 'period_return']
SUMMARY_COLUMNS = ['period_count', 'mean_period_return', 'period_return_std', 'annualized_volatility', 'downside_deviation', 'annualized_downside_deviation', 'sharpe_ratio', 'sortino_ratio']
RAW_BTC = Path(__file__).resolve().parents[1] / 'data/raw/BTCUSDT_1h.csv'


def equity(values=(100, 150, 75, 75, 150), times=None):
    return pd.DataFrame({
        'observation': np.arange(len(values), dtype='int64'),
        'valuation_time': pd.date_range(START, periods=len(values), freq='h') if times is None else times,
        'equity': list(values),
    })


def synthetic_candles():
    return pd.DataFrame({
        'timestamp': pd.date_range(START, periods=3, freq='h'),
        'open': [100, 110, 90], 'close': [110, 90, 120],
    })


class TimeBasedReturnTests(unittest.TestCase):
    def test_exact_schema_and_fresh_range_index(self):
        result = calculate_time_based_returns(equity())
        self.assertEqual(result.columns.tolist(), RETURN_COLUMNS)
        pd.testing.assert_index_equal(result.index, pd.RangeIndex(4))

    def test_exact_dtypes(self):
        result = calculate_time_based_returns(equity())
        self.assertEqual(str(result.observation.dtype), 'int64')
        for column in ['starting_equity', 'ending_equity', 'period_return']:
            self.assertEqual(str(result[column].dtype), 'float64')
        for column in ['period_start_time', 'period_end_time']:
            self.assertEqual(str(result[column].dtype), 'datetime64[ns, UTC]')

    def test_n_plus_one_equity_rows_produce_n_returns_without_fake_zero(self):
        for size in [2, 3, 12]:
            result = calculate_time_based_returns(equity([100] * size))
            self.assertEqual(len(result), size - 1)
            self.assertEqual(result.observation.tolist(), list(range(1, size)))

    def test_first_actual_return_and_last_period_are_retained(self):
        source = equity()
        result = calculate_time_based_returns(source)
        self.assertEqual(result.period_return.iloc[0], .5)
        self.assertEqual(result.observation.iloc[0], 1)
        self.assertEqual(result.period_start_time.iloc[0], START)
        self.assertEqual(result.period_end_time.iloc[0], START + HOUR)
        self.assertEqual(result.period_end_time.iloc[-1], source.valuation_time.iloc[-1])

    def test_simple_returns_and_adjacent_equities(self):
        result = calculate_time_based_returns(equity())
        self.assertEqual(result.period_return.tolist(), [.5, -.5, 0, 1])
        self.assertEqual(result.starting_equity.tolist(), [100, 150, 75, 75])
        self.assertEqual(result.ending_equity.tolist(), [150, 75, 75, 150])

    def test_flat_cash_periods_are_kept_as_exact_zeros(self):
        result = calculate_time_based_returns(equity([100, 100, 100, 50, 50]))
        self.assertEqual(result.period_return.tolist(), [0, 0, -.5, 0])
        self.assertEqual(len(result), 4)

    def test_positive_to_zero_final_transition_is_total_loss(self):
        self.assertEqual(calculate_time_based_returns(equity([100, 150, 0])).period_return.tolist(), [.5, -1])

    def test_zero_before_a_subsequent_observation_is_rejected(self):
        for values in [[100, 0, 0], [100, 0, 100], [0, 100]]:
            with self.subTest(values=values), self.assertRaises(ValueError):
                calculate_time_based_returns(equity(values))

    def test_dataframe_required(self):
        for source in [None, [], {}, np.array([100, 150])]:
            with self.subTest(source=type(source)), self.assertRaisesRegex(ValueError, 'DataFrame'):
                calculate_time_based_returns(source)

    def test_unique_columns_required(self):
        source = pd.concat([equity(), equity()[['equity']]], axis=1)
        with self.assertRaisesRegex(ValueError, 'unique'):
            calculate_time_based_returns(source)

    def test_required_columns_even_for_empty_input(self):
        for column in ['observation', 'valuation_time', 'equity']:
            for source in [equity().drop(columns=column), equity().iloc[:0].drop(columns=column)]:
                with self.subTest(column=column), self.assertRaisesRegex(ValueError, column):
                    calculate_time_based_returns(source)

    def test_at_least_two_equity_observations_required(self):
        for size in [0, 1]:
            with self.subTest(size=size), self.assertRaisesRegex(ValueError, 'at least two'):
                calculate_time_based_returns(equity().iloc[:size])

    def test_canonical_integer_observations_required(self):
        for values in [[1, 2, 3], [0, 2, 3], [0, 1, 1], [0, 2, 1], [0., 1., 2.], [False, 1, 2], [0, True, 2], ['0', 1, 2], [0, None, 2], [0, np.bool_(True), 2]]:
            source = equity([100] * 3)
            source['observation'] = pd.Series(values, dtype='object')
            with self.subTest(values=values), self.assertRaisesRegex(ValueError, 'observation'):
                calculate_time_based_returns(source)

    def test_missing_strings_numeric_epochs_and_unsafe_times_rejected(self):
        for value in [None, pd.NaT, np.datetime64('NaT'), '2025-01-01', 1, True, datetime(3000, 1, 1)]:
            source = equity([100, 120])
            source['valuation_time'] = pd.Series([START, value], dtype='object')
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'datetime'):
                calculate_time_based_returns(source)

    def test_times_must_be_strictly_increasing_without_sorting(self):
        for times in [[START, START], [START + HOUR, START]]:
            with self.subTest(times=times), self.assertRaisesRegex(ValueError, 'strictly increasing'):
                calculate_time_based_returns(equity([100, 120], times))

    def test_unequal_elapsed_spacing_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'equally spaced'):
            calculate_time_based_returns(equity([100, 120, 130], [START, START + HOUR, START + 3 * HOUR]))

    def test_coherent_naive_object_datetimes_are_accepted(self):
        source = equity([100, 150, 75], pd.Series([datetime(2025, 1, 1, h) for h in range(3)], dtype='object'))
        result = calculate_time_based_returns(source)
        self.assertEqual(str(result.period_start_time.dtype), 'datetime64[ns]')
        self.assertEqual(str(result.period_end_time.dtype), 'datetime64[ns]')
        self.assertEqual(result.period_return.tolist(), [.5, -.5])

    def test_aware_clocks_preserved_and_mixed_clocks_rejected(self):
        for zone in [ZoneInfo('Asia/Seoul'), timezone.utc]:
            times = pd.date_range('2025-01-01', periods=3, freq='h', tz=zone)
            result = calculate_time_based_returns(equity([100, 120, 130], times))
            self.assertEqual(result.period_end_time.dtype.tz, zone)
        bad_clocks = [
            [START, datetime(2025, 1, 1, 1)],
            [START, (START + HOUR).tz_convert('Asia/Seoul')],
            [START, (START + HOUR).tz_convert(ZoneInfo('UTC'))],
        ]
        for times in bad_clocks:
            with self.subTest(times=times), self.assertRaisesRegex(ValueError, 'timezone'):
                calculate_time_based_returns(equity([100, 120], pd.Series(times, dtype='object')))

    def test_same_zone_dst_uses_elapsed_time_for_spring_and_fall(self):
        zone = ZoneInfo('America/New_York')
        for start in ['2025-03-09 00:00', '2025-11-02 00:00']:
            times = pd.date_range(start, periods=5, freq='h', tz=zone)
            result = calculate_time_based_returns(equity([100] * 5, times))
            self.assertEqual(result.period_end_time.dtype.tz, zone)
            self.assertEqual((result.period_end_time - result.period_start_time).tolist(), [HOUR] * 4)

    def test_naive_dst_gap_is_not_silently_repaired(self):
        times = [datetime(2025, 3, 9, h) for h in [0, 1, 3]]
        with self.assertRaisesRegex(ValueError, 'equally spaced'):
            calculate_time_based_returns(equity([100] * 3, times))

    def test_equity_requires_finite_nonnegative_real_numbers_not_bools(self):
        for value in [-1, None, pd.NA, np.nan, np.inf, -np.inf, True, np.bool_(False), '100', 1 + 0j, 10 ** 400]:
            source = equity([100, 150])
            source['equity'] = pd.Series([100, value], dtype='object')
            with self.subTest(value=value), self.assertRaises(ValueError):
                calculate_time_based_returns(source)

    def test_input_preserved_with_extra_columns_reordered_columns_and_duplicate_index(self):
        source = equity()
        source['optional'] = pd.array([1, 2, None, 4, 5], dtype='Int64')
        source = source[['optional', 'equity', 'valuation_time', 'observation']]
        source.index = [8] * len(source)
        before = source.copy(deep=True)
        calculate_time_based_returns(source)
        summarize_risk_adjusted_performance(source, 8760)
        pd.testing.assert_frame_equal(source, before)

    def test_output_independence_in_both_directions(self):
        source = equity()
        before = source.copy(deep=True)
        result = calculate_time_based_returns(source)
        result.at[0, 'starting_equity'] = 999
        result.at[0, 'period_start_time'] = START + 30 * HOUR
        pd.testing.assert_frame_equal(source, before)
        independent = calculate_time_based_returns(source)
        expected = independent.copy(deep=True)
        source.at[0, 'equity'] = 1
        source.at[0, 'valuation_time'] = START - HOUR
        pd.testing.assert_frame_equal(independent, expected)

    def test_optional_columns_do_not_select_an_accounting_source(self):
        source = equity()
        source['net_trade_return'] = ['bad'] * len(source)
        source['gross_pnl'] = [np.nan] * len(source)
        pd.testing.assert_frame_equal(calculate_time_based_returns(source), calculate_time_based_returns(equity()))

    def test_appending_future_observations_preserves_every_prefix(self):
        source = equity()
        for size in [2, 3, 4]:
            pd.testing.assert_frame_equal(calculate_time_based_returns(source.iloc[:size]), calculate_time_based_returns(source).iloc[:size - 1])

    def test_changing_later_equity_cannot_change_earlier_returns(self):
        source = equity()
        later = source.copy(deep=True)
        later.at[4, 'equity'] = 999
        pd.testing.assert_frame_equal(calculate_time_based_returns(source).iloc[:3], calculate_time_based_returns(later).iloc[:3])

    def test_unrepresentable_return_arithmetic_fails_clearly(self):
        with self.assertRaisesRegex(ValueError, 'finite float64'):
            calculate_time_based_returns(equity([np.nextafter(0., 1.), 1e308]))


class RiskAdjustedSummaryTests(unittest.TestCase):
    def test_exact_schema_label_and_default_label(self):
        self.assertEqual(summarize_risk_adjusted_performance(equity(), 16).columns.tolist(), SUMMARY_COLUMNS)
        self.assertEqual(summarize_risk_adjusted_performance(equity(), 16).index.tolist(), ['PORTFOLIO'])
        self.assertEqual(summarize_risk_adjusted_performance(equity(), 16, label=' EMA NET ').index.tolist(), [' EMA NET '])

    def test_exact_summary_dtypes(self):
        summary = summarize_risk_adjusted_performance(equity(), 16)
        self.assertEqual(str(summary.period_count.dtype), 'int64')
        for column in SUMMARY_COLUMNS[1:]:
            self.assertEqual(str(summary[column].dtype), 'float64')

    def test_summary_reuses_the_single_public_return_calculation(self):
        with patch('trading_lab.analytics.risk_adjusted.calculate_time_based_returns', wraps=calculate_time_based_returns) as helper:
            source = equity()
            summarize_risk_adjusted_performance(source, 16)
            helper.assert_called_once_with(source)

    def test_arithmetic_mean_includes_flat_period(self):
        summary = summarize_risk_adjusted_performance(equity(), 16).iloc[0]
        self.assertEqual(summary.period_count, 4)
        self.assertEqual(summary.mean_period_return, .25)

    def test_standard_deviation_uses_sample_ddof_one(self):
        summary = summarize_risk_adjusted_performance(equity(), 16).iloc[0]
        expected = np.sqrt(1.25 / 3)
        self.assertAlmostEqual(summary.period_return_std, expected)
        self.assertNotAlmostEqual(summary.period_return_std, np.sqrt(1.25 / 4))

    def test_annualized_volatility_uses_explicit_square_root_basis(self):
        summary = summarize_risk_adjusted_performance(equity(), 16).iloc[0]
        self.assertAlmostEqual(summary.annualized_volatility, np.sqrt(1.25 / 3) * 4)

    def test_sharpe_formula_uses_sample_excess_std(self):
        summary = summarize_risk_adjusted_performance(equity(), 16).iloc[0]
        self.assertAlmostEqual(summary.sharpe_ratio, .25 / np.sqrt(1.25 / 3) * 4)

    def test_sortino_formula_and_annualized_downside(self):
        summary = summarize_risk_adjusted_performance(equity(), 16).iloc[0]
        self.assertEqual(summary.downside_deviation, .25)
        self.assertEqual(summary.annualized_downside_deviation, 1)
        self.assertEqual(summary.sortino_ratio, 4)

    def test_downside_mean_uses_all_periods_not_negative_subset(self):
        summary = summarize_risk_adjusted_performance(equity(), 16).iloc[0]
        self.assertEqual(summary.downside_deviation, np.sqrt(.5 ** 2 / 4))
        self.assertNotEqual(summary.downside_deviation, .5)

    def test_annualization_is_not_inferred_from_number_of_periods(self):
        small = summarize_risk_adjusted_performance(equity(), 4).iloc[0]
        large = summarize_risk_adjusted_performance(equity(), 16).iloc[0]
        for field in ['annualized_volatility', 'annualized_downside_deviation', 'sharpe_ratio', 'sortino_ratio']:
            self.assertAlmostEqual(large[field], 2 * small[field])
        self.assertEqual(large.period_count, small.period_count)

    def test_explicit_per_period_risk_free_parameter(self):
        result = summarize_risk_adjusted_performance(equity(), 16, risk_free_return_per_period=.125).iloc[0]
        self.assertAlmostEqual(result.sharpe_ratio, (.25 - .125) / np.sqrt(1.25 / 3) * 4)
        self.assertEqual(result.sortino_ratio, 4)

    def test_explicit_mar_changes_all_period_downside_and_numerator(self):
        result = summarize_risk_adjusted_performance(equity(), 16, minimum_acceptable_return_per_period=.125).iloc[0]
        expected_downside = np.sqrt((.625 ** 2 + .125 ** 2) / 4)
        self.assertAlmostEqual(result.downside_deviation, expected_downside)
        self.assertAlmostEqual(result.sortino_ratio, (.25 - .125) / expected_downside * 4)

    def test_periods_per_year_validation(self):
        for value in [0, -1, None, np.nan, np.inf, True, np.bool_(False), '8760', 1 + 0j, 10 ** 400]:
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'periods_per_year'):
                summarize_risk_adjusted_performance(equity(), value)

    def test_risk_free_parameter_validation(self):
        for value in [None, pd.NA, np.nan, np.inf, -np.inf, True, np.bool_(False), '0', 1 + 0j, 10 ** 400]:
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'risk_free'):
                summarize_risk_adjusted_performance(equity(), 8760, risk_free_return_per_period=value)

    def test_mar_parameter_validation(self):
        for value in [None, pd.NA, np.nan, np.inf, -np.inf, True, np.bool_(False), '0', 1 + 0j, 10 ** 400]:
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'minimum_acceptable'):
                summarize_risk_adjusted_performance(equity(), 8760, minimum_acceptable_return_per_period=value)

    def test_label_validation(self):
        for value in ['', '  ', None, 1, True, ['EMA']]:
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'label'):
                summarize_risk_adjusted_performance(equity(), 8760, label=value)

    def test_zero_std_positive_excess_and_no_downside_give_positive_infinity(self):
        result = summarize_risk_adjusted_performance(equity([100, 150, 225]), 8760).iloc[0]
        self.assertEqual(result.period_return_std, 0)
        self.assertEqual(result.sharpe_ratio, np.inf)
        self.assertEqual(result.sortino_ratio, np.inf)

    def test_zero_std_negative_excess_gives_negative_infinite_sharpe(self):
        result = summarize_risk_adjusted_performance(equity([100, 50, 25]), 16).iloc[0]
        self.assertEqual(result.sharpe_ratio, -np.inf)
        self.assertEqual(result.sortino_ratio, -4)

    def test_zero_excess_and_zero_downside_give_nan_ratios(self):
        result = summarize_risk_adjusted_performance(equity([100, 100, 100]), 8760).iloc[0]
        self.assertTrue(np.isnan(result.sharpe_ratio))
        self.assertTrue(np.isnan(result.sortino_ratio))
        self.assertEqual(result.annualized_volatility, 0)

    def test_single_positive_return_has_undefined_sample_std_and_sharpe(self):
        result = summarize_risk_adjusted_performance(equity([100, 150]), 16).iloc[0]
        self.assertEqual(result.period_count, 1)
        self.assertTrue(np.isnan(result.period_return_std))
        self.assertTrue(np.isnan(result.annualized_volatility))
        self.assertTrue(np.isnan(result.sharpe_ratio))
        self.assertEqual(result.sortino_ratio, np.inf)

    def test_single_negative_return_keeps_defined_downside_and_sortino(self):
        result = summarize_risk_adjusted_performance(equity([100, 0]), 16).iloc[0]
        self.assertEqual(result.downside_deviation, 1)
        self.assertEqual(result.sortino_ratio, -4)
        self.assertTrue(np.isnan(result.sharpe_ratio))

    def test_no_downside_with_variable_positive_returns_gives_infinite_sortino(self):
        result = summarize_risk_adjusted_performance(equity([100, 150, 300]), 16).iloc[0]
        self.assertTrue(np.isfinite(result.sharpe_ratio))
        self.assertEqual(result.sortino_ratio, np.inf)

    def test_zero_excess_constant_positive_returns_give_nan_sharpe(self):
        result = summarize_risk_adjusted_performance(equity([100, 150, 225]), 16, risk_free_return_per_period=.5, minimum_acceptable_return_per_period=.5).iloc[0]
        self.assertTrue(np.isnan(result.sharpe_ratio))
        self.assertTrue(np.isnan(result.sortino_ratio))

    def test_unrepresentable_summary_intermediates_rejected(self):
        for kwargs in [{'risk_free_return_per_period': 1e308}, {'periods_per_year': 1e308}]:
            source = equity([1, 1e200, 1e200]) if 'periods_per_year' in kwargs else equity()
            with self.subTest(kwargs=kwargs), self.assertRaisesRegex(ValueError, 'intermediates'):
                summarize_risk_adjusted_performance(source, **({'periods_per_year': 8760, **kwargs}))


class EquityIntegrationTests(unittest.TestCase):
    def test_existing_stage511_gross_and_net_equity_are_direct_sources(self):
        source = synthetic_candles()
        times = pd.Series([START])
        trade = pd.DataFrame({'trade_id': [1], 'entry_time': times, 'entry_price': [100.], 'exit_time': pd.Series([pd.NaT], dtype=times.dtype), 'exit_price': [np.nan], 'status': ['OPEN']})
        gross = calculate_gross_mark_to_market_equity(source, calculate_trade_results(trade, 1000), HOUR, 1000)
        net = calculate_net_mark_to_market_equity(source, calculate_trade_results_with_costs(trade, 1000, .001, .0005), HOUR, 1000)
        for path in [gross, net]:
            before = path.copy(deep=True)
            returns = calculate_time_based_returns(path)
            self.assertEqual(len(returns), 3)
            self.assertAlmostEqual(returns.period_return.iloc[-1], 120 / 90 - 1)
            self.assertEqual(summarize_risk_adjusted_performance(path, 8760).period_count.iloc[0], 3)
            pd.testing.assert_frame_equal(path, before)

    def test_existing_stage516_benchmark_equity_is_a_direct_source(self):
        source = synthetic_candles()
        for benchmark in [calculate_gross_buy_and_hold_benchmark(source, HOUR, 1000), calculate_net_buy_and_hold_benchmark(source, HOUR, 1000, .001, .0005)]:
            returns = calculate_time_based_returns(benchmark)
            self.assertEqual(len(returns), 3)
            self.assertAlmostEqual(returns.period_return.iloc[-1], 120 / 90 - 1)
            self.assertTrue(np.isfinite(summarize_risk_adjusted_performance(benchmark, 8760).iloc[0]).all())


@unittest.skipUnless(RAW_BTC.is_file(), 'Local ignored BTC snapshot is unavailable.')
class LocalBTCRiskAdjustedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.candles = load_ohlcv_csv(RAW_BTC)
        cls.candles_before = cls.candles.copy(deep=True)
        trades = build_trade_ledger(run_ema_execution_pipeline(cls.candles))
        cls.paths = {
            'EMA GROSS': calculate_gross_mark_to_market_equity(cls.candles, calculate_trade_results(trades, 10000), HOUR, 10000),
            'Buy & Hold GROSS': calculate_gross_buy_and_hold_benchmark(cls.candles, HOUR, 10000),
            'EMA NET': calculate_net_mark_to_market_equity(cls.candles, calculate_trade_results_with_costs(trades, 10000, .001, .0005), HOUR, 10000),
            'Buy & Hold NET': calculate_net_buy_and_hold_benchmark(cls.candles, HOUR, 10000, .001, .0005),
        }
        cls.before = {label: path.copy(deep=True) for label, path in cls.paths.items()}
        cls.returns = {label: calculate_time_based_returns(path) for label, path in cls.paths.items()}
        cls.summaries = {label: summarize_risk_adjusted_performance(path, 8760, label=label) for label, path in cls.paths.items()}

    def test_actual_ema_and_benchmark_period_counts_and_finite_summaries(self):
        for label, path in self.paths.items():
            with self.subTest(label=label):
                self.assertEqual(len(path), 8761)
                self.assertEqual(len(self.returns[label]), 8760)
                self.assertEqual(self.summaries[label].period_count.iloc[0], 8760)
                self.assertTrue(np.isfinite(self.summaries[label].iloc[0]).all())

    def test_all_four_equity_and_return_clocks_align_exactly(self):
        reference = self.returns['EMA GROSS']
        for label, returns in self.returns.items():
            for column in ['observation', 'period_start_time', 'period_end_time']:
                pd.testing.assert_series_equal(returns[column], reference[column])
            pd.testing.assert_series_equal(self.paths[label].valuation_time, self.paths['EMA GROSS'].valuation_time)
            self.assertEqual(returns.observation.tolist(), list(range(1, 8761)))
            self.assertEqual(returns.period_start_time.iloc[0], pd.Timestamp('2025-10-01', tz='UTC'))
            self.assertEqual(returns.period_end_time.iloc[0], pd.Timestamp('2025-10-01 01:00', tz='UTC'))
            self.assertEqual(returns.period_end_time.iloc[-1], pd.Timestamp('2026-10-01', tz='UTC'))

    def test_ema_cash_zeros_and_final_open_trade78_mark_are_retained(self):
        for label in ['EMA GROSS', 'EMA NET']:
            path = self.paths[label]
            returns = self.returns[label]
            self.assertEqual(returns.period_return.iloc[0], 0)
            self.assertGreater(returns.period_return.eq(0).sum(), 0)
            self.assertEqual(path.active_trade_id.iloc[-2:].tolist(), [78, 78])
            self.assertEqual(path.position.iloc[-2:].tolist(), [1, 1])
            self.assertAlmostEqual(returns.period_return.iloc[-1], self.candles.close.iloc[-1] / self.candles.close.iloc[-2] - 1)
            self.assertNotEqual(returns.period_return.iloc[-1], 0)

    def test_all_sources_preserved_after_return_and_summary_calls(self):
        for label, path in self.paths.items():
            pd.testing.assert_frame_equal(path, self.before[label])
        pd.testing.assert_frame_equal(self.candles, self.candles_before)
