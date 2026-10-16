"""Stage 11.2 pure policy tests; all amounts/marks/limits are synthetic."""

import ast
from copy import deepcopy
from dataclasses import MISSING, FrozenInstanceError, fields, replace
from decimal import (
    Decimal, Inexact, ROUND_DOWN, ROUND_UP, Rounded, Underflow, localcontext,
)
import inspect
import unittest

import trading_lab.risk.runtime_risk as module
from trading_lab.risk.runtime_risk import (
    DAY_MS, HOUR_MS, RiskActionKind, RiskActionProposal, RiskBook, RiskEvaluation,
    RiskExecution, RiskExecutionSide, RiskReason, RiskState, RiskVerdict,
    RuntimeRiskConfiguration, RuntimeRiskError, advance_risk_state,
    apply_owned_execution, calculate_projected_exposure, calculate_risk_equity,
    evaluate_risk, initial_risk_book, initialize_risk_state,
)


D = Decimal
HOUR = HOUR_MS
DAY = DAY_MS


def config(**changes):
    return replace(RuntimeRiskConfiguration(
        D("1000"), D("100"), D("200"), D("500"), D("0.1"), D("0.2"),
        2, "BTC", "USDT",
    ), **changes)


def execution(**changes):
    return replace(RiskExecution("fill-1", RiskExecutionSide.BUY, D("2"),
                                 D("100"), D("0"), None, 123), **changes)


def entry(amount="100"):
    return RiskActionProposal(RiskActionKind.ENTRY, D(amount))


def exit_proposal(amount="1"):
    return RiskActionProposal(RiskActionKind.EXIT, D(amount))


def initial(*, equity="1000", at=0, cfg=None):
    return initialize_risk_state(cfg or config(), RiskBook(D(equity), D(0)), D(1), at)


def next_equity(previous, equity, *, cfg=None):
    return advance_risk_state(cfg or config(), previous, RiskBook(D(equity), D(0)),
                              D(1), previous.valued_at_ms + HOUR)


def evaluate(state, proposal=None, *, cfg=None, book=None, mark=D(1)):
    return evaluate_risk(cfg or config(), state,
                         book if book is not None else RiskBook(state.risk_equity, D(0)),
                         mark, proposal)


class ConfigurationTests(unittest.TestCase):
    def test_explicit_configuration_has_no_deployment_defaults(self):
        self.assertTrue(all(field.default is MISSING and field.default_factory is MISSING
                            for field in fields(RuntimeRiskConfiguration)))
        self.assertEqual(config().base_currency, "BTC")

    def test_all_cap_equalities_are_accepted(self):
        value = config(buy_quote_budget=D(1000), max_entry_notional_quote=D(1000),
                       max_position_notional_quote=D(1000))
        self.assertEqual(value.risk_capital_quote, value.buy_quote_budget)

    def test_fraction_one_is_accepted(self):
        value = config(max_daily_loss_fraction=D(1), max_drawdown_fraction=D(1))
        self.assertEqual(value.max_drawdown_fraction, D(1))

    def test_all_financial_fields_require_exact_decimal(self):
        class DecimalChild(Decimal):
            pass
        for name in ("risk_capital_quote", "buy_quote_budget", "max_entry_notional_quote",
                     "max_position_notional_quote", "max_daily_loss_fraction", "max_drawdown_fraction"):
            for value in (True, False, 1, 0.1, "0.1", None, DecimalChild("0.1")):
                with self.subTest(field=name, kind=type(value)), self.assertRaises(RuntimeRiskError):
                    config(**{name: value})

    def test_nonpositive_and_nonfinite_financial_configuration_is_rejected(self):
        for name in ("risk_capital_quote", "buy_quote_budget", "max_entry_notional_quote",
                     "max_position_notional_quote", "max_daily_loss_fraction", "max_drawdown_fraction"):
            for value in (D(0), D("-0"), D("-0.1"), D("NaN"), D("sNaN"), D("Infinity"), D("-Infinity")):
                with self.subTest(field=name, value=value), self.assertRaises(RuntimeRiskError):
                    config(**{name: value})

    def test_each_cap_relation_rejects_one_quantum_beyond(self):
        for changes in (
            {"buy_quote_budget": D("200.0000000000000000000000000001")},
            {"max_entry_notional_quote": D("500.0000000000000000000000000001")},
            {"max_position_notional_quote": D("1000.000000000000000000000000001")},
        ):
            with self.subTest(changes=changes), self.assertRaises(RuntimeRiskError):
                config(**changes)

    def test_fractions_above_one_are_rejected(self):
        for name in ("max_daily_loss_fraction", "max_drawdown_fraction"):
            with self.subTest(field=name), self.assertRaises(RuntimeRiskError):
                config(**{name: D("1.0000000000000000000000000001")})

    def test_entry_limit_requires_positive_python_int(self):
        for value in (0, -1, True, False, 1.0, D(1), "1", None):
            with self.subTest(value=value), self.assertRaises(RuntimeRiskError):
                config(max_entries_per_utc_day=value)

    def test_unsafe_currency_text_is_rejected(self):
        for name in ("base_currency", "quote_currency"):
            for value in ("", "btc", " BTC", "BTC\n", "B-TC", "БТС", "123", 123, None, "A" * 65):
                with self.subTest(field=name, value=value), self.assertRaises(RuntimeRiskError):
                    config(**{name: value})

    def test_equal_currencies_are_rejected(self):
        with self.assertRaises(RuntimeRiskError):
            config(quote_currency="BTC")

    def test_other_explicit_currencies_are_supported(self):
        self.assertEqual(config(base_currency="ETH", quote_currency="USDC").quote_currency, "USDC")

    def test_plain_decimal_size_bound_is_explicit(self):
        for value in (D("1e4094"), D("1e-4094")):
            with self.subTest(value=value), self.assertRaises(RuntimeRiskError):
                config(risk_capital_quote=value)


class ExecutionRecordTests(unittest.TestCase):
    def test_execution_preserves_exact_values(self):
        value = execution(executed_base_quantity=D("0.12345678901234567890123456789"),
                          execution_fee=D("-0.00000000000000000000000000001"), fee_currency="BTC")
        self.assertEqual(value.executed_at_ms, 123)
        self.assertEqual(value.execution_fee, D("-1e-29"))

    def test_execution_id_requires_safe_text(self):
        for value in ("", " fill", "fill/1", "fill\n", "秘密", 1, None, "a" * 65):
            with self.subTest(value=value), self.assertRaises(RuntimeRiskError):
                execution(execution_id=value)

    def test_only_explicit_side_enum_is_accepted(self):
        for value in ("BUY", "SELL", "SHORT", RiskActionKind.ENTRY, None, True):
            with self.subTest(value=value), self.assertRaises(RuntimeRiskError):
                execution(side=value)

    def test_quantity_and_price_require_positive_exact_values(self):
        for name in ("executed_base_quantity", "execution_price"):
            for value in (D(0), D("-0"), D(-1), D("NaN"), D("sNaN"), D("Infinity"), 1, 1.0, True, "1"):
                with self.subTest(field=name, value=value), self.assertRaises(RuntimeRiskError):
                    execution(**{name: value})

    def test_fee_is_signed_but_finite_decimal(self):
        for value in (D("NaN"), D("sNaN"), D("Infinity"), D("-Infinity"), True, 0, 0.0, "0"):
            with self.subTest(value=value), self.assertRaises(RuntimeRiskError):
                execution(execution_fee=value)
        self.assertEqual(execution(execution_fee=D("-1")).execution_fee, D(-1))

    def test_fee_currency_requires_safe_uppercase_or_none(self):
        for value in ("", "btc", " BTC", "BTC\n", 1, True):
            with self.subTest(value=value), self.assertRaises(RuntimeRiskError):
                execution(fee_currency=value)
        self.assertIsNone(execution().fee_currency)

    def test_execution_time_is_nonnegative_bounded_int(self):
        for value in (-1, True, False, 1.0, D(1), "1", None, 2**63):
            with self.subTest(value=value), self.assertRaises(RuntimeRiskError):
                execution(executed_at_ms=value)
        self.assertEqual(execution(executed_at_ms=0).executed_at_ms, 0)


class AccountingTests(unittest.TestCase):
    def setUp(self):
        self.cfg = config()
        self.book = initial_risk_book(self.cfg)

    def test_initial_book_is_only_the_authorized_anchor(self):
        self.assertEqual(self.book, RiskBook(D(1000), D(0)))
        self.assertEqual({field.name for field in fields(RiskBook)}, {"virtual_quote_cash", "owned_base_quantity"})

    def test_buy_quote_fee(self):
        result = apply_owned_execution(self.cfg, self.book, execution(execution_fee=D("1.25"), fee_currency="USDT"))
        self.assertEqual(result, RiskBook(D("798.75"), D(2)))

    def test_buy_base_fee(self):
        result = apply_owned_execution(self.cfg, self.book, execution(execution_fee=D("0.01"), fee_currency="BTC"))
        self.assertEqual(result, RiskBook(D(800), D("1.99")))

    def test_buy_quote_rebate(self):
        result = apply_owned_execution(self.cfg, self.book, execution(execution_fee=D("-1.25"), fee_currency="USDT"))
        self.assertEqual(result, RiskBook(D("801.25"), D(2)))

    def test_buy_base_rebate(self):
        result = apply_owned_execution(self.cfg, self.book, execution(execution_fee=D("-0.01"), fee_currency="BTC"))
        self.assertEqual(result, RiskBook(D(800), D("2.01")))

    def test_sell_quote_fee(self):
        result = apply_owned_execution(self.cfg, RiskBook(D(800), D(2)), execution(
            side=RiskExecutionSide.SELL, execution_fee=D("0.25"), fee_currency="USDT"))
        self.assertEqual(result, RiskBook(D("999.75"), D(0)))

    def test_sell_base_fee(self):
        result = apply_owned_execution(self.cfg, RiskBook(D(800), D("2.01")), execution(
            side=RiskExecutionSide.SELL, execution_fee=D("0.01"), fee_currency="BTC"))
        self.assertEqual(result, RiskBook(D(1000), D(0)))

    def test_sell_quote_rebate(self):
        result = apply_owned_execution(self.cfg, RiskBook(D(800), D(2)), execution(
            side=RiskExecutionSide.SELL, execution_fee=D("-0.25"), fee_currency="USDT"))
        self.assertEqual(result, RiskBook(D("1000.25"), D(0)))

    def test_sell_base_rebate_leaves_owned_inventory(self):
        result = apply_owned_execution(self.cfg, RiskBook(D(800), D(2)), execution(
            side=RiskExecutionSide.SELL, execution_fee=D("-0.01"), fee_currency="BTC"))
        self.assertEqual(result, RiskBook(D(1000), D("0.01")))

    def test_oversell_and_base_fee_oversell_fail_atomically(self):
        for quantity, fee in (("2.01", "0"), ("2", "0.01")):
            book = RiskBook(D(800), D(2))
            before = deepcopy(book)
            with self.subTest(quantity=quantity, fee=fee), self.assertRaises(RuntimeRiskError):
                apply_owned_execution(self.cfg, book, execution(side=RiskExecutionSide.SELL,
                    executed_base_quantity=D(quantity), execution_fee=D(fee), fee_currency="BTC"))
            self.assertEqual(book, before)

    def test_negative_resulting_cash_is_retained(self):
        result = apply_owned_execution(self.cfg, RiskBook(D(1), D(0)), execution())
        self.assertEqual(result.virtual_quote_cash, D(-199))

    def test_unsupported_nonzero_fees_fail(self):
        for currency in (None, "BNB", "USD"):
            for fee in (D(1), D(-1)):
                with self.subTest(currency=currency, fee=fee), self.assertRaises(RuntimeRiskError):
                    apply_owned_execution(self.cfg, self.book, execution(execution_fee=fee, fee_currency=currency))

    def test_zero_fee_needs_no_currency_or_conversion(self):
        for currency in (None, "BTC", "USDT", "BNB"):
            with self.subTest(currency=currency):
                self.assertEqual(apply_owned_execution(self.cfg, self.book, execution(fee_currency=currency)),
                                 RiskBook(D(800), D(2)))

    def test_repeated_execution_is_explicitly_not_idempotent(self):
        once = apply_owned_execution(self.cfg, self.book, execution())
        twice = apply_owned_execution(self.cfg, once, execution())
        self.assertEqual(twice, RiskBook(D(600), D(4)))

    def test_execution_and_book_inputs_are_preserved(self):
        observation = execution(execution_fee=D("0.01"), fee_currency="BTC")
        before = deepcopy((self.cfg, self.book, observation))
        apply_owned_execution(self.cfg, self.book, observation)
        self.assertEqual((self.cfg, self.book, observation), before)

    def test_round_trip_fees_affect_equity_once(self):
        bought = apply_owned_execution(self.cfg, self.book, execution(
            execution_fee=D("0.01"), fee_currency="BTC"))
        self.assertEqual(calculate_risk_equity(bought, D(100)), D(999))
        sold = apply_owned_execution(self.cfg, bought, execution(
            execution_id="fill-2", side=RiskExecutionSide.SELL,
            executed_base_quantity=D("1.99"), execution_price=D(110),
            execution_fee=D("0.25"), fee_currency="USDT"))
        self.assertEqual(sold, RiskBook(D("1018.65"), D(0)))
        self.assertEqual(calculate_risk_equity(sold, D(110)), D("1018.65"))

    def test_book_rejects_nondecimal_nonfinite_or_negative_inventory(self):
        for field in ("virtual_quote_cash", "owned_base_quantity"):
            for value in (1, 1.0, True, "1", D("NaN"), D("sNaN"), D("Infinity")):
                with self.subTest(field=field, value=value), self.assertRaises(RuntimeRiskError):
                    replace(self.book, **{field: value})
        with self.assertRaises(RuntimeRiskError):
            RiskBook(D(1000), D("-0.00001"))

    def test_execution_algebra_is_independent_of_global_decimal_context(self):
        qty = D("1.234567890123456789012345678901")
        price = D("100.0000000000000000000000000001")
        obs = execution(executed_base_quantity=qty, execution_price=price,
                        execution_fee=D("-0.000000000000000000000000001"), fee_currency="USDT")
        with localcontext() as ctx:
            ctx.prec = 100
            expected = RiskBook(D(1000) - qty * price - obs.execution_fee, qty)
        for rounding in (ROUND_UP, ROUND_DOWN):
            with self.subTest(rounding=rounding), localcontext() as ctx:
                ctx.prec, ctx.rounding, ctx.Emax, ctx.Emin = 2, rounding, 9, -9
                ctx.traps[Inexact] = ctx.traps[Rounded] = ctx.traps[Underflow] = True
                self.assertEqual(apply_owned_execution(self.cfg, self.book, obs), expected)


class EquityTests(unittest.TestCase):
    def test_equity_is_cash_plus_marked_base(self):
        self.assertEqual(calculate_risk_equity(RiskBook(D("123.45"), D("0.25")), D("100.4")), D("148.55"))

    def test_negative_cash_and_positive_base_are_marked_honestly(self):
        self.assertEqual(calculate_risk_equity(RiskBook(D(-10), D(1)), D(15)), D(5))

    def test_equity_helper_returns_zero_or_negative_exactly(self):
        self.assertEqual(calculate_risk_equity(RiskBook(D(-10), D(1)), D(10)), D(0))
        self.assertEqual(calculate_risk_equity(RiskBook(D(-10), D(1)), D(9)), D(-1))

    def test_marks_require_positive_finite_exact_decimal(self):
        for value in (D(0), D("-0"), D(-1), D("NaN"), D("sNaN"), D("Infinity"), 1, True, 1.0, "1"):
            with self.subTest(value=value), self.assertRaises(RuntimeRiskError):
                calculate_risk_equity(RiskBook(D(1), D(0)), value)

    def test_high_precision_equity_has_exact_known_result(self):
        self.assertEqual(calculate_risk_equity(RiskBook(D("1e40"), D("1e-40")), D("1.23456789")),
                         D("10000000000000000000000000000000000000000.000000000000000000000000000000000000000123456789"))

    def test_large_small_and_cancelling_numbers_survive_hostile_context(self):
        for book, mark, expected in (
            (RiskBook(D("1e400"), D("1e-400")), D("1e400"), D("1" + "0" * 399 + "1")),
            (RiskBook(D("-1e400"), D("1e200")), D("1e200"), D(0)),
            (RiskBook(D("1e-400"), D("1e-200")), D("1e-200"), D("2e-400")),
        ):
            with self.subTest(book=book), localcontext() as ctx:
                ctx.prec, ctx.Emax, ctx.Emin = 1, 9, -9
                ctx.traps[Inexact] = ctx.traps[Rounded] = True
                self.assertEqual(calculate_risk_equity(book, mark), expected)

    def test_out_of_bound_arithmetic_fails_without_rounding_or_clamping(self):
        with self.assertRaises(RuntimeRiskError):
            calculate_risk_equity(RiskBook(D(0), D("1e3000")), D("1e3000"))

    def test_zero_with_huge_exponent_does_not_expand_precision(self):
        self.assertEqual(calculate_risk_equity(RiskBook(D("0e999999999"), D(0)), D(1)), D(0))

    def test_projected_exposure_keeps_full_pending_reservation(self):
        result = calculate_projected_exposure(D("0.5"), D(100), D(50), D(100))
        self.assertEqual(result, D(200))

    def test_projected_exposure_default_has_no_pending_reservation(self):
        self.assertEqual(calculate_projected_exposure(D(0), D(100), D(50)), D(50))

    def test_projected_exposure_validation(self):
        for index, value in ((0, D(-1)), (1, D(0)), (2, D(-1)), (3, D(-1)), (3, 0.0)):
            args = [D(0), D(1), D(0), D(0)]
            args[index] = value
            with self.subTest(index=index, value=value), self.assertRaises(RuntimeRiskError):
                calculate_projected_exposure(*args)


class StateValidationTests(unittest.TestCase):
    def test_first_partial_day_initialization(self):
        state = initial(equity="1234", at=3 * HOUR)
        self.assertEqual((state.epoch_started_at_ms, state.valued_at_ms, state.utc_day_start_ms), (3 * HOUR, 3 * HOUR, 0))
        self.assertEqual((state.risk_equity, state.peak_risk_equity, state.utc_day_start_risk_equity), (D(1234),) * 3)
        self.assertEqual((state.daily_pnl, state.drawdown_numerator, state.entries_this_utc_day), (D(0), D(0), 0))
        self.assertIsNone(state.trip_reason)
        self.assertFalse(state.trip_pending_report)

    def test_initial_equity_comes_from_current_book_not_capital_reset(self):
        state = initialize_risk_state(config(), RiskBook(D(800), D(1)), D(150), HOUR)
        self.assertEqual(state.risk_equity, D(950))
        self.assertEqual(state.peak_risk_equity, D(950))

    def test_zero_or_negative_equity_cannot_initialize(self):
        for equity in ("0", "-0", "-1"):
            with self.subTest(equity=equity), self.assertRaises(RuntimeRiskError):
                initial(equity=equity)

    def test_only_hourly_nonnegative_int_valuation_time_is_accepted(self):
        for at in (-HOUR, 1, HOUR + 1, True, 0.0, D(0), "0", 2**63):
            with self.subTest(at=at), self.assertRaises(RuntimeRiskError):
                initial(at=at)

    def test_epoch_cannot_start_after_valuation(self):
        with self.assertRaises(RuntimeRiskError):
            replace(initial(), epoch_started_at_ms=HOUR)

    def test_day_start_must_be_correct_utc_midnight(self):
        for day in (1, -1, HOUR, DAY, True):
            with self.subTest(day=day), self.assertRaises(RuntimeRiskError):
                replace(initial(at=HOUR), utc_day_start_ms=day)

    def test_equity_peak_and_baseline_require_positive_finite_decimals(self):
        for name in ("risk_equity", "peak_risk_equity", "utc_day_start_risk_equity"):
            for value in (D(0), D(-1), D("NaN"), D("sNaN"), D("Infinity"), 1000, 1000.0, True, "1000"):
                with self.subTest(field=name, value=value), self.assertRaises(RuntimeRiskError):
                    replace(initial(), **{name: value})

    def test_peak_cannot_be_below_equity_or_baseline(self):
        with self.assertRaises(RuntimeRiskError):
            replace(initial(), peak_risk_equity=D(999))
        with self.assertRaises(RuntimeRiskError):
            replace(next_equity(initial(), "950"), peak_risk_equity=D(950))

    def test_daily_pnl_is_exactly_reconciled(self):
        with self.assertRaises(RuntimeRiskError):
            replace(initial(), daily_pnl=D("0.00000000000000000000001"))
        for value in (1, True, 1.0, "0", D("NaN")):
            with self.subTest(value=value), self.assertRaises(RuntimeRiskError):
                replace(initial(), daily_pnl=value)

    def test_entries_are_nonnegative_python_int(self):
        for value in (-1, True, 0.0, D(0), "0", None):
            with self.subTest(value=value), self.assertRaises(RuntimeRiskError):
                replace(initial(), entries_this_utc_day=value)

    def test_trip_time_and_reason_must_exist_together(self):
        for changes in ({"tripped_at_ms": 0}, {"trip_reason": RiskReason.DAILY_LOSS_LIMIT},
                        {"trip_pending_report": True}):
            with self.subTest(changes=changes), self.assertRaises(RuntimeRiskError):
                replace(initial(), **changes)

    def test_only_breaker_reasons_can_latch(self):
        for reason in (RiskReason.ENTRY_COUNT_LIMIT, RiskReason.ENTRY_NOTIONAL_LIMIT,
                       RiskReason.POSITION_NOTIONAL_LIMIT, RiskReason.RISK_LATCH_ACTIVE,
                       "DAILY_LOSS_LIMIT", True):
            with self.subTest(reason=reason), self.assertRaises(RuntimeRiskError):
                replace(initial(), trip_reason=reason, tripped_at_ms=0)

    def test_trip_time_must_be_in_epoch_history_on_hour(self):
        state = initial(at=HOUR)
        for at in (0, 2 * HOUR, HOUR + 1, True, 0.0):
            with self.subTest(at=at), self.assertRaises(RuntimeRiskError):
                replace(state, trip_reason=RiskReason.MAX_DRAWDOWN, tripped_at_ms=at)

    def test_trip_pending_flag_requires_bool(self):
        with self.assertRaises(RuntimeRiskError):
            replace(initial(), trip_pending_report=1)

    def test_gapped_duplicate_or_backward_hours_fail(self):
        state = initial(at=2 * HOUR)
        for at in (0, HOUR, 2 * HOUR, 4 * HOUR, 3 * HOUR + 1):
            with self.subTest(at=at), self.assertRaises(RuntimeRiskError):
                advance_risk_state(config(), state, RiskBook(D(1000), D(0)), D(1), at)

    def test_advancing_to_zero_or_negative_equity_fails_without_mutation(self):
        state = initial()
        for equity in ("0", "-1"):
            with self.subTest(equity=equity), self.assertRaises(RuntimeRiskError):
                next_equity(state, equity)
        self.assertEqual(state, initial())

    def test_inconsistent_book_or_mark_is_rejected_before_any_verdict(self):
        for book, mark in ((RiskBook(D(999), D(0)), D(1)), (RiskBook(D(0), D(1)), D(999))):
            with self.subTest(book=book), self.assertRaises(RuntimeRiskError):
                evaluate(initial(), entry(), book=book, mark=mark)

    def test_bypassed_constructor_is_revalidated(self):
        state = initial()
        object.__setattr__(state, "daily_pnl", D(1))
        with self.assertRaises(RuntimeRiskError):
            evaluate(state, entry())

    def test_incomplete_bypassed_record_is_a_sanitized_domain_error(self):
        state = initial()
        object.__delattr__(state, "daily_pnl")
        with self.assertRaises(RuntimeRiskError) as caught:
            evaluate(state, entry())
        self.assertEqual(str(caught.exception), "A complete valid pure risk record is required.")
        self.assertIsNone(caught.exception.__context__)


class DailyLossTests(unittest.TestCase):
    def test_flat_and_profitable_equity_do_not_trip(self):
        for equity in ("1000", "1100"):
            with self.subTest(equity=equity):
                state = next_equity(initial(), equity)
                self.assertIsNone(state.trip_reason)
                self.assertIs(evaluate(state).verdict, RiskVerdict.ALLOW)

    def test_exact_daily_threshold_trips(self):
        state = next_equity(initial(), "900")
        self.assertIs(state.trip_reason, RiskReason.DAILY_LOSS_LIMIT)
        self.assertEqual(state.daily_pnl, D(-100))
        self.assertIs(evaluate(state).verdict, RiskVerdict.TRIP)

    def test_one_quantum_before_threshold_does_not_trip(self):
        state = next_equity(initial(), "900.0000000000000000000000000001")
        self.assertIsNone(state.trip_reason)

    def test_one_quantum_beyond_threshold_trips(self):
        self.assertIs(next_equity(initial(), "899.9999999999999999999999999999").trip_reason,
                      RiskReason.DAILY_LOSS_LIMIT)

    def test_daily_boundary_comparison_ignores_global_rounding(self):
        for equity, expected in (("900", RiskReason.DAILY_LOSS_LIMIT),
                                 ("900.0000000000000000000000000001", None)):
            with self.subTest(equity=equity), localcontext() as ctx:
                ctx.prec, ctx.rounding = 1, ROUND_DOWN
                ctx.traps[Inexact] = ctx.traps[Rounded] = True
                self.assertIs(next_equity(initial(), equity).trip_reason, expected)

    def test_daily_threshold_uses_fixed_capital_after_profit(self):
        # A new UTC day starts at equity 2000; its loss allowance is still 100.
        state = next_equity(initial(equity="2000", at=23 * HOUR), "2000")
        state = next_equity(state, "1900")
        self.assertIs(state.trip_reason, RiskReason.DAILY_LOSS_LIMIT)

    def test_unrealized_mark_decline_trips_without_a_sell(self):
        book = RiskBook(D(0), D(10))
        state = initialize_risk_state(config(), book, D(100), 0)
        state = advance_risk_state(config(), state, book, D(90), HOUR)
        self.assertIs(state.trip_reason, RiskReason.DAILY_LOSS_LIMIT)
        self.assertEqual(book.owned_base_quantity, D(10))

    def test_midnight_checks_final_hour_against_outgoing_baseline(self):
        state = next_equity(initial(at=23 * HOUR), "900")
        self.assertIs(state.trip_reason, RiskReason.DAILY_LOSS_LIMIT)
        self.assertEqual(state.tripped_at_ms, DAY)
        self.assertEqual((state.utc_day_start_ms, state.utc_day_start_risk_equity, state.daily_pnl), (DAY, D(900), D(0)))
        self.assertIs(evaluate(state).verdict, RiskVerdict.TRIP)

    def test_midnight_before_threshold_does_not_trip(self):
        state = next_equity(initial(at=23 * HOUR), "900.0000000000000000000000000001")
        self.assertIsNone(state.trip_reason)
        self.assertEqual(state.daily_pnl, D(0))

    def test_midnight_resets_entries_before_next_action_evaluation(self):
        state = replace(initial(at=23 * HOUR), entries_this_utc_day=2)
        state = next_equity(state, "1000")
        result = evaluate(state, entry())
        self.assertIs(result.verdict, RiskVerdict.ALLOW)
        self.assertEqual(result.state.entries_this_utc_day, 1)

    def test_midnight_never_clears_existing_latch(self):
        state = evaluate(next_equity(initial(at=22 * HOUR), "900")).state
        state = next_equity(state, "1000")
        self.assertEqual(state.utc_day_start_ms, DAY)
        self.assertIs(state.trip_reason, RiskReason.DAILY_LOSS_LIMIT)
        self.assertEqual(state.tripped_at_ms, 23 * HOUR)
        self.assertIs(evaluate(state, entry()).verdict, RiskVerdict.BLOCK)

    def test_each_missing_hour_must_be_replayed(self):
        state = initial()
        for hour in range(1, 26):
            state = next_equity(state, "900" if hour == 5 else "1000")
        self.assertEqual(state.valued_at_ms, 25 * HOUR)
        self.assertEqual(state.tripped_at_ms, 5 * HOUR)
        self.assertIs(state.trip_reason, RiskReason.DAILY_LOSS_LIMIT)

    def test_day_baseline_is_not_reset_at_an_intraday_advance(self):
        state = initial(at=HOUR)
        state = next_equity(state, "950")
        state = next_equity(state, "900")
        self.assertEqual(state.utc_day_start_risk_equity, D(1000))
        self.assertIs(state.trip_reason, RiskReason.DAILY_LOSS_LIMIT)


class DrawdownTests(unittest.TestCase):
    def setUp(self):
        self.cfg = config(max_daily_loss_fraction=D(1))

    def test_new_high_updates_peak(self):
        state = next_equity(initial(cfg=self.cfg), "1200", cfg=self.cfg)
        self.assertEqual(state.peak_risk_equity, D(1200))
        self.assertEqual((state.drawdown_numerator, state.drawdown_denominator), (D(0), D(1200)))

    def test_decline_below_threshold_does_not_trip(self):
        self.assertIsNone(next_equity(initial(), "800.0000000000000000000000000001", cfg=self.cfg).trip_reason)

    def test_exact_drawdown_threshold_trips(self):
        state = next_equity(initial(), "800", cfg=self.cfg)
        self.assertIs(state.trip_reason, RiskReason.MAX_DRAWDOWN)
        self.assertEqual((state.drawdown_numerator, state.drawdown_denominator), (D(200), D(1000)))

    def test_drawdown_uses_peak_not_initial_capital(self):
        state = next_equity(initial(), "2000", cfg=self.cfg)
        state = next_equity(state, "1600", cfg=self.cfg)
        self.assertIs(state.trip_reason, RiskReason.MAX_DRAWDOWN)

    def test_nonterminating_diagnostic_is_an_exact_pair(self):
        state = next_equity(initial(equity="3"), "2", cfg=self.cfg)
        self.assertEqual((state.drawdown_numerator, state.drawdown_denominator), (D(1), D(3)))
        self.assertIs(state.trip_reason, RiskReason.MAX_DRAWDOWN)

    def test_midnight_does_not_reset_peak_or_hide_drawdown(self):
        state = next_equity(initial(at=23 * HOUR), "800", cfg=self.cfg)
        self.assertEqual(state.peak_risk_equity, D(1000))
        self.assertEqual(state.daily_pnl, D(0))
        self.assertIs(state.trip_reason, RiskReason.MAX_DRAWDOWN)

    def test_recovery_and_new_high_preserve_original_latch(self):
        state = next_equity(initial(), "800", cfg=self.cfg)
        state = evaluate(state, cfg=self.cfg).state
        state = next_equity(state, "1100", cfg=self.cfg)
        self.assertEqual(state.peak_risk_equity, D(1100))
        self.assertIs(state.trip_reason, RiskReason.MAX_DRAWDOWN)
        self.assertEqual(state.tripped_at_ms, HOUR)
        self.assertEqual(state.drawdown_numerator, D(0))

    def test_daily_reason_wins_simultaneous_first_breach(self):
        state = next_equity(initial(), "800")
        self.assertIs(state.trip_reason, RiskReason.DAILY_LOSS_LIMIT)
        self.assertEqual(state.tripped_at_ms, HOUR)
        state = next_equity(state, "700")
        self.assertIs(state.trip_reason, RiskReason.DAILY_LOSS_LIMIT)
        self.assertEqual(state.tripped_at_ms, HOUR)

    def test_later_daily_breach_cannot_rewrite_drawdown_latch(self):
        cfg = config(max_daily_loss_fraction=D("0.9"), max_drawdown_fraction=D("0.1"))
        state = next_equity(initial(), "850", cfg=cfg)
        state = next_equity(state, "50", cfg=cfg)
        self.assertIs(state.trip_reason, RiskReason.MAX_DRAWDOWN)
        self.assertEqual(state.tripped_at_ms, HOUR)

    def test_thresholds_are_independent_of_global_decimal_context(self):
        for equity, reason in (("800", RiskReason.MAX_DRAWDOWN),
                               ("800.0000000000000000000000000001", None),
                               ("799.9999999999999999999999999999", RiskReason.MAX_DRAWDOWN)):
            with self.subTest(equity=equity), localcontext() as ctx:
                ctx.prec, ctx.rounding = 1, ROUND_UP
                ctx.traps[Inexact] = ctx.traps[Rounded] = True
                state = next_equity(initial(), equity, cfg=self.cfg)
                self.assertIs(state.trip_reason, reason)


class PolicyTests(unittest.TestCase):
    def test_first_entry_allows_and_consumes_exactly_one_count(self):
        state = initial()
        result = evaluate(state, entry())
        self.assertIs(result.verdict, RiskVerdict.ALLOW)
        self.assertIsNone(result.reason)
        self.assertEqual(result.state.entries_this_utc_day, 1)
        self.assertEqual(state.entries_this_utc_day, 0)

    def test_entry_count_limit_blocks_without_increment(self):
        state = evaluate(initial(), entry()).state
        state = evaluate(state, entry()).state
        result = evaluate(state, entry())
        self.assertIs(result.verdict, RiskVerdict.BLOCK)
        self.assertIs(result.reason, RiskReason.ENTRY_COUNT_LIMIT)
        self.assertEqual(result.state.entries_this_utc_day, 2)

    def test_entry_count_precedes_notional_limits(self):
        result = evaluate(replace(initial(), entries_this_utc_day=2), entry("10000"))
        self.assertIs(result.reason, RiskReason.ENTRY_COUNT_LIMIT)

    def test_exact_entry_and_position_cap_equality_is_allowed(self):
        cfg = config(buy_quote_budget=D(1000), max_entry_notional_quote=D(1000), max_position_notional_quote=D(1000))
        self.assertIs(evaluate(initial(cfg=cfg), entry("1000"), cfg=cfg).verdict, RiskVerdict.ALLOW)

    def test_entry_limit_one_quantum_above_blocks_without_resize(self):
        proposal = entry("200.0000000000000000000000000001")
        result = evaluate(initial(), proposal)
        self.assertIs(result.reason, RiskReason.ENTRY_NOTIONAL_LIMIT)
        self.assertEqual(result.state.entries_this_utc_day, 0)
        self.assertEqual(proposal.authorized_amount, D("200.0000000000000000000000000001"))

    def test_proposal_above_position_cap_is_also_over_entry_cap(self):
        # Ordered caps plus FLAT-only ENTRY make the entry limit stricter here;
        # never forge invalid config/owned state merely to hit a later branch.
        result = evaluate(initial(), entry("500.000000000000000000000000001"))
        self.assertIs(result.reason, RiskReason.ENTRY_NOTIONAL_LIMIT)
        self.assertGreater(calculate_projected_exposure(D(0), D(1), D("500.000000000000000000000000001")), D(500))

    def test_owned_entry_is_invalid_even_below_caps(self):
        book = RiskBook(D(999), D(1))
        for state in (initial(), evaluate(next_equity(initial(), "900")).state):
            matching = RiskBook(D(999) if state.risk_equity == 1000 else D(899), D(1))
            with self.subTest(latched=state.trip_reason), self.assertRaises(RuntimeRiskError):
                evaluate(state, entry("1"), book=matching)
        self.assertEqual(book.owned_base_quantity, D(1))

    def test_healthy_exact_exit_ignores_entry_limits_and_count(self):
        state = replace(initial(), entries_this_utc_day=100)
        result = evaluate(state, exit_proposal("10"), book=RiskBook(D(0), D(10)), mark=D(100))
        self.assertIs(result.verdict, RiskVerdict.ALLOW)
        self.assertEqual(result.state.entries_this_utc_day, 100)

    def test_wrong_exit_amount_is_invalid_even_if_smaller(self):
        for amount in ("0.5", "1.00000000000000000000001", "2"):
            with self.subTest(amount=amount), self.assertRaises(RuntimeRiskError):
                evaluate(initial(), exit_proposal(amount), book=RiskBook(D(999), D(1)))

    def test_exit_while_flat_is_invalid(self):
        with self.assertRaises(RuntimeRiskError):
            evaluate(initial(), exit_proposal())

    def test_no_proposal_allows_no_action_and_consumes_no_entry(self):
        result = evaluate(initial())
        self.assertIs(result.verdict, RiskVerdict.ALLOW)
        self.assertIsNone(result.reason)
        self.assertEqual(result.state.entries_this_utc_day, 0)
        self.assertEqual({field.name for field in fields(result)}, {"state", "verdict", "reason"})

    def test_new_trip_with_entry_returns_trip_without_count(self):
        result = evaluate(next_equity(initial(), "900"), entry())
        self.assertIs(result.verdict, RiskVerdict.TRIP)
        self.assertIs(result.reason, RiskReason.DAILY_LOSS_LIMIT)
        self.assertEqual(result.state.entries_this_utc_day, 0)
        self.assertFalse(result.state.trip_pending_report)

    def test_existing_latch_blocks_entry(self):
        state = evaluate(next_equity(initial(), "900")).state
        result = evaluate(state, entry())
        self.assertIs(result.verdict, RiskVerdict.BLOCK)
        self.assertIs(result.reason, RiskReason.RISK_LATCH_ACTIVE)
        self.assertIs(result.state.trip_reason, RiskReason.DAILY_LOSS_LIMIT)
        self.assertEqual(result.state.tripped_at_ms, HOUR)

    def test_existing_trip_no_proposal_allows_accounting_only(self):
        state = evaluate(next_equity(initial(), "900")).state
        result = evaluate(state)
        self.assertIs(result.verdict, RiskVerdict.ALLOW)
        self.assertIsNotNone(result.state.trip_reason)

    def test_new_trip_with_exact_exit_allows_and_preserves_latch(self):
        state = next_equity(initial(), "900")
        result = evaluate(state, exit_proposal(), book=RiskBook(D(800), D(1)), mark=D(100))
        self.assertIs(result.verdict, RiskVerdict.ALLOW)
        self.assertIsNone(result.reason)
        self.assertIs(result.state.trip_reason, RiskReason.DAILY_LOSS_LIMIT)
        self.assertEqual(result.state.tripped_at_ms, HOUR)
        self.assertFalse(result.state.trip_pending_report)

    def test_existing_trip_exact_exit_is_allowed(self):
        state = evaluate(next_equity(initial(), "900")).state
        result = evaluate(state, exit_proposal(), book=RiskBook(D(800), D(1)), mark=D(100))
        self.assertIs(result.verdict, RiskVerdict.ALLOW)
        self.assertEqual(result.state.trip_reason, state.trip_reason)

    def test_tripped_wrong_exit_is_error_not_block(self):
        state = evaluate(next_equity(initial(), "900")).state
        with self.assertRaises(RuntimeRiskError):
            evaluate(state, exit_proposal("0.5"), book=RiskBook(D(800), D(1)), mark=D(100))

    def test_unreported_trip_survives_further_valuations(self):
        state = next_equity(next_equity(initial(), "900"), "1100")
        result = evaluate(state)
        self.assertIs(result.verdict, RiskVerdict.TRIP)
        self.assertEqual(result.state.tripped_at_ms, HOUR)

    def test_evaluation_rechecks_unlatched_snapshot_thresholds(self):
        state = replace(initial(), valued_at_ms=HOUR, risk_equity=D(900), daily_pnl=D(-100))
        result = evaluate(state, entry())
        self.assertIs(result.verdict, RiskVerdict.TRIP)
        self.assertIs(result.state.trip_reason, RiskReason.DAILY_LOSS_LIMIT)

    def test_latch_precedes_count_and_cap_refusals(self):
        state = replace(evaluate(next_equity(initial(), "900")).state, entries_this_utc_day=2)
        result = evaluate(state, entry("10000"))
        self.assertIs(result.reason, RiskReason.RISK_LATCH_ACTIVE)

    def test_broken_valuation_never_allows_even_exact_exit(self):
        state = evaluate(next_equity(initial(), "900")).state
        with self.assertRaises(RuntimeRiskError):
            evaluate(state, exit_proposal(), book=RiskBook(D(801), D(1)), mark=D(100))

    def test_block_does_not_mutate_or_refund_existing_count(self):
        state = replace(initial(), entries_this_utc_day=1)
        before = deepcopy(state)
        result = evaluate(state, entry("201"))
        self.assertIs(result.verdict, RiskVerdict.BLOCK)
        self.assertEqual(result.state.entries_this_utc_day, 1)
        self.assertEqual(state, before)

    def test_policy_is_deterministic_and_preserves_all_inputs(self):
        state, book, proposal, cfg = initial(), RiskBook(D(1000), D(0)), entry(), config()
        before = deepcopy((state, book, proposal, cfg))
        first = evaluate(state, proposal, book=book, cfg=cfg)
        self.assertEqual(evaluate(state, proposal, book=book, cfg=cfg), first)
        self.assertEqual((state, book, proposal, cfg), before)

    def test_proposal_requires_kind_enum_and_positive_decimal(self):
        for kind in ("ENTRY", "EXIT", RiskExecutionSide.BUY, None):
            with self.subTest(kind=kind), self.assertRaises(RuntimeRiskError):
                RiskActionProposal(kind, D(1))
        for value in (D(0), D("-0"), D(-1), D("NaN"), D("Infinity"), 1, True, 1.0, "1"):
            with self.subTest(value=value), self.assertRaises(RuntimeRiskError):
                RiskActionProposal(RiskActionKind.ENTRY, value)

    def test_result_record_rejects_inconsistent_verdict_reason(self):
        state = initial()
        for verdict, reason in (("ALLOW", None), (RiskVerdict.ALLOW, RiskReason.ENTRY_COUNT_LIMIT),
                                (RiskVerdict.BLOCK, None), (RiskVerdict.BLOCK, RiskReason.DAILY_LOSS_LIMIT),
                                (RiskVerdict.TRIP, RiskReason.MAX_DRAWDOWN),
                                (RiskVerdict.BLOCK, RiskReason.RISK_LATCH_ACTIVE)):
            with self.subTest(verdict=verdict, reason=reason), self.assertRaises(RuntimeRiskError):
                RiskEvaluation(state, verdict, reason)

    def test_wrong_record_types_fail_with_domain_error(self):
        calls = (
            lambda: initial_risk_book(None),
            lambda: apply_owned_execution(config(), None, execution()),
            lambda: apply_owned_execution(config(), initial_risk_book(config()), {}),
            lambda: calculate_risk_equity({}, D(1)),
            lambda: advance_risk_state(config(), {}, RiskBook(D(1), D(0)), D(1), HOUR),
            lambda: evaluate(initial(), {}),
        )
        for call in calls:
            with self.subTest(call=call), self.assertRaises(RuntimeRiskError):
                call()


class BoundaryTests(unittest.TestCase):
    def test_enum_sets_are_exact(self):
        self.assertEqual({item.value for item in RiskVerdict}, {"ALLOW", "BLOCK", "TRIP"})
        self.assertEqual({item.value for item in RiskReason}, {"ENTRY_NOTIONAL_LIMIT", "POSITION_NOTIONAL_LIMIT",
            "ENTRY_COUNT_LIMIT", "RISK_LATCH_ACTIVE", "DAILY_LOSS_LIMIT", "MAX_DRAWDOWN"})
        self.assertEqual({item.value for item in RiskActionKind}, {"ENTRY", "EXIT"})
        self.assertEqual({item.value for item in RiskExecutionSide}, {"BUY", "SELL"})

    def test_all_public_records_are_frozen_slotted_and_immutable(self):
        records = (config(), execution(), initial_risk_book(config()), initial(), entry(), evaluate(initial()))
        for record in records:
            with self.subTest(record=type(record)):
                self.assertFalse(hasattr(record, "__dict__"))
                self.assertTrue(record.__dataclass_params__.frozen)
                name = fields(record)[0].name
                with self.assertRaises(FrozenInstanceError):
                    setattr(record, name, getattr(record, name))

    def test_replace_revalidates_all_record_invariants(self):
        for record, changes in (
            (config(), {"risk_capital_quote": D(0)}),
            (execution(), {"executed_base_quantity": D(0)}),
            (initial_risk_book(config()), {"owned_base_quantity": D(-1)}),
            (initial(), {"daily_pnl": D(1)}),
            (entry(), {"authorized_amount": D(0)}),
            (evaluate(initial()), {"reason": RiskReason.ENTRY_COUNT_LIMIT}),
        ):
            with self.subTest(record=type(record)), self.assertRaises(RuntimeRiskError):
                replace(record, **changes)

    def test_no_external_import_or_io_capability(self):
        tree = ast.parse(inspect.getsource(module))
        imports = {node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        self.assertEqual(imports, {"dataclasses", "decimal", "enum"})
        self.assertFalse(any(isinstance(node, ast.Import) for node in ast.walk(tree)))
        forbidden = {"runtime", "exchange", "strategies", "backtest", "sqlite3", "requests", "pybit", "pandas", "numpy",
                     "os", "socket", "sleep", "open", "connect", "execute", "commit", "place_order", "cancel_order",
                     "get_wallet_balance", "PlanKind", "ActionPlan", "RuntimeCheckpoint", "RuntimeState", "ActionRecord",
                     "OwnedFillRecord", "position_sizing", "position_fraction", "calculate_position_budget"}
        references = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        references |= {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
        self.assertFalse(references & forbidden)
        self.assertFalse(any(isinstance(node, (ast.While, ast.AsyncFunctionDef, ast.Await)) for node in ast.walk(tree)))

    def test_public_api_has_no_rearm_resize_or_liquidation_action(self):
        public = set(module.__all__)
        forbidden = {"rearm", "reset", "liquidate", "stop_loss", "take_profit", "trailing_stop", "force_sell",
                     "place_order", "cancel_order", "resize", "reduce"}
        self.assertFalse(public & forbidden)
        functions = {name for name, value in vars(module).items()
                     if inspect.isfunction(value) and value.__module__ == module.__name__ and not name.startswith("_")}
        self.assertEqual(functions, {"initial_risk_book", "apply_owned_execution", "calculate_risk_equity",
            "initialize_risk_state", "advance_risk_state", "evaluate_risk", "calculate_projected_exposure", "rearm_risk_state"})

    def test_no_module_level_activation_calls(self):
        tree = ast.parse(inspect.getsource(module))
        for node in tree.body:
            with self.subTest(node=type(node).__name__):
                self.assertIsInstance(node, (ast.Expr, ast.ImportFrom, ast.Assign, ast.ClassDef, ast.FunctionDef))
                if isinstance(node, ast.Expr):
                    self.assertIsInstance(node.value, ast.Constant)

    def test_error_messages_do_not_echo_caller_data(self):
        secret = "SENSITIVE_CALLER_VALUE"
        for call in (lambda: config(base_currency=secret.lower()),
                     lambda: execution(execution_id=secret + "\n"),
                     lambda: calculate_risk_equity(RiskBook(D(1), D(0)), secret),
                     lambda: evaluate(initial(), secret)):
            with self.subTest(call=call), self.assertRaises(RuntimeRiskError) as caught:
                call()
            self.assertNotIn(secret, str(caught.exception))
            self.assertIsNone(caught.exception.__cause__)


if __name__ == "__main__":
    unittest.main()
